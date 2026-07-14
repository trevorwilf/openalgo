"""Phase 1 — bowaka_v2_config.yaml structural + default checks."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


_CFG_PATH = (
    Path(__file__).resolve().parents[2]
    / "strategies" / "scripts" / "bowaka_v2_config.yaml"
)


def _load_cfg() -> dict:
    return yaml.safe_load(_CFG_PATH.read_text(encoding="utf-8"))


def test_v2_config_loads_yaml() -> None:
    cfg = _load_cfg()
    assert isinstance(cfg, dict)
    # Every top-level section from handoff §6.
    for section in (
        "strategy", "paths", "data", "session", "universe",
        "historical_features", "scanner", "signals", "score",
        "execution", "sizing", "risk", "exits",
        "protected_position", "logging", "research",
        "liquidity_monitor",
    ):
        assert section in cfg, f"missing top-level section {section!r}"


def test_v2_config_defaults_sip_after_cutover() -> None:
    cfg = _load_cfg()
    # SIP cutover 2026-06-04: feed flipped to the consolidated tape and
    # the research-only escape hatch re-armed off.
    assert cfg["data"]["feed"] == "sip"
    assert cfg["data"]["allow_non_sip_for_research_only"] is False
    assert cfg["data"]["live_requires_sip"] is True


def test_v2_config_compounding_block_defaults() -> None:
    cfg = _load_cfg()
    comp = cfg["sizing"]["compounding"]
    assert comp["enabled"] is True
    assert comp["base_dollars"] is None
    assert comp["floor_fraction"] == pytest.approx(0.50)
    assert comp["cap_multiple"] == pytest.approx(4.0)


def test_v2_config_environment_is_paper() -> None:
    cfg = _load_cfg()
    assert cfg["strategy"]["environment"] == "paper"
    assert cfg["strategy"]["mode"] == "forming_daily_bar_monitor"


def test_v2_config_signals_have_min_thresholds() -> None:
    cfg = _load_cfg()
    s = cfg["signals"]
    # Handoff §6 priors are RVOL≥1.50, range≥1.25, close_loc≥0.60.
    # Operator may relax for IEX partial-tape testing (see YAML
    # comments). We assert the gates are configured and within a
    # sensible band — typos like 15.0 or 0.01 still fail.
    assert 0.3 <= s["rvol_so_far_min"] <= 2.0
    assert 0.3 <= s["range_expansion_so_far_min"] <= 2.0
    assert 0.3 <= s["close_location_so_far_min"] <= 1.0


def test_v2_config_score_bounded_default() -> None:
    cfg = _load_cfg()
    assert cfg["score"]["bounded"] is True
    assert cfg["score"]["rvol_score_cap"] == pytest.approx(5.0)
    assert cfg["score"]["range_score_cap"] == pytest.approx(2.5)


def test_v2_config_risk_paper_safe_with_shadow_block() -> None:
    cfg = _load_cfg()
    assert cfg["risk"]["daily_loss_pct"] == pytest.approx(0.03)
    # Shadow block exists.
    assert "shadow" in cfg["risk"]
    assert cfg["risk"]["shadow"]["daily_loss_pct"] == pytest.approx(0.01)


def test_v2_config_logging_observability_parity_toggles_on() -> None:
    cfg = _load_cfg()
    L = cfg["logging"]
    # Fix Phase 7 removed the dead logging.emit_candidate_events key
    # (nothing ever read it — candidate events are the scanner's
    # unconditional output stream).
    for k in (
        "emit_entry_decisions",
        "emit_rejected_candidates", "emit_feature_snapshots",
        "log_order_execution_quality", "log_protection_state",
        "log_shadow_risk_controls", "log_counterfactual_entries",
        "log_counterfactual_exits", "persist_config_snapshot",
    ):
        assert L.get(k) is True, f"logging.{k} should default true in paper"


def test_v2_config_protected_position_blocks_in_v2() -> None:
    cfg = _load_cfg()
    pp = cfg["protected_position"]
    assert pp["enabled"] is True
    assert pp["block_entries_on_violation"] is True  # §10.2
    assert pp["flatten_if_unprotected"] is True


def test_v2_config_research_minute_bars_enabled() -> None:
    cfg = _load_cfg()
    r = cfg["research"]["candidate_minute_bars"]
    assert r["enabled"] is True
    assert r["layout"] == "by_session"
    assert "ts" in r["columns"]
    assert "vwap" in r["columns"]
