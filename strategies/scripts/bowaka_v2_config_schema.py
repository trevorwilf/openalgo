#!/usr/bin/env python3
"""Bowaka v2 — strict config-key validation.

Walks a loaded ``bowaka_v2_config.yaml`` tree and raises
:class:`ConfigError` (exit 5 at the callers) listing every key that is
not in the known-key schema below. This permanently prevents the
dead-key class: a misspelled or unwired key fails startup loudly
instead of being silently ignored for weeks.

Rules:
- Unknown keys are errors. Known-but-null keys are fine.
- ``BOWAKA_CONFIG_ALLOW_UNKNOWN=1`` in the environment downgrades the
  raise to a WARNING (operator escape hatch for config experiments).
- The schema must be extended in the SAME commit that wires a new key.

Used by both the strategy (``bowaka_v2_strategy.main``) and the
scanner (``bowaka_intraday_scanner.main``) — they share the yaml.
"""
from __future__ import annotations

import logging
import os
from typing import Any

LOG = logging.getLogger("bowaka_v2_config_schema")


class ConfigError(RuntimeError):
    pass


# A schema node is one of:
#   LEAF                 — any scalar/list value is fine
#   dict                 — nested mapping; keys are validated
#   ("list_of", schema)  — list whose dict elements validate per schema
LEAF = "leaf"

_ADV_TIER_SCHEMA = {
    "max_adv_dollars": LEAF,
    "max_position_as_adv_frac": LEAF,
    "reject_if_below": LEAF,
}

KNOWN_KEYS: dict[str, Any] = {
    "strategy": {
        "name": LEAF,
        "strategy_id": LEAF,
        "mode": LEAF,
        "environment": LEAF,
        "analysis_epoch": LEAF,
    },
    "paths": {
        "universe_snapshot_path": LEAF,
        "daily_feature_cache_path": LEAF,
        "volume_curve_path": LEAF,
        "candidate_events_path": LEAF,
        "entry_decisions_path": LEAF,
        "state_path": LEAF,
        "trade_ledger_path": LEAF,
        "daily_summary_path": LEAF,
        "kill_switch_dir": LEAF,
    },
    "data": {
        "provider": LEAF,
        "feed": LEAF,
        "allow_non_sip_for_research_only": LEAF,
        "live_requires_sip": LEAF,
        "daily_timeframe": LEAF,
        "intraday_timeframe": LEAF,
        "timezone": LEAF,
        "min_history_trading_days": LEAF,
        "require_adjusted_daily_bars": LEAF,
        "require_split_adjustment": LEAF,
        "fail_on_missing_baseline": LEAF,
        "max_bar_age_seconds": LEAF,
    },
    "session": {
        "timezone": LEAF,
        "start": LEAF,
        "end": LEAF,
        "scanner_start": LEAF,
        "scanner_end": LEAF,
        "loop_interval_seconds": LEAF,
    },
    "universe": {
        "allowed_exchanges": LEAF,
        "exclude_otc": LEAF,
        "exclude_etf": LEAF,
        "exclude_leveraged_etp": LEAF,
        "exclude_inverse_etp": LEAF,
        "exclude_etn": LEAF,
        "exclude_warrants": LEAF,
        "exclude_units": LEAF,
        "exclude_rights": LEAF,
        "exclude_preferred": LEAF,
        "ticker_blocklist": LEAF,
        "price_min": LEAF,
        "price_max": LEAF,
        "avg_dollar_volume_min": LEAF,
        "avg_dollar_volume_max": LEAF,
        "market_cap_max": LEAF,
        "float_shares_max": LEAF,
        "shares_outstanding_max": LEAF,
    },
    "historical_features": {
        "lookback_days": LEAF,
        "atr_days": LEAF,
        "ema_days": LEAF,
        "ema_slope_lookback": LEAF,
        "volume_curve": {
            "mode": LEAF,
            "bucket_edges": LEAF,
            "fallback_opening_15m_share": LEAF,
            "min_days_for_symbol_curve": LEAF,
        },
    },
    "scanner": {
        "enabled": LEAF,
        "debug_gate_dump": LEAF,
        "scan_interval_seconds": LEAF,
        "fetch_concurrency": LEAF,
        "bar_source": LEAF,
        "alpaca_chunk_size": LEAF,
        "alpaca_fetch_concurrency": LEAF,
        "incremental_bars_enabled": LEAF,
        "incremental_overlap_minutes": LEAF,
        "full_reconcile_interval_minutes": LEAF,
        "max_candidates_per_scan": LEAF,
        "max_entries_per_scan": LEAF,
        "signal_expiry_seconds": LEAF,
        "same_symbol_entries_per_day": LEAF,
        "symbol_cooldown_minutes": LEAF,
        "require_fresh_intraday_bar": LEAF,
    },
    "signals": {
        "rvol_so_far_min": LEAF,
        "projected_full_day_rvol_min": LEAF,
        "prior_atr_pct_min": LEAF,
        "range_expansion_so_far_min": LEAF,
        "close_location_so_far_min": LEAF,
        "ema_distance_min": LEAF,
        "ema_slope_min": LEAF,
        "price_min": LEAF,
        "price_max": LEAF,
        "avg_dollar_volume_min": LEAF,
        "avg_dollar_volume_max": LEAF,
        "rvol_so_far_max": LEAF,
        "projected_full_day_rvol_max": LEAF,
        "range_expansion_so_far_max": LEAF,
        "gap_pct_max": LEAF,
        "current_return_pct_max": LEAF,
    },
    "score": {
        "bounded": LEAF,
        "rvol_score_cap": LEAF,
        "range_score_cap": LEAF,
        "ema_distance_score_cap": LEAF,
        "ema_slope_score_cap": LEAF,
        "close_location_weight": LEAF,
        "gap_penalty_above": LEAF,
    },
    "execution": {
        "parent_order_style": LEAF,
        "marketable_limit_slippage_pct": LEAF,
        "marketable_limit_timeout_seconds": LEAF,
        "bracket_pricing_mode": LEAF,
        "default_venue_code": LEAF,
        "pending_fill_timeout_seconds": LEAF,
        "quote_gate": {
            "enabled": LEAF,
            "max_spread_pct": LEAF,
            "max_quote_age_seconds": LEAF,
            "require_bid_ask_positive": LEAF,
        },
        "price_chase_gate": {
            "enabled": LEAF,
            "max_pct_above_signal_price": LEAF,
            "min_pct_below_signal_price": LEAF,
        },
        "halt_gate": {
            "enabled": LEAF,
            "block_on_halt_or_pending_review": LEAF,
            "block_on_recent_luld_pause": LEAF,
        },
    },
    "sizing": {
        "sizing_mode": LEAF,
        "bankroll_fixed_dollars": LEAF,
        "max_concurrent_positions": LEAF,
        "equal_slice_bankroll_fraction": LEAF,
        "target_risk_dollars": LEAF,
        "min_order_notional": LEAF,
        "max_per_trade_dollars": LEAF,
        "compounding": {
            "enabled": LEAF,
            "base_dollars": LEAF,
            "floor_fraction": LEAF,
            "cap_multiple": LEAF,
        },
    },
    "reconcile": {
        "halt_on_orphans": LEAF,
    },
    "risk": {
        "daily_loss_pct": LEAF,
        "strategy_slice_loss_pct": LEAF,
        "max_gross_exposure_pct": LEAF,
        "max_total_entries_per_day": LEAF,
        "max_lots_per_symbol": LEAF,
        "max_stopouts_per_day": LEAF,
        # Legacy persistent latch. New deployments should leave this
        # null and use stopout_breaker below, which has an explicit
        # session cooldown and probation recovery path.
        "stop_trading_after_consecutive_stopouts": LEAF,
        "stopout_breaker": {
            "enabled": LEAF,
            "threshold": LEAF,
            "cooldown_sessions": LEAF,
            "probation_entries": LEAF,
            "probation_size_multiplier": LEAF,
        },
        "max_position_as_adv_frac": LEAF,
        "adv_tier_caps": ("list_of", _ADV_TIER_SCHEMA),
        "shadow": {
            "daily_loss_pct": LEAF,
            "max_gross_exposure_pct": LEAF,
            "max_total_entries_per_day": LEAF,
            "max_unrealized_loss_pct": LEAF,
            "adv_tier_caps": ("list_of", _ADV_TIER_SCHEMA),
        },
    },
    "exits": {
        "stop_pct": LEAF,
        "target_pct": LEAF,
        "max_hold_days": LEAF,
        "oco_time_in_force": LEAF,
        "time_stop": {
            "enabled": LEAF,
            "exit_time": LEAF,
        },
        "signal_fade": {
            "enabled": LEAF,
            "active": LEAF,
            "initial_mode": LEAF,
            "eval_time": LEAF,
            "telemetry_time": LEAF,
            "score_thresholds": {
                "soft": LEAF,
                "hard": LEAF,
                "critical": LEAF,
            },
            "exit_on": LEAF,
            "order_style": LEAF,
            "marketable_limit_offset_pct": LEAF,
        },
    },
    "protected_position": {
        "enabled": LEAF,
        "max_unprotected_seconds": LEAF,
        "max_oco_attach_attempts": LEAF,
        "fallback_stop_enabled": LEAF,
        "flatten_if_unprotected": LEAF,
        "block_entries_on_violation": LEAF,
    },
    "logging": {
        "level": LEAF,
        "emit_entry_decisions": LEAF,
        "emit_rejected_candidates": LEAF,
        "emit_feature_snapshots": LEAF,
        "log_order_execution_quality": LEAF,
        "log_protection_state": LEAF,
        "log_shadow_risk_controls": LEAF,
        "log_counterfactual_entries": LEAF,
        "log_counterfactual_exits": LEAF,
        "persist_config_snapshot": LEAF,
    },
    "research": {
        "candidate_minute_bars": {
            "enabled": LEAF,
            "output_dir": LEAF,
            "layout": LEAF,
            "window": {
                "premarket_start": LEAF,
                "session_end": LEAF,
            },
            "columns": LEAF,
            "on_missing": LEAF,
        },
    },
    "liquidity_monitor": {
        "enabled": LEAF,
        "tick_interval_seconds": LEAF,
        "stale_quote_seconds": LEAF,
        "severe_stale_quote_seconds": LEAF,
        "spread_warning_pct": LEAF,
        "spread_severe_pct": LEAF,
        "consecutive_warning_ticks": LEAF,
        "action_on_severe_if_profitable": LEAF,
    },
}


def _walk(
    node: Any, schema: Any, path: str, problems: list[str],
) -> None:
    if schema == LEAF:
        return
    if isinstance(schema, tuple) and schema[0] == "list_of":
        if isinstance(node, list):
            for i, item in enumerate(node):
                if isinstance(item, dict):
                    _walk(item, schema[1], f"{path}[{i}]", problems)
        return
    if not isinstance(node, dict):
        # Known key holding null / a scalar where a mapping could be —
        # "known-but-null keys are fine".
        return
    for key, value in node.items():
        child_path = f"{path}.{key}" if path else str(key)
        if not isinstance(schema, dict) or key not in schema:
            problems.append(child_path)
            continue
        _walk(value, schema[key], child_path, problems)


def find_unknown_keys(cfg: dict) -> list[str]:
    """Return the dotted paths of every unknown key in ``cfg``."""
    problems: list[str] = []
    _walk(cfg or {}, KNOWN_KEYS, "", problems)
    return problems


def validate_config(cfg: dict) -> None:
    """Raise :class:`ConfigError` listing unknown keys, unless the
    ``BOWAKA_CONFIG_ALLOW_UNKNOWN=1`` escape hatch downgrades the
    failure to a WARNING."""
    unknown = find_unknown_keys(cfg)
    if not unknown:
        return
    msg = (
        "unknown config key(s) — wire them or remove them "
        "(set BOWAKA_CONFIG_ALLOW_UNKNOWN=1 to bypass): "
        + ", ".join(sorted(unknown))
    )
    if os.environ.get("BOWAKA_CONFIG_ALLOW_UNKNOWN") == "1":
        LOG.warning("%s", msg)
        return
    raise ConfigError(msg)


__all__ = [
    "ConfigError",
    "KNOWN_KEYS",
    "LEAF",
    "find_unknown_keys",
    "validate_config",
]
