"""Phase 6 — pre-trade validator for chart-originated order intents.

Enforces, per HANDOFF Phase 6 §11:

* Idempotency: dedupe by ``idempotency_token`` (5-minute window).
* Max-size guard: ``qty <= max_order_size``.
* Max-notional guard: ``qty * price <= max_notional`` (currency-aware).
* Kill-switch state: blocks if ON.
* Account context: validates ``account_id`` belongs to user.
* Live-mode gate: blocks live intents unless
  ``chart_safety_settings.live_mode_enabled = true``.

Returns a structured ``ValidationResult`` — never raises; the API
layer maps a non-ok result to a 4xx envelope with the Reason code.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from decimal import Decimal
from time import time as _time
from typing import Iterable, Literal

from services.charts.safety_defaults import SafetyDefaults

# 5-minute idempotency window — any token re-used within this window
# is treated as a duplicate of the original intent.
IDEMPOTENCY_WINDOW_SECONDS = 5 * 60

ValidationCode = Literal[
    "ok",
    "duplicate_intent",
    "size_exceeded",
    "notional_exceeded",
    "kill_switch_on",
    "wrong_account",
    "live_mode_disabled",
    "missing_token",
    "missing_qty",
    "missing_price",
    "no_notional_cap_configured",
]


@dataclass
class IntentRequest:
    """Inbound chart-originated order intent."""

    idempotency_token: str
    user_id: str
    account_id: str
    intent_kind: Literal["place", "modify", "cancel"]
    symbol: str
    qty: Decimal | None
    price: Decimal | None
    is_live: bool


@dataclass
class ValidationResult:
    code: ValidationCode
    message: str = ""
    details: dict[str, str | int | float | bool] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.code == "ok"


@dataclass
class _SeenToken:
    seen_at: float
    user_id: str


class PreTradeValidator:
    """Stateful idempotency cache + stateless guard checks.

    Threadsafe: the idempotency cache is protected by a single lock.
    Production deployments use a single instance per process; the
    Flask-SocketIO ``-w 1`` constraint means the cache stays
    in-process.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, _SeenToken] = {}
        self._lock = threading.Lock()

    def validate(
        self,
        intent: IntentRequest,
        defaults: SafetyDefaults,
        user_accounts: Iterable[str],
    ) -> ValidationResult:
        # 1. Required fields.
        if not intent.idempotency_token:
            return ValidationResult("missing_token", "idempotency_token is required")
        if intent.intent_kind in {"place", "modify"} and intent.qty is None:
            return ValidationResult("missing_qty", "qty is required")
        # `price` may be None for MARKET orders — only require for LIMIT.
        # Phase 6 doesn't carry order_type yet; the API layer adds it.

        # 2. Account context.
        if intent.account_id not in set(user_accounts):
            return ValidationResult(
                "wrong_account",
                f"account_id {intent.account_id!r} not in user's account list",
            )

        # 3. Kill-switch.
        if defaults.kill_switch:
            return ValidationResult(
                "kill_switch_on",
                "kill switch is ON; chart-originated intents are blocked",
            )

        # 4. Live-mode gate.
        if intent.is_live and not defaults.live_mode_enabled:
            return ValidationResult(
                "live_mode_disabled",
                "live mode is disabled; toggle the 'I understand' gate to enable",
            )

        # 5. Max size.
        if intent.qty is not None and intent.qty > defaults.max_order_size:
            return ValidationResult(
                "size_exceeded",
                f"qty {intent.qty} > max_order_size {defaults.max_order_size}",
                details={"qty": float(intent.qty), "max": defaults.max_order_size},
            )

        # 6. Max notional.
        if intent.qty is not None and intent.price is not None:
            if defaults.max_notional is None:
                return ValidationResult(
                    "no_notional_cap_configured",
                    f"no notional cap configured for currency {defaults.currency!r}",
                )
            notional = intent.qty * intent.price
            if notional > defaults.max_notional:
                return ValidationResult(
                    "notional_exceeded",
                    f"notional {notional} > cap {defaults.max_notional} {defaults.currency}",
                    details={
                        "notional": float(notional),
                        "cap": float(defaults.max_notional),
                        "currency": defaults.currency,
                    },
                )

        # 7. Idempotency (after all other guards — denies for size/etc
        # don't burn a token).
        if not self._claim_token(intent.idempotency_token, intent.user_id):
            return ValidationResult(
                "duplicate_intent",
                "idempotency_token already used in the last 5 minutes",
            )

        return ValidationResult("ok")

    def _claim_token(self, token: str, user_id: str) -> bool:
        now = _time()
        with self._lock:
            self._gc(now)
            existing = self._tokens.get(token)
            if existing is not None and now - existing.seen_at <= IDEMPOTENCY_WINDOW_SECONDS:
                return False
            self._tokens[token] = _SeenToken(seen_at=now, user_id=user_id)
            return True

    def _gc(self, now: float) -> None:
        cutoff = now - IDEMPOTENCY_WINDOW_SECONDS
        stale = [k for k, v in self._tokens.items() if v.seen_at < cutoff]
        for k in stale:
            self._tokens.pop(k, None)

    def reset_for_tests(self) -> None:
        with self._lock:
            self._tokens.clear()


# Module-level singleton; tests reset via `validator_for_tests().reset_for_tests()`.
_validator = PreTradeValidator()


def validator_for_tests() -> PreTradeValidator:
    return _validator


def validate(
    intent: IntentRequest,
    defaults: SafetyDefaults,
    user_accounts: Iterable[str],
) -> ValidationResult:
    return _validator.validate(intent, defaults, user_accounts)


__all__ = [
    "IDEMPOTENCY_WINDOW_SECONDS",
    "IntentRequest",
    "PreTradeValidator",
    "ValidationCode",
    "ValidationResult",
    "validate",
    "validator_for_tests",
]
