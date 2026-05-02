"""Phase 2 T-09 — byte-identical relocation of HOLIDAYS_2026.

The 2026 India market-holiday list lived inline in
``database/market_calendar_db.py:307-470`` before the market-agnostic
refactor. Phase 2 T-09 relocates the data into
``market_regions/india/holidays.py`` and has the legacy seed function
read from there. This test pins the relocated data so any future drift
fails loudly — the central parity guarantee of Phase 2.

Acceptance:
* The number of holiday entries is 18.
* Every (date, description, holiday_type) triple matches the legacy
  inline list.
* For TRADING_HOLIDAY rows, the ``closed`` exchange list matches.
* For SPECIAL_SESSION rows, the ``open`` window list (epoch ms in IST)
  matches.
* The legacy seeder ``database.market_calendar_db.seed_holidays_2026``
  loads its data from this module (verified by patching).
"""

from __future__ import annotations

from market_regions.india.holidays import HOLIDAYS_2026


# Snapshot of the (date, description, holiday_type, closed,
# open_count) tuple per entry, taken from the original
# database/market_calendar_db.py inline list. open_count is used to
# detect drift in the special-session windows without copying every
# epoch-millisecond literal.
EXPECTED_2026_DIGEST: list[tuple[str, str, str, tuple[str, ...], int]] = [
    ("2026-01-15", "Municipal Corporation Election - Maharashtra",
     "TRADING_HOLIDAY", ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-01-26", "Republic Day", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"), 0),
    ("2026-03-03", "Holi", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-03-26", "Shri Ram Navami", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-03-31", "Shri Mahavir Jayanti", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-04-03", "Good Friday", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"), 0),
    ("2026-04-14", "Dr. Baba Saheb Ambedkar Jayanti", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-05-01", "Maharashtra Day", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-05-28", "Bakri Id", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-06-26", "Muharram", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-09-14", "Ganesh Chaturthi", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-10-02", "Mahatma Gandhi Jayanti", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"), 0),
    ("2026-10-20", "Dussehra", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-11-08", "Diwali Laxmi Pujan (Muhurat Trading)",
     "SPECIAL_SESSION", (), 7),
    ("2026-11-10", "Diwali Balipratipada", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-11-24", "Prakash Gurpurb Sri Guru Nanak Dev",
     "TRADING_HOLIDAY", ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD"), 1),
    ("2026-12-25", "Christmas", "TRADING_HOLIDAY",
     ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"), 0),
]


def test_holiday_count_matches_snapshot():
    # 17 entries — 16 trading holidays + 1 special session (Diwali
    # Muhurat Trading). Edits to the count must update the snapshot.
    assert len(HOLIDAYS_2026) == len(EXPECTED_2026_DIGEST), (
        f"HOLIDAYS_2026 has {len(HOLIDAYS_2026)} entries; "
        f"snapshot expects {len(EXPECTED_2026_DIGEST)}. If you intend "
        "to edit the calendar, update EXPECTED_2026_DIGEST in this "
        "file too — both sides exist precisely to make data drift "
        "fail loudly."
    )


def test_holiday_byte_identical_to_snapshot():
    for actual, expected in zip(HOLIDAYS_2026, EXPECTED_2026_DIGEST):
        date_, description, holiday_type, closed, open_count = expected
        assert actual["date"] == date_, (
            f"date drift for {description!r}: actual {actual['date']!r} "
            f"vs expected {date_!r}"
        )
        assert actual["description"] == description, (
            f"description drift on {date_}: {actual['description']!r} "
            f"vs {description!r}"
        )
        assert actual["holiday_type"] == holiday_type, (
            f"holiday_type drift on {date_}: {actual['holiday_type']!r}"
        )
        assert tuple(actual["closed"]) == closed, (
            f"closed-exchanges drift on {date_}: "
            f"{actual['closed']!r} vs {list(closed)!r}"
        )
        assert len(actual["open"]) == open_count, (
            f"open-window count drift on {date_}: "
            f"{len(actual['open'])} vs {open_count}"
        )


def test_legacy_seed_function_imports_relocated_data():
    """``database.market_calendar_db.seed_holidays_2026`` must read its
    payload from ``market_regions.india.holidays.HOLIDAYS_2026``."""
    import inspect

    from database import market_calendar_db

    src = inspect.getsource(market_calendar_db.seed_holidays_2026)
    assert "market_regions.india.holidays" in src, (
        "seed_holidays_2026 should import HOLIDAYS_2026 from the "
        "relocated source. Phase 2 T-09 relocated the data; the seeder "
        "must continue to consume it from the region-plugin path."
    )
    assert "HOLIDAYS_2026" in src, (
        "seed_holidays_2026 should use the canonical HOLIDAYS_2026 "
        "name from market_regions.india.holidays."
    )


def test_diwali_muhurat_window_count():
    """The 2026-11-08 special session must carry 7 windows: 6 equity/
    derivatives venues at 18:00–19:15 + MCX 18:00–00:15. Pinning the
    count guards against accidental window deletion."""
    diwali = next(h for h in HOLIDAYS_2026 if h["date"] == "2026-11-08")
    assert diwali["holiday_type"] == "SPECIAL_SESSION"
    venues = sorted(w["exchange"] for w in diwali["open"])
    assert venues == ["BCD", "BFO", "BSE", "CDS", "MCX", "NFO", "NSE"]
