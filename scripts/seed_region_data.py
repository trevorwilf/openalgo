"""Phase 3 v4 (ADR 0023, ADR 0024) — idempotent seeder for region
plugin venues, session templates, and calendar exceptions.

Reads each ``market_regions/<code>/plugin.json`` and upserts:

* ``venues`` rows in ``database.instruments_repo`` (one per
  ``venue_code`` declared in the plugin's ``venues`` block).
* ``venue_schedule_templates`` rows in
  ``database.venue_schedule_repo`` (one per (venue, day_of_week,
  session_type) combination).
* ``venue_calendar_exceptions`` rows for declared exceptions.

Idempotent — re-running does not duplicate rows. Safe to wire into
app startup behind a settings flag, and safe as a CLI:

    uv run python -m scripts.seed_region_data
    uv run python -m scripts.seed_region_data --region india
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _venue_code_for_repo(seed_venue_code: str) -> str:
    return str(seed_venue_code).strip()


def _seed_one_region(region) -> dict[str, int]:
    """Seed venues + schedule templates + calendar exceptions for one
    :class:`MarketRegion`. Returns counts for reporting."""
    from database import instruments_repo
    from database import venue_schedule_repo

    counts = {"venues": 0, "templates": 0, "exceptions": 0}

    # Venues — instruments_repo.venues_upsert
    for v in region.venues:
        market_family_value = (
            getattr(v.market_family, "value", v.market_family)
            if v.market_family
            else "EXCHANGE"
        )
        instruments_repo.venues_upsert(
            venue_code=_venue_code_for_repo(v.venue_code),
            market_family=str(market_family_value),
            timezone_name=v.timezone_name or region.timezone_name,
            country_code=v.country_code,
            base_currency=v.base_currency or (
                getattr(region.default_currency, "value", region.default_currency)
            ),
            settlement_type=v.settlement_template,
            session_model=v.session_model,
            display_name=v.display_name,
            metadata={
                "mic_code": v.mic_code,
                "region_code": region.region_code,
            },
        )
        counts["venues"] += 1

    # Session templates — one row per (venue, day_of_week, session_type).
    for tpl in region.session_templates:
        session_type = getattr(tpl.session_code, "value", str(tpl.session_code))
        for venue_code in tpl.venue_codes:
            for dow in tpl.days_of_week:
                venue_schedule_repo.upsert_schedule_template(
                    venue_code=venue_code,
                    day_of_week=int(dow),
                    session_type=session_type,
                    starts_at_local=tpl.local_start_time,
                    ends_at_local=tpl.local_end_time,
                    is_active=True,
                    metadata={
                        "label": tpl.label,
                        "region_code": region.region_code,
                    } if tpl.label else {"region_code": region.region_code},
                )
                counts["templates"] += 1

    # Calendar exceptions
    for exc in region.calendar_exceptions:
        venue_schedule_repo.upsert_calendar_exception(
            venue_code=exc.venue_code,
            session_date=exc.date,
            exception_type=exc.exception_type,
            starts_at_local=exc.local_start_time,
            ends_at_local=exc.local_end_time,
            description=exc.reason,
            metadata={"region_code": region.region_code, "source": exc.source},
        )
        counts["exceptions"] += 1

    return counts


def seed_all_regions(region_codes: list[str] | None = None) -> dict[str, dict[str, int]]:
    """Seed every installed region (or just the listed codes). Returns
    per-region counts for reporting / tests."""
    from utils.region_loader import load_market_regions

    regions = load_market_regions()
    if region_codes:
        wanted = {c.strip().lower() for c in region_codes}
        regions = {k: v for k, v in regions.items() if k in wanted}

    out: dict[str, dict[str, int]] = {}
    for code, region in regions.items():
        try:
            counts = _seed_one_region(region)
        except Exception as e:  # pragma: no cover - log + re-raise
            logger.exception("Failed to seed region %r: %s", code, e)
            raise
        out[code] = counts
        logger.info(
            "Seeded region %r: %d venues, %d templates, %d exceptions",
            code,
            counts["venues"],
            counts["templates"],
            counts["exceptions"],
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--region",
        action="append",
        help="Only seed the named region (may be repeated). Default: all.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    counts = seed_all_regions(region_codes=args.region)
    total = sum(c["venues"] for c in counts.values())
    print(f"Seeded {len(counts)} regions, {total} venues total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
