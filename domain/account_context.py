"""AccountContext — structured account identity passed to promoted-lane translators.

Replaces the prior loose ``TypedDict`` shape that carried only
``{broker_code, account_id}``. The new model is the single object that
flows from the v2 dispatcher into:

* :class:`domain.broker_translator.BrokerOrderTranslator` ``validate``,
  ``to_native``, ``send_native``,
* :class:`domain.broker_market_data.BrokerQuoteAdapter` /
  :class:`BrokerBarAdapter`,
* :func:`services.rule_enforcement.check_order` (Phase 3 onwards).

Schwab carries account *hashes* rather than raw IDs; Webull-style
sub-accounts use ``subaccount_id``; market-data entitlements drive
"real-time data not entitled" rejects (Phase 8). All such fields live
here so future broker plugins do not need ad-hoc dicts.

The class is ``frozen=True, extra="forbid"`` so a translator typo on
field name fails at construction rather than silently dropping data.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domain.currency import Currency


class AccountContext(BaseModel):
    """Structured account context passed to promoted-lane components.

    Attributes
    ----------
    broker_code:
        Lower-case broker identifier (matches the broker plugin
        ``broker_code`` and the per-broker ``API_V2_<BROKER>`` flag).
    account_id:
        Stable account identifier as the broker presents it. For
        brokers that hash account IDs in URLs (Schwab), this is the
        canonical ID and ``account_hash`` carries the URL fragment.
    account_hash:
        Optional URL-safe hash. Schwab's account hashes go here.
    base_currency:
        The account's settlement currency. Used by rule enforcement
        and currency-formatting layers.
    subaccount_id:
        Optional sub-account identifier. Webull-style sub-accounts go
        here; brokers without sub-accounts leave it ``None``.
    entitlements:
        Per-account market-data permissions surfaced by the broker
        (e.g. "us_equity_realtime", "options_l1"). Phase 8 wires this
        into :func:`services.rule_enforcement.check_order` so a
        request that needs an unentitled feed fails with a structured
        reject.
    extra:
        Broker-specific extras the framework does not yet model.
        Translators MAY read this; nothing in core should depend on
        any specific key.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    broker_code: str
    account_id: str
    account_hash: str | None = None
    base_currency: Currency | None = None
    subaccount_id: str | None = None
    entitlements: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


def from_legacy_dict(value: Any) -> AccountContext:
    """Wrap a raw auth-token / dict into an ``AccountContext``.

    The promoted dispatcher used to pass ``{broker_code, account_id}``
    dicts. Older translators or call paths that have not been updated
    feed through this shim — it returns the object untouched if it is
    already an ``AccountContext``, or coerces a dict.
    """
    if isinstance(value, AccountContext):
        return value
    if isinstance(value, dict):
        # Filter to only the known fields; promote `auth_token` to
        # account_id when account_id is missing.
        payload = dict(value)
        if "account_id" not in payload and "auth_token" in payload:
            payload["account_id"] = payload.pop("auth_token")
        # Drop unknown keys into `extra` so extra="forbid" does not bite.
        known = {
            "broker_code",
            "account_id",
            "account_hash",
            "base_currency",
            "subaccount_id",
            "entitlements",
            "extra",
        }
        extras = {k: payload.pop(k) for k in list(payload) if k not in known}
        if extras:
            payload.setdefault("extra", {}).update(extras)
        return AccountContext(**payload)
    raise TypeError(
        f"cannot coerce {type(value).__name__} into AccountContext"
    )


__all__ = ["AccountContext", "from_legacy_dict"]
