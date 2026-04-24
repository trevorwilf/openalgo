"""BrokerOrderTranslator — the promoted-lane contract for per-broker
order translation.

A broker translator owns three responsibilities:

1. **Validation** — reject orders the broker cannot honor (unsupported
   order type, venue, quantity unit, session, etc.) before anything
   hits the wire. Throw ``UnsupportedCapability`` so callers can map
   the failure to a structured 422.
2. **Translation to native** — produce the broker's request body / dict
   from the :class:`NormalizedOrderRequest` plus a resolved instrument.
3. **Translation from native** — take the broker's response envelope
   and return OpenAlgo's normalized order-response dict (``order_id``,
   ``status``, etc.) so ``/api/v2/orders`` can return a consistent
   shape regardless of broker.

Promoted brokers are registered into
:mod:`services.broker_translator_registry` at startup. The promoted
``/api/v2/orders`` dispatcher looks the broker up by code when the
per-broker flag ``API_V2_<BROKER_CODE_UPPER>`` is set. If no translator
is registered for a promoted broker, the route returns 503.

This module intentionally uses :class:`typing.Protocol` rather than an
abstract base class. Broker adapters don't inherit — they just satisfy
the shape. That keeps the promoted lane free from an "OpenAlgo base
class" dependency and makes testing with fakes trivial.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from domain.orders import NormalizedOrderRequest


class AccountContext(TypedDict, total=False):
    """Minimal account context passed to the translator.

    Intentionally permissive — broker adapters may carry extra fields
    in ``extra``; new keys may be added without breaking existing
    translators.
    """

    broker_code: str
    base_currency: str
    account_id: str
    extra: dict[str, Any]


@runtime_checkable
class BrokerOrderTranslator(Protocol):
    """Contract for per-broker order translation on the promoted lane.

    Implementations are registered into
    :mod:`services.broker_translator_registry` and looked up by
    ``broker_code`` when the per-broker feature flag is set.
    """

    broker_code: str
    """Lower-case broker identifier — must match the broker's
    ``plugin.json`` ``broker_code`` field and the last segment of the
    ``API_V2_<BROKER_CODE_UPPER>`` flag name."""

    def validate(
        self,
        order: "NormalizedOrderRequest",
        instrument: Any,
        account_ctx: AccountContext,
    ) -> None:
        """Raise if this order cannot be honored by the broker.

        Inputs:
            order: the validated, cross-field-checked
                :class:`NormalizedOrderRequest`.
            instrument: the resolved instrument object (Phase 4 returns
                a ``ResolvedInstrument``; until then, callers may pass
                an instrument record from
                :func:`database.instruments_repo.instruments_get_by_id`
                or an equivalent shape).
            account_ctx: :class:`AccountContext` with at least
                ``broker_code`` and ``base_currency``.

        Returns:
            ``None`` on success.

        Raises:
            domain.errors.UnsupportedCapability: when the broker cannot
                honor a specific normalized field — e.g. an unsupported
                ``OrderType`` or ``TimeInForce``.
            ValueError: for other validation failures that are not
                capability-level (e.g. insufficient price precision for
                the tick size).
        """

    def to_native(
        self,
        order: "NormalizedOrderRequest",
        instrument: Any,
        account_ctx: AccountContext,
    ) -> dict[str, Any]:
        """Build the broker's native request body.

        The returned dict is passed to the broker's HTTP / SDK call by
        the promoted dispatcher — the translator does not make network
        calls itself. Keeping translation pure keeps testing trivial.

        Raises:
            domain.errors.UnsupportedCapability: if a field that
                :meth:`validate` did not reject cannot be expressed
                natively. Translators should ideally catch these in
                :meth:`validate`, but this exception is the correct
                surface if ``to_native`` is called on unsupported
                input regardless.
        """

    def from_native_order_response(
        self,
        payload: dict[str, Any],
        instrument: Any,
    ) -> dict[str, Any]:
        """Map the broker's order-creation response to the normalized
        response envelope.

        The returned dict is merged into ``/api/v2/orders``' response
        body. At minimum it should include an ``order_id`` and a
        ``status`` field. Implementations may include broker-specific
        fields under a ``native`` subkey for consumers that need them.

        Raises:
            ValueError: when ``payload`` is malformed (missing required
                broker fields).
        """


__all__ = ["BrokerOrderTranslator", "AccountContext"]
