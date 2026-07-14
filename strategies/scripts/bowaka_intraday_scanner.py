#!/usr/bin/env python3
"""Bowaka v2 — intraday scanner.

Standalone long-running process that continuously monitors the
filtered universe during the regular session, evaluates the
FORMING daily/session bar at every scan interval, and emits
time-stamped candidate events to a JSONL stream the strategy
consumes. The scanner does NOT place orders.

CLI:
  python bowaka_intraday_scanner.py --config bowaka_v2_config.yaml
  python bowaka_intraday_scanner.py --config bowaka_v2_config.yaml --replay-from <fixture> --dry-run

The --replay-from fixture is a JSONL with one record per scan
tick, containing the minute bars to feed at that timestamp. Used
by deterministic tests + the Phase 5 backtester.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

import bowaka_v2_features as features  # noqa: E402
import bowaka_v2_paths as paths  # noqa: E402
import bowaka_v2_schemas as schemas  # noqa: E402
import bowaka_v2_volume_curve as vcurve  # noqa: E402


LOG = logging.getLogger("bowaka_intraday_scanner")


class ConfigError(RuntimeError):
    """Raised on a fatal config validation failure at startup. The
    scanner exits with code 5 so the operator notices."""


# ---------------------------------------------------------------- startup gate


def validate_startup_config(cfg: dict) -> None:
    """Per handoff §5.6 + P0.3: refuse to start if data.feed is not
    SIP unless ``allow_non_sip_for_research_only: true`` is set. In
    paper/test mode an IEX feed emits a loud WARNING but proceeds."""
    data = cfg.get("data") or {}
    feed = data.get("feed", "sip")
    research_ok = bool(data.get("allow_non_sip_for_research_only"))
    if feed != "sip" and not research_ok:
        raise ConfigError(
            f"Bowaka v2 scanner refuses to start: feed={feed!r} but "
            "data.allow_non_sip_for_research_only is false. Either "
            "switch to SIP or flip the research flag."
        )
    if feed != "sip":
        LOG.warning(
            "running on %s partial-tape; RVOL and range_expansion "
            "will be distorted. SIP is the validation feed.",
            feed,
        )


# ---------------------------------------------------------------- loaders


def load_universe_snapshot(cfg: dict) -> dict:
    p = _resolve(cfg, "universe_snapshot_path",
                  paths.UNIVERSE_SNAPSHOT_PATH)
    if not p.exists():
        raise ConfigError(
            f"universe_snapshot.json not found at {p}; run "
            "bowaka_universe_builder.py first"
        )
    return json.loads(p.read_text(encoding="utf-8"))


def load_daily_feature_cache(cfg: dict) -> pd.DataFrame:
    p = _resolve(cfg, "daily_feature_cache_path",
                  paths.DAILY_FEATURE_CACHE_PATH)
    if not p.exists():
        raise ConfigError(
            f"daily_feature_cache.parquet not found at {p}; run "
            "bowaka_universe_builder.py first"
        )
    try:
        return pd.read_parquet(p)
    except Exception:
        # Fall back to gzipped jsonl path if parquet missing.
        alt = p.with_suffix(".jsonl.gz")
        if alt.exists():
            return pd.read_json(alt, lines=True, compression="gzip")
        raise


def load_volume_curve(cfg: dict) -> pd.DataFrame | None:
    p = _resolve(cfg, "volume_curve_path", paths.VOLUME_CURVE_PATH)
    if not p.exists():
        LOG.warning(
            "volume_curve.parquet not found at %s; using fallback "
            "opening-15m share = %s",
            p,
            ((cfg.get("historical_features") or {})
             .get("volume_curve") or {})
                .get("fallback_opening_15m_share", 0.08),
        )
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


# ---------------------------------------------------------------- state


def _empty_state(today_iso: str) -> dict:
    return {
        "session_date": today_iso,
        "entered_symbols_today": [],
        "rejected_symbols_today": {},
        "cooldowns": {},
        "in_play_pool": {},
        "scanner_last_run_ts": None,
    }


def load_or_init_scanner_state(today_iso: str) -> dict:
    p = paths.SCANNER_STATE_PATH
    if not p.exists():
        return _empty_state(today_iso)
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return _empty_state(today_iso)
    if s.get("session_date") != today_iso:
        # New session — reset per-day counters.
        s = _empty_state(today_iso)
    return s


def save_scanner_state(state: dict) -> None:
    p = paths.SCANNER_STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, default=str, indent=2),
                    encoding="utf-8")
    os.replace(tmp, p)


def hydrate_entered_symbols_from_decisions(
    state: dict, today_iso: str,
) -> None:
    """Phase 3.5 dedupe: read strategy-side entry_decisions.jsonl
    for today's accepted entries; mark each symbol in
    ``entered_symbols_today``."""
    p = paths.ENTRY_DECISIONS_PATH
    if not p.exists():
        return
    entered = set(state.get("entered_symbols_today") or [])
    try:
        for raw in p.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if ev.get("session_date") != today_iso:
                continue
            if ev.get("decision") != "accepted":
                continue
            sym = ev.get("symbol")
            if sym:
                entered.add(sym)
    except OSError:
        pass
    state["entered_symbols_today"] = sorted(entered)


# ---------------------------------------------------------------- candidate emission


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _session_date_et(t: datetime) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(
        timezone(timedelta(hours=-4)),  # ET fallback for compute only
    ).date().isoformat() if False else pd.Timestamp(t).tz_convert(
        "America/New_York"
    ).date().isoformat()


def build_candidate_event(
    *,
    symbol: str,
    universe_meta: dict,
    cfg: dict,
    universe_hash: str,
    config_hash_v: str,
    session_bar: dict,
    prior_baselines: dict,
    forming_feats: dict,
    volume_curve_fraction: float,
    gate_results: dict[str, bool],
    candidate_rank: int,
    scan_ts: datetime,
    signal_strength: float,
) -> dict:
    """Materialize the schema-v3 candidate_signal event from the
    parts the scanner has computed."""
    scan_iso = _iso(scan_ts)
    session_date = _session_date_et(scan_ts)
    expiry_s = int((cfg.get("scanner") or {}).get("signal_expiry_seconds", 600))
    expiry = _iso(scan_ts + timedelta(seconds=expiry_s))

    return {
        "schema_version": schemas.CANDIDATE_EVENT_SCHEMA_VERSION,
        "strategy": "bowaka_v2",
        "event_type": "candidate_signal",
        "event_id": schemas.make_event_id(
            "bowaka_v2", session_date, symbol, scan_iso,
        ),
        "generated_at": _iso(_now_utc()),
        "session_date": session_date,
        "scan_timestamp": scan_iso,
        "provider": (cfg.get("data") or {}).get("provider", "alpaca"),
        "data_feed": (cfg.get("data") or {}).get("feed", "iex"),
        "bar_interval": (cfg.get("data") or {}).get("intraday_timeframe", "1m"),
        "config_hash": config_hash_v,
        "universe_hash": universe_hash,
        "symbol": symbol,
        "exchange": universe_meta.get("exchange"),
        "venue_code": universe_meta.get("venue_code") or "XNAS",
        "instrument_class": universe_meta.get("instrument_class"),
        "eligible_for_bowaka_equity_bucket":
            universe_meta.get("eligible_for_bowaka_equity_bucket", True),
        "prior_daily_baselines": {
            "prior_close":           prior_baselines.get("prior_close"),
            "avg_volume_20d":        prior_baselines.get("avg_volume_20d"),
            "avg_dollar_volume_20d": prior_baselines.get("avg_dollar_volume_20d"),
            "prior_atr_14d":         prior_baselines.get("prior_atr_14d"),
            "prior_atr_pct":         prior_baselines.get("prior_atr_pct"),
            "ema_10_prior":          prior_baselines.get("ema_10_prior"),
            "ema_10_lag_3":          prior_baselines.get("ema_10_lag_3"),
            "ema_slope_prior":       prior_baselines.get("ema_slope_prior"),
        },
        "forming_session_bar": session_bar,
        "intraday_volume_context": {
            "volume_curve_fraction": volume_curve_fraction,
            "expected_volume_until_scan": forming_feats.get(
                "expected_volume_until_scan",
            ),
            "rvol_so_far": forming_feats.get("rvol_so_far"),
            "projected_full_day_rvol": forming_feats.get(
                "projected_full_day_rvol",
            ),
        },
        "features": {
            "gap_pct": forming_feats.get("gap_pct"),
            "current_return_pct": forming_feats.get("current_return_pct"),
            "range_expansion_so_far": forming_feats.get(
                "range_expansion_so_far",
            ),
            "close_location_so_far": forming_feats.get(
                "close_location_so_far",
            ),
            "ema_distance": forming_feats.get("ema_distance"),
            "ema_slope": prior_baselines.get("ema_slope_prior"),
            "signal_strength": signal_strength,
        },
        "gate_results": gate_results,
        "candidate_rank": candidate_rank,
        "signal_expiry_timestamp": expiry,
    }


def append_candidate_event(ev: dict, out_path: Path | None = None) -> None:
    """Atomic append (one line, flush). Skips silently when schema
    validation fails — we never want a malformed line to crash the
    scanner mid-loop."""
    ok, problems = schemas.validate_candidate_event(ev)
    if not ok:
        LOG.warning(
            "candidate event failed schema validation; dropping: %s",
            problems,
        )
        return
    p = out_path or paths.CANDIDATE_EVENTS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, default=str) + "\n")
        f.flush()


def append_heartbeat(payload: dict, out_path: Path | None = None) -> None:
    p = out_path or paths.SCANNER_HEARTBEAT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")
        f.flush()


# ---------------------------------------------------------------- one scan


def evaluate_one_scan(
    *,
    cfg: dict,
    universe_snapshot: dict,
    daily_cache: pd.DataFrame,
    volume_curve: pd.DataFrame | None,
    state: dict,
    scan_ts: datetime,
    bars_supplier: Callable[[str, datetime], pd.DataFrame | None],
    candidate_events_path: Path | None = None,
    heartbeat_path: Path | None = None,
) -> list[dict]:
    """Pure-function scan: evaluate every universe symbol at
    ``scan_ts``, emit candidate events that pass all v2 gates, and
    return the list of emitted events. Idempotent against test
    fixtures — same inputs yield same outputs.

    ``bars_supplier`` is the only injection point that talks to
    Alpaca in production. In tests it's a fixture-fed lambda.
    """
    scanner_cfg = cfg.get("scanner") or {}
    signals_cfg = cfg.get("signals") or {}
    score_cfg = cfg.get("score") or {}
    hf_cfg = (cfg.get("historical_features") or {})
    bucket_edges = list(
        (hf_cfg.get("volume_curve") or {}).get(
            "bucket_edges",
            [250000, 500000, 1000000, 5000000, 20000000],
        )
    )
    fallback_share = float(
        (hf_cfg.get("volume_curve") or {}).get(
            "fallback_opening_15m_share", 0.08,
        )
    )

    entered = set(state.get("entered_symbols_today") or [])
    max_candidates = int(
        scanner_cfg.get("max_candidates_per_scan", 25)
    )

    universe_meta_by_sym = {
        s["symbol"]: s for s in universe_snapshot.get("symbols", [])
    }
    cache_by_sym = {}
    if daily_cache is not None and not daily_cache.empty:
        for _, row in daily_cache.iterrows():
            cache_by_sym[row["symbol"]] = row.to_dict()

    universe_hash = universe_snapshot.get("universe_hash", "sha256:unknown")
    config_hash_v = "sha256:" + hashlib.sha256(
        json.dumps(cfg, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]

    # Diagnostic: when scanner.debug_gate_dump is true, write one
    # per-symbol JSONL row each scan with feature values + gate-by-
    # gate pass/fail. Lets the operator see WHY symbols miss without
    # waiting for a candidate to actually emit.
    debug_dump = bool(scanner_cfg.get("debug_gate_dump", False))
    dump_path = paths.SCANNER_GATE_DUMP_PATH if debug_dump else None
    if dump_path is not None:
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_fh = open(dump_path, "a", encoding="utf-8")
    else:
        dump_fh = None

    passing: list[tuple[float, dict]] = []
    for symbol, meta in universe_meta_by_sym.items():
        if symbol in entered:
            continue
        baselines = cache_by_sym.get(symbol)
        if not baselines:
            if dump_fh is not None:
                dump_fh.write(json.dumps({
                    "ts": _iso(_now_utc()),
                    "scan_timestamp": _iso(scan_ts),
                    "symbol": symbol,
                    "skipped": "no_baselines",
                }, default=str) + "\n")
            continue
        adv = baselines.get("avg_dollar_volume_20d")
        prior_atr_pct = baselines.get("prior_atr_pct")
        ema_slope = baselines.get("ema_slope_prior")
        bucket = vcurve.adv_bucket(adv, bucket_edges)
        # Volume curve fraction for the scan time.
        vcf = features.compute_volume_curve_fraction(
            volume_curve, scan_ts, bucket,
            fallback_opening_15m_share=fallback_share,
        )

        # Fetch / replay this symbol's minute bars through scan_ts.
        try:
            bars = bars_supplier(symbol, scan_ts)
        except Exception as e:
            LOG.debug("bars fetch failed for %s: %s", symbol, e)
            if dump_fh is not None:
                dump_fh.write(json.dumps({
                    "ts": _iso(_now_utc()),
                    "scan_timestamp": _iso(scan_ts),
                    "symbol": symbol,
                    "skipped": "bars_fetch_failed",
                    "error": str(e)[:200],
                }, default=str) + "\n")
            continue
        if bars is None or len(bars) == 0:
            if dump_fh is not None:
                dump_fh.write(json.dumps({
                    "ts": _iso(_now_utc()),
                    "scan_timestamp": _iso(scan_ts),
                    "symbol": symbol,
                    "skipped": "no_bars",
                }, default=str) + "\n")
            continue
        sess = features.aggregate_forming_session_bar(bars)
        feats = features.compute_forming_session_features(
            sess, baselines, vcf,
        )
        ok, gates = features.apply_v2_gates(
            feats, signals_cfg,
            price=sess.get("last_price"),
            avg_dollar_volume_20d=adv,
            prior_atr_pct=prior_atr_pct,
            ema_slope_prior=ema_slope,
            instrument_class=meta.get("instrument_class"),
        )
        if dump_fh is not None:
            failing = sorted(k for k, v in (gates or {}).items() if not v)
            dump_fh.write(json.dumps({
                "ts": _iso(_now_utc()),
                "scan_timestamp": _iso(scan_ts),
                "symbol": symbol,
                "ok": bool(ok),
                "failing_gates": failing,
                "gate_results": gates,
                "features": {
                    "rvol_so_far": feats.get("rvol_so_far"),
                    "projected_full_day_rvol": feats.get(
                        "projected_full_day_rvol",
                    ),
                    "range_expansion_so_far": feats.get(
                        "range_expansion_so_far",
                    ),
                    "close_location_so_far": feats.get(
                        "close_location_so_far",
                    ),
                    "ema_distance": feats.get("ema_distance"),
                    "gap_pct": feats.get("gap_pct"),
                    "current_return_pct": feats.get("current_return_pct"),
                },
                "baselines": {
                    "prior_close": baselines.get("prior_close"),
                    "prior_atr_pct": prior_atr_pct,
                    "ema_slope_prior": ema_slope,
                    "avg_dollar_volume_20d": adv,
                },
                "session_bar": {
                    "open": sess.get("session_open"),
                    "high": sess.get("session_high"),
                    "low": sess.get("session_low"),
                    "last": sess.get("last_price"),
                    "volume": sess.get("session_volume"),
                },
                "volume_curve_fraction": vcf,
                "instrument_class": meta.get("instrument_class"),
            }, default=str) + "\n")
        if not ok:
            continue
        score = features.compute_signal_strength(
            feats, score_cfg, ema_slope_prior=ema_slope,
        )
        ev = build_candidate_event(
            symbol=symbol,
            universe_meta=meta,
            cfg=cfg,
            universe_hash=universe_hash,
            config_hash_v=config_hash_v,
            session_bar=sess,
            prior_baselines=baselines,
            forming_feats=feats,
            volume_curve_fraction=vcf,
            gate_results=gates,
            candidate_rank=0,  # filled after sort
            scan_ts=scan_ts,
            signal_strength=score,
        )
        passing.append((score, ev))

    # Rank + cap.
    passing.sort(key=lambda x: -x[0])
    emitted: list[dict] = []
    for rank, (_score, ev) in enumerate(passing[:max_candidates], start=1):
        ev["candidate_rank"] = rank
        append_candidate_event(ev, candidate_events_path)
        emitted.append(ev)
        # Track in scanner state's in_play_pool.
        state.setdefault("in_play_pool", {})[ev["symbol"]] = {
            "last_signal_ts": ev["scan_timestamp"],
            "signal_expiry_ts": ev["signal_expiry_timestamp"],
            "last_signal_strength": ev["features"]["signal_strength"],
        }

    state["scanner_last_run_ts"] = _iso(scan_ts)
    # Heartbeat.
    append_heartbeat({
        "ts": _iso(_now_utc()),
        "scan_timestamp": _iso(scan_ts),
        "universe_size": len(universe_meta_by_sym),
        "passed_gates_this_scan": len(passing),
        "emitted_count": len(emitted),
    }, heartbeat_path)
    if dump_fh is not None:
        try:
            dump_fh.flush()
            dump_fh.close()
        except Exception:
            pass
    return emitted


def _resolve(cfg: dict, key: str, default: Path) -> Path:
    p = (cfg.get("paths") or {}).get(key)
    if not p:
        return default
    pp = Path(p)
    if pp.is_absolute():
        return pp
    return paths.REPO_ROOT / pp


# ---------------------------------------------------------------- CLI


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bowaka v2 intraday scanner",
    )
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--replay-from", default=None,
        help="Path to a replay-mode fixture JSONL with one record per "
             "scan tick. Bypasses Alpaca and uses the fixture's bars.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run one scan tick (against the fixture or a synthetic "
             "no-symbol set) and exit. Useful for CI / cron smoke.",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    logging.basicConfig(
        level=getattr(logging, (cfg.get("logging") or {})
                       .get("level", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        validate_startup_config(cfg)
    except ConfigError as e:
        LOG.error("config error: %s", e)
        return 5

    paths.ensure_dirs()
    universe = load_universe_snapshot(cfg)
    daily_cache = load_daily_feature_cache(cfg)
    volume_curve = load_volume_curve(cfg)
    today_iso = pd.Timestamp.now(tz="America/New_York").date().isoformat()
    state = load_or_init_scanner_state(today_iso)
    hydrate_entered_symbols_from_decisions(state, today_iso)
    save_scanner_state(state)

    if args.replay_from:
        return _run_replay(
            cfg, universe, daily_cache, volume_curve, state, args,
        )

    if args.dry_run:
        LOG.info(
            "dry-run: emitting empty scan + heartbeat (no live scan)"
        )
        append_heartbeat({
            "ts": _iso(_now_utc()),
            "scan_timestamp": _iso(_now_utc()),
            "universe_size": len(universe.get("symbols") or []),
            "passed_gates_this_scan": 0,
            "emitted_count": 0,
        })
        save_scanner_state(state)
        return 0

    return _run_live(cfg, universe, daily_cache, volume_curve, state)


def _file_mtime(p: Path) -> float:
    """Return the on-disk mtime of ``p`` (epoch seconds), or 0.0 if
    the file doesn't exist."""
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0
    except OSError:
        return 0.0


def _run_live(
    cfg: dict, universe: dict, daily_cache, volume_curve, state,
) -> int:
    """Long-running live scan loop. Each scan_interval_seconds it
    prefetches OpenAlgo /api/v2/bars for every universe symbol
    concurrently (fetch_concurrency workers), evaluates gates, and
    emits candidate events.

    Hot-reload: each tick checks the mtime of universe_snapshot.json,
    daily_feature_cache.parquet, and volume_curve.parquet. When the
    universe builder writes a fresh snapshot (atomic rename via
    os.replace), the scanner picks up the new files at the next scan
    without a process restart. The prefetch_scan_bars closure
    captures ``universe`` by name, so a rebind here propagates to
    the next prefetch automatically.
    """
    import bowaka_v2_openalgo_client as oa
    import bowaka_v2_alpaca_data as ad
    import signal as _signal
    host, api_key = oa.resolve_host_and_key()
    sess_cfg = cfg.get("session") or {}
    scanner_cfg = cfg.get("scanner") or {}
    interval = int(scanner_cfg.get("scan_interval_seconds", 60))
    # Concurrent minute-bar prefetch fan-out. Each scan tick fetches
    # bars for every universe symbol in parallel so a large universe
    # (cap_to_n_symbols) still completes well within scan_interval.
    fetch_concurrency = max(1, int(scanner_cfg.get("fetch_concurrency", 24)))
    http = oa.make_http_client(
        host, timeout=30.0, max_connections=fetch_concurrency + 8,
    )

    # Bar source: 'openalgo' (default — single-symbol /api/v2/bars via the
    # local single-worker server) or 'alpaca_direct' (one multi-symbol
    # request straight to Alpaca, bypassing the server bottleneck). When
    # alpaca_direct can't resolve creds at startup we downgrade to
    # openalgo so the scanner never fails to start; per-tick errors also
    # fall back to openalgo. The two paths return identical {symbol: df}.
    bar_source = (scanner_cfg.get("bar_source") or "openalgo").strip().lower()
    alpaca_chunk = int(scanner_cfg.get("alpaca_chunk_size", 200))
    alpaca_conc = max(1, int(scanner_cfg.get("alpaca_fetch_concurrency", 4)))
    ad_client = None
    ad_feed = None
    if bar_source == "alpaca_direct":
        try:
            _headers, ad_feed = ad.resolve_alpaca_data_auth()
            ad_client = ad.make_data_client(
                _headers, max_connections=alpaca_conc + 4,
            )
            LOG.info(
                "bar_source=alpaca_direct (feed=%s, chunk=%d, conc=%d) — "
                "minute bars fetched direct from Alpaca",
                ad_feed, alpaca_chunk, alpaca_conc,
            )
        except Exception as e:
            LOG.error(
                "bar_source=alpaca_direct setup failed (%s); falling back "
                "to openalgo", e,
            )
            bar_source = "openalgo"
            ad_client = None

    # Resolved input paths + initial mtimes. Used by the per-tick
    # hot-reload check below.
    uni_path = _resolve(cfg, "universe_snapshot_path",
                          paths.UNIVERSE_SNAPSHOT_PATH)
    dfc_path = _resolve(cfg, "daily_feature_cache_path",
                          paths.DAILY_FEATURE_CACHE_PATH)
    vc_path = _resolve(cfg, "volume_curve_path",
                        paths.VOLUME_CURVE_PATH)
    last_uni_mtime = _file_mtime(uni_path)
    last_dfc_mtime = _file_mtime(dfc_path)
    last_vc_mtime = _file_mtime(vc_path)
    today_et_date = pd.Timestamp.now(tz="America/New_York").date()
    session_start = pd.Timestamp(
        f"{today_et_date} {sess_cfg.get('scanner_start', '09:45')}",
        tz="America/New_York",
    )
    session_end = pd.Timestamp(
        f"{today_et_date} {sess_cfg.get('scanner_end', '15:30')}",
        tz="America/New_York",
    )
    LOG.info(
        "scanner live loop: %d symbols, interval=%ds, window=%s -> %s",
        len(universe.get("symbols") or []),
        interval, session_start, session_end,
    )

    shutdown = {"flag": False}
    def _handler(_signum, _frame):
        LOG.info("scanner shutdown signal received")
        shutdown["flag"] = True
    try:
        _signal.signal(_signal.SIGINT, _handler)
        _signal.signal(_signal.SIGTERM, _handler)
    except (ValueError, OSError):
        pass

    def prefetch_scan_bars(scan_ts) -> dict:
        # Concurrently fetch every universe symbol's minute bars from
        # session_start → scan_ts. Returns {symbol: DataFrame}. Reads
        # ``universe`` by name so a hot-reload rebind is picked up on
        # the next tick.
        scan_ts_utc = pd.Timestamp(scan_ts)
        if scan_ts_utc.tzinfo is None:
            scan_ts_utc = scan_ts_utc.tz_localize("UTC")
        start_dt = session_start.tz_convert("UTC").to_pydatetime()
        end_dt = scan_ts_utc.to_pydatetime()
        syms_meta = universe.get("symbols") or []
        if bar_source == "alpaca_direct" and ad_client is not None:
            try:
                return ad.fetch_bars_multi(
                    ad_client, ad_feed,
                    [s["symbol"] for s in syms_meta],
                    "1m", start_dt, end_dt,
                    chunk_size=alpaca_chunk, concurrency=alpaca_conc,
                )
            except Exception as e:
                LOG.warning(
                    "alpaca_direct prefetch failed (%s); falling back to "
                    "openalgo for this tick", e,
                )
        reqs = [
            {
                "venue_code": s.get("venue_code", "XNAS"),
                "symbol": s["symbol"],
                "interval": "1m",
                "start": start_dt,
                "end": end_dt,
            }
            for s in syms_meta
        ]
        return oa.fetch_bars_concurrent(
            http, api_key, reqs, concurrency=fetch_concurrency,
        )

    try:
        while not shutdown["flag"]:
            now = pd.Timestamp.now(tz="America/New_York")
            if now < session_start:
                LOG.info("waiting for scanner_start (%s)...", session_start)
                _sleep_or_shutdown(interval, shutdown)
                continue
            if now > session_end:
                LOG.info("past scanner_end (%s); scanner exiting", session_end)
                break

            # Hot-reload check. If the universe builder dropped a
            # fresh snapshot / cache / volume curve since the last
            # check, swap them in before this scan tick. Reads are
            # safe against the builder's atomic write (os.replace).
            new_uni_mtime = _file_mtime(uni_path)
            if new_uni_mtime > last_uni_mtime:
                try:
                    fresh_uni = load_universe_snapshot(cfg)
                    prev_hash = (universe or {}).get("universe_hash")
                    new_hash = fresh_uni.get("universe_hash")
                    universe = fresh_uni
                    last_uni_mtime = new_uni_mtime
                    LOG.info(
                        "universe snapshot reloaded: hash %s -> %s, "
                        "symbols=%d",
                        prev_hash, new_hash,
                        len(universe.get("symbols") or []),
                    )
                except Exception as e:
                    LOG.warning(
                        "universe reload failed (continuing with old): %s",
                        e,
                    )
            new_dfc_mtime = _file_mtime(dfc_path)
            if new_dfc_mtime > last_dfc_mtime:
                try:
                    daily_cache = load_daily_feature_cache(cfg)
                    last_dfc_mtime = new_dfc_mtime
                    LOG.info(
                        "daily_feature_cache reloaded (rows=%d)",
                        len(daily_cache),
                    )
                except Exception as e:
                    LOG.warning(
                        "daily_feature_cache reload failed "
                        "(continuing with old): %s", e,
                    )
            new_vc_mtime = _file_mtime(vc_path)
            if new_vc_mtime > last_vc_mtime:
                try:
                    fresh_vc = load_volume_curve(cfg)
                    if fresh_vc is not None:
                        volume_curve = fresh_vc
                        LOG.info(
                            "volume_curve reloaded (rows=%d)",
                            len(volume_curve),
                        )
                    last_vc_mtime = new_vc_mtime
                except Exception as e:
                    LOG.warning(
                        "volume_curve reload failed "
                        "(continuing with old): %s", e,
                    )

            scan_ts = now.tz_convert("UTC").to_pydatetime()
            try:
                _t_fetch0 = time.monotonic()
                bars_by_sym = prefetch_scan_bars(scan_ts)
                fetch_secs = time.monotonic() - _t_fetch0
                emitted = evaluate_one_scan(
                    cfg=cfg, universe_snapshot=universe,
                    daily_cache=daily_cache, volume_curve=volume_curve,
                    state=state, scan_ts=scan_ts,
                    bars_supplier=lambda sym, _ts: bars_by_sym.get(sym),
                )
                LOG.info(
                    "scan @ %s: emitted=%d events "
                    "(prefetched %d symbols in %.1fs, conc=%d)",
                    scan_ts.isoformat()[:19], len(emitted),
                    len(bars_by_sym), fetch_secs, fetch_concurrency,
                )
            except Exception as e:
                LOG.exception("scan tick raised: %s", e)
            save_scanner_state(state)
            _sleep_or_shutdown(interval, shutdown)
    finally:
        http.close()
    return 0


def _sleep_or_shutdown(interval_seconds: int, shutdown: dict) -> None:
    import time as _time
    slept = 0.0
    while slept < interval_seconds and not shutdown["flag"]:
        _time.sleep(min(1.0, interval_seconds - slept))
        slept += 1.0


def _run_replay(
    cfg: dict, universe: dict, daily_cache, volume_curve, state, args,
) -> int:
    """Replay a fixture JSONL of pre-baked scan ticks."""
    replay_path = Path(args.replay_from)
    if not replay_path.exists():
        LOG.error("replay fixture not found: %s", replay_path)
        return 3
    ticks = []
    for raw in replay_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ticks.append(json.loads(raw))
        except ValueError:
            continue
    LOG.info("replay mode: %d ticks loaded", len(ticks))

    def bars_supplier(symbol: str, scan_ts: datetime) -> pd.DataFrame | None:
        # Pulled from the current tick's "bars_by_symbol" map.
        return current_tick_bars.get(symbol)

    total_emitted = 0
    for tick in ticks:
        scan_ts = pd.Timestamp(tick["scan_timestamp"])
        if scan_ts.tzinfo is None:
            scan_ts = scan_ts.tz_localize("UTC")
        current_tick_bars: dict[str, pd.DataFrame] = {}
        for sym, rows in (tick.get("bars_by_symbol") or {}).items():
            current_tick_bars[sym] = pd.DataFrame(rows)
        events = evaluate_one_scan(
            cfg=cfg,
            universe_snapshot=universe,
            daily_cache=daily_cache,
            volume_curve=volume_curve,
            state=state,
            scan_ts=scan_ts.to_pydatetime(),
            bars_supplier=bars_supplier,
        )
        total_emitted += len(events)
        save_scanner_state(state)
        if args.dry_run:
            # Single-tick replay is enough for the dry-run smoke.
            break
    LOG.info("replay complete: emitted=%d events", total_emitted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
