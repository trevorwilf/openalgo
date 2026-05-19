# Bowaka v1 → v2 Migration Guide

## What changed

| Area | v1 | v2 |
|---|---|---|
| Entry discovery | Once-per-session via prior-day candidate file | Continuous all-day forming-bar scanner |
| Candidate source | `data/in_play_candidates.json` (single file) | `data/bowaka_v2/candidate_events.jsonl` (stream) |
| Schema | ad-hoc + v1 prefilter shape | schema_version=3 (event-typed) |
| Signal timing | Prior completed daily bar | Forming session/day bar |
| Volume feature | Full-day RVOL (back-dated) | RVOL_so_far + projected_full_day_rvol via curve |
| ATR | Daily ATR (could include today) | Prior completed-session ATR only |
| Close location | EOD close location | last-price location within forming range |
| Universe layer | conflated with signal gates | universe is "garbage filter" only |
| Scanner process | n/a (in-strategy) | separate `bowaka_intraday_scanner.py` |
| Process model | one process | universe_builder → scanner → strategy split |

## File-by-file map

| v1 (status) | v2 |
|---|---|
| `bowaka_prefilter.py` (archived) | `bowaka_universe_builder.py` (universe) + `bowaka_intraday_scanner.py` (forming bars) |
| `bowaka_prefilter.yaml` (archived) | `bowaka_universe_builder.yaml` + `bowaka_v2_config.yaml` |
| `bowaka_prefilter.cron` (archived) | `bowaka_universe_builder.cron` + `bowaka_intraday_scanner.cron` |
| `bowaka_strategy.py` (preserved as baseline) | `bowaka_v2_strategy.py` (event consumer) |
| `bowaka_strategy.yaml` (operator decides) | `bowaka_v2_config.yaml` |
| `bowaka_analysis.py` (kept) | `bowaka_v2_analysis.py` |
| `bowaka_counterfactuals.py` (kept) | `bowaka_v2_counterfactuals.py` |
| n/a | `bowaka_v2_features.py` — shared causal feature module |
| n/a | `bowaka_v2_schemas.py` — schema-v3 validators |
| n/a | `bowaka_v2_paths.py` — single source of truth |
| n/a | `bowaka_v2_backtest.py` + `cost_model` + `ablation` + `bucket_analysis` + `replay_data` |
| n/a | `bowaka_v2_stream.py` + `heartbeat.py` + `dashboard.py` + `replay.py` |

## Behavior delta (research-grade)

- v2 may produce candidates v1 missed (regime transitions
  mid-session). It may also produce more rejected entries (the
  scanner sees more names).
- Per-symbol once-per-day rule still holds.
- Bracket pricing mode = `actual_fill` unchanged.
- Cost model in the backtester is conservative-by-default; live
  fills may be tighter.

## What's preserved

Per handoff §3.3 ("keep v1 as a baseline/control"), v1 modules
remain importable. The v2 strategy reuses v1's ADV-tier caps,
ledger, bankroll, sizing, kill switches, and OCO bracket attach
plumbing via the narrow `_v1_reuse` alias.

## Acceptance gates (per handoff §8.9 + §8.10)

Before paper trading v2:
1. No-lookahead unit tests passing.
2. SIP data available (or research flag set explicitly).
3. v2 backtest positive net expectancy after conservative costs.
4. ADV/spread bucket analysis identifies tradable edge regions.
5. Entry-delay sensitivity proves edge survives latency.
6. Paper execution logs every candidate + rejection + order + fill.

Before live trading v2:
1. 30–60 trading days of paper with v2 scanner.
2. Paper-vs-sim slippage within tolerance.
3. Daily loss + gross exposure caps active.
4. Halt handling tested.
5. Signal-fade exit logic validated.
6. Final review by quant + engineer.

## Rollback

If v2 misbehaves and you need to fall back:

```
ENVIRONMENT=paper
BOWAKA_V2_CFG=strategies/scripts/data/bowaka_v2/archive_v2.yaml  # disable v2
# Re-enable v1: restore strategies/scripts/archive/v1_prefilter/* to scripts/
# Re-point watchdog wrappers at bowaka_strategy.py + bowaka_strategy.yaml
```

v1 baseline is preserved untouched in the repo.
