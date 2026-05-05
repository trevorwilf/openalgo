"""Phase 1 — Datafeed Foundation: chart workspace persistence schema.

Adds the 9 new tables described in HANDOFF Phase 1 §6 to ``openalgo.db``.
The migration is **purely additive** — it never alters or drops the
legacy ``chart_preferences`` table (which lives behind the
``database.chart_prefs_db`` shim and is owned by the v1 lane).

Tables created here:

* ``chart_workspace_layouts``
* ``chart_drawings``
* ``chart_indicators``
* ``chart_watchlists``
* ``chart_templates``
* ``chart_workspace_active``
* ``audit_log_chart_orders``  (DELETE blocked via trigger — Q-17)
* ``chart_strategy_signals``
* ``chart_safety_settings``   (Phase 6 wires this; created in Phase 1)

All schemas carry a ``schema_version`` field on the JSON-bearing tables
(starts at 1 — D-07).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")


# Module-level engine + session — created lazily so unit tests can swap.
_engine: Engine | None = None
_Session = None
Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ChartWorkspaceLayout(Base):
    """A user-named workspace layout — a tab in the workspace picker.

    `cells_json` carries the per-cell engine/symbol/timeframe/etc.
    state. `schema_version` lets us migrate the JSON shape without
    altering rows in place.
    """

    __tablename__ = "chart_workspace_layouts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    cells_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_chart_layout_user_name"),
    )


class ChartDrawing(Base):
    __tablename__ = "chart_drawings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    layout_id = Column(Integer, nullable=False, index=True)
    cell_id = Column(String(64), nullable=False)
    kind = Column(String(32), nullable=False)
    params_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("ix_chart_drawings_layout_cell", "layout_id", "cell_id"),
    )


class ChartIndicator(Base):
    __tablename__ = "chart_indicators"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    layout_id = Column(Integer, nullable=False, index=True)
    cell_id = Column(String(64), nullable=False)
    indicator_key = Column(String(64), nullable=False)
    params_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("ix_chart_indicators_layout_cell", "layout_id", "cell_id"),
    )


class ChartWatchlist(Base):
    __tablename__ = "chart_watchlists"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    symbols_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_chart_watchlist_user_name"),
    )


class ChartTemplate(Base):
    __tablename__ = "chart_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    cells_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_chart_template_user_name"),
    )


class ChartWorkspaceActive(Base):
    """Per-user active layout pointer (one row per user)."""

    __tablename__ = "chart_workspace_active"
    user_id = Column(String(64), primary_key=True)
    layout_id = Column(Integer, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class AuditLogChartOrder(Base):
    """Append-only audit row for every chart-originated order intent.

    DELETE is blocked at the DB level via a trigger — see
    :func:`_install_audit_delete_block`. Q-17: retention is forever.
    """

    __tablename__ = "audit_log_chart_orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    account_id = Column(String(64), nullable=False)
    ts_utc = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    intent_kind = Column(String(32), nullable=False)
    symbol = Column(String(64), nullable=False)
    qty = Column(String(32), nullable=False)  # decimal-as-string
    price = Column(String(32), nullable=True)  # null for MARKET
    idempotency_token = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False)
    broker_response_json = Column(Text, nullable=True)
    chart_origin = Column(Boolean, nullable=False, default=True)


class ChartStrategySignal(Base):
    __tablename__ = "chart_strategy_signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    ts_utc = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)
    symbol = Column(String(64), nullable=False)
    kind = Column(String(32), nullable=False)
    payload_json = Column(Text, nullable=False, default="{}")
    source = Column(String(64), nullable=False)


class ChartSafetySettings(Base):
    """Per-user/per-account safety guardrails — populated by Phase 6.

    Created in Phase 1 because the schema is referenced by the audit
    log + pre-trade validator contracts. Default rows resolve via the
    safety_defaults service at write time.
    """

    __tablename__ = "chart_safety_settings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    account_id = Column(String(64), nullable=False)
    max_order_size = Column(Integer, nullable=False, default=100)
    max_notional = Column(String(32), nullable=False, default="100000")
    kill_switch_state = Column(Boolean, nullable=False, default=False)
    live_mode_enabled = Column(Boolean, nullable=False, default=False)
    live_mode_acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "account_id", name="uq_chart_safety_user_account"
        ),
    )


# ---------------------------------------------------------------------------
# Engine + session
# ---------------------------------------------------------------------------


def _make_engine(url: str) -> Engine:
    """Engine factory — uses NullPool for SQLite per CLAUDE.md guidance."""
    if url.startswith("sqlite"):
        return create_engine(url, poolclass=NullPool)
    return create_engine(url)


def get_engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        # Re-read DATABASE_URL on each lazy-init so unit tests that
        # set the env var via ``monkeypatch.setenv`` AFTER the module
        # is imported get a fresh per-test SQLite. The module-level
        # ``DATABASE_URL`` is the production default; when an env var
        # is present at engine-build time, it wins.
        url = os.getenv("DATABASE_URL", DATABASE_URL)
        _engine = _make_engine(url)
        _Session = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        )
    return _engine


def get_session():
    get_engine()
    return _Session()


def _reset_engine_for_tests() -> None:
    """Force the next call to :func:`get_engine` to rebuild from the
    current ``DATABASE_URL`` environment variable. Used by per-test
    fixtures so chart-workspace state does not leak across tests via
    a shared SQLite file.
    """
    global _engine, _Session
    if _Session is not None:
        try:
            _Session.remove()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:  # noqa: BLE001
            pass
    _engine = None
    _Session = None


def _install_audit_delete_block(engine: Engine) -> None:
    """Install a SQLite trigger that raises on DELETE from
    ``audit_log_chart_orders`` (Q-17 — append-only forever).

    On non-SQLite backends, the equivalent constraint should be added
    via that backend's native trigger / role grant — left as a TODO for
    the deployment.
    """
    if not engine.url.drivername.startswith("sqlite"):
        return
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TRIGGER IF NOT EXISTS trg_block_audit_chart_orders_delete
            BEFORE DELETE ON audit_log_chart_orders
            BEGIN
                SELECT RAISE(ABORT, 'audit_log_chart_orders is append-only; DELETE blocked by trigger (Q-17)');
            END;
            """
        )


def init_chart_workspace_db(engine: Engine | None = None) -> Engine:
    """Create the 9 chart tables on the configured DB if they don't exist.

    Idempotent. Safe to call at app startup.
    """
    eng = engine or get_engine()
    Base.metadata.create_all(eng)
    _install_audit_delete_block(eng)
    logger.info("Chart workspace DB tables ensured at %s", eng.url)
    return eng


def create_all_for_test(engine: Engine) -> None:
    """Test helper — installs the schema (incl. delete-block trigger)
    on a caller-provided engine (typically an in-memory SQLite).
    """
    Base.metadata.create_all(engine)
    _install_audit_delete_block(engine)


def drop_all_for_test(engine: Engine) -> None:
    """Test teardown — drops every chart-workspace table on the
    caller's engine. Used by the migration rollback test.
    """
    if engine.url.drivername.startswith("sqlite"):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "DROP TRIGGER IF EXISTS trg_block_audit_chart_orders_delete"
            )
    Base.metadata.drop_all(engine)


# Import-time guard — ensure the trigger is reinstated after any
# ``Base.metadata.create_all(engine)`` invocation (e.g., when a new
# blueprint init runs).
@event.listens_for(Base.metadata, "after_create")
def _after_create(target: Any, connection: Any, **kw: Any) -> None:
    try:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql(
                """
                CREATE TRIGGER IF NOT EXISTS trg_block_audit_chart_orders_delete
                BEFORE DELETE ON audit_log_chart_orders
                BEGIN
                    SELECT RAISE(ABORT, 'audit_log_chart_orders is append-only; DELETE blocked by trigger (Q-17)');
                END;
                """
            )
    except Exception as e:  # pragma: no cover
        logger.warning("audit DELETE block trigger install failed: %s", e)


__all__ = [
    "AuditLogChartOrder",
    "Base",
    "ChartDrawing",
    "ChartIndicator",
    "ChartSafetySettings",
    "ChartStrategySignal",
    "ChartTemplate",
    "ChartWatchlist",
    "ChartWorkspaceActive",
    "ChartWorkspaceLayout",
    "create_all_for_test",
    "drop_all_for_test",
    "get_engine",
    "get_session",
    "init_chart_workspace_db",
]
