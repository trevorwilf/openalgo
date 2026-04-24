# database/settings_db.py

import base64
import os

from cachetools import TTLCache
from cryptography.fernet import Fernet
from sqlalchemy import Boolean, Column, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from utils.logging import get_logger

logger = get_logger(__name__)

# Settings cache - 1 hour TTL (settings rarely change)
# This cache significantly reduces DB queries since get_analyze_mode() is called on every request
_settings_cache = TTLCache(maxsize=10, ttl=3600)  # 1 hour TTL

DEFAULT_MARKET_REGION = (
    os.getenv("DEFAULT_MARKET_REGION", "india").strip().lower().replace("-", "_") or "india"
)
DATABASE_URL = os.getenv("DATABASE_URL")


def _build_engine(database_url: str | None):
    """Build the SQLAlchemy engine using the project-wide pooling rules."""
    if database_url and "sqlite" in database_url:
        return create_engine(
            database_url, poolclass=NullPool, connect_args={"check_same_thread": False}
        )
    return create_engine(database_url, pool_size=50, max_overflow=100, pool_timeout=10)


engine = _build_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    analyze_mode = Column(Boolean, default=False)  # Default to Live Mode
    default_market_region = Column(String(64), default=DEFAULT_MARKET_REGION, nullable=False)

    # SMTP Configuration
    smtp_server = Column(String(255), nullable=True)
    smtp_port = Column(Integer, nullable=True)
    smtp_username = Column(String(255), nullable=True)
    smtp_password_encrypted = Column(Text, nullable=True)  # Encrypted SMTP password
    smtp_use_tls = Column(Boolean, default=True)
    smtp_from_email = Column(String(255), nullable=True)
    smtp_helo_hostname = Column(String(255), nullable=True)  # HELO/EHLO hostname

    # Security Settings
    security_auto_ban_enabled = Column(Boolean, default=False)  # Auto-ban disabled by default
    security_404_threshold = Column(Integer, default=100)  # 404 errors per day before ban
    security_404_ban_duration = Column(Integer, default=0)  # 0 = permanent ban
    security_api_threshold = Column(Integer, default=100)  # Invalid API attempts before ban
    security_api_ban_duration = Column(Integer, default=0)  # 0 = permanent ban
    security_repeat_offender_limit = Column(Integer, default=2)  # Bans before permanent ban


def init_db():
    """Initialize the settings database"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Settings DB", logger)
    _migrate_add_default_market_region_column()

    # Create default settings only if no settings exist (with race condition protection)
    try:
        if not Settings.query.first():
            logger.debug(
                "Settings DB: Creating default configuration (Live Mode, region=%s)",
                DEFAULT_MARKET_REGION,
            )
            default_settings = Settings(
                analyze_mode=False,
                default_market_region=DEFAULT_MARKET_REGION,
            )
            db_session.add(default_settings)
            db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.debug(f"Settings DB: Default config may already exist (race condition): {e}")


def _migrate_add_default_market_region_column():
    """Add default_market_region column for existing deployments if missing."""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "settings" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("settings")]
        if "default_market_region" in columns:
            return

        with engine.connect() as conn:
            conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN default_market_region VARCHAR(64) "
                    f"DEFAULT '{DEFAULT_MARKET_REGION}'"
                )
            )
            conn.execute(
                text(
                    "UPDATE settings SET default_market_region = :region "
                    "WHERE default_market_region IS NULL OR TRIM(default_market_region) = ''"
                ),
                {"region": DEFAULT_MARKET_REGION},
            )
            conn.commit()
            logger.info("Migration: Added 'default_market_region' column to settings table")
    except Exception as e:
        logger.debug(f"Migration check for default_market_region column: {e}")


def _ensure_settings_row() -> Settings:
    settings = Settings.query.first()
    if not settings:
        settings = Settings(
            analyze_mode=False,
            default_market_region=DEFAULT_MARKET_REGION,
            security_auto_ban_enabled=False,
            security_404_threshold=100,
            security_404_ban_duration=0,
            security_api_threshold=100,
            security_api_ban_duration=0,
            security_repeat_offender_limit=2,
        )
        db_session.add(settings)
        db_session.commit()
    elif not settings.default_market_region:
        settings.default_market_region = DEFAULT_MARKET_REGION
        db_session.commit()
    return settings


def _invalidate_cache(*keys: str) -> None:
    if not keys:
        _settings_cache.clear()
        return
    for key in keys:
        _settings_cache.pop(key, None)


def get_analyze_mode():
    """Get current analyze mode setting (cached for 1 hour)"""
    cache_key = "analyze_mode"

    if cache_key in _settings_cache:
        return _settings_cache[cache_key]

    settings = _ensure_settings_row()
    _settings_cache[cache_key] = settings.analyze_mode
    return settings.analyze_mode


def set_analyze_mode(mode: bool):
    """Set analyze mode setting"""
    settings = _ensure_settings_row()
    settings.analyze_mode = mode
    db_session.commit()
    _invalidate_cache("analyze_mode")


def get_default_market_region() -> str:
    """Get the configured default market-region code."""
    cache_key = "default_market_region"
    if cache_key in _settings_cache:
        return _settings_cache[cache_key]

    settings = _ensure_settings_row()
    value = (settings.default_market_region or DEFAULT_MARKET_REGION).strip().lower()
    _settings_cache[cache_key] = value
    return value


def set_default_market_region(region_code: str) -> None:
    """Persist the configured default market-region code."""
    normalized = str(region_code).strip().lower().replace("-", "_")
    if not normalized:
        raise ValueError("default market region cannot be empty")

    settings = _ensure_settings_row()
    settings.default_market_region = normalized
    db_session.commit()
    _invalidate_cache("default_market_region")
    logger.info("Default market region updated successfully: %s", normalized)


def get_market_region_settings() -> dict[str, str]:
    """Get persisted market-region settings."""
    return {"default_market_region": get_default_market_region()}


def _get_encryption_key():
    """Get or create encryption key for SMTP password"""
    # Use API_KEY_PEPPER as the base for encryption key
    pepper = os.getenv("API_KEY_PEPPER", "default-pepper-key")
    # Create a stable key from the pepper
    key = base64.urlsafe_b64encode(pepper.ljust(32)[:32].encode())
    return key


def _encrypt_password(password: str) -> str | None:
    """Encrypt SMTP password"""
    if not password:
        return None
    key = _get_encryption_key()
    f = Fernet(key)
    encrypted = f.encrypt(password.encode())
    return encrypted.decode()


def _decrypt_password(encrypted_password: str) -> str | None:
    """Decrypt SMTP password"""
    if not encrypted_password:
        return None
    key = _get_encryption_key()
    f = Fernet(key)
    decrypted = f.decrypt(encrypted_password.encode())
    return decrypted.decode()


def get_smtp_settings():
    """Get SMTP configuration"""
    settings = _ensure_settings_row()

    return {
        "smtp_server": settings.smtp_server,
        "smtp_port": settings.smtp_port,
        "smtp_username": settings.smtp_username,
        "smtp_password": _decrypt_password(settings.smtp_password_encrypted)
        if settings.smtp_password_encrypted
        else None,
        "smtp_use_tls": settings.smtp_use_tls,
        "smtp_from_email": settings.smtp_from_email,
        "smtp_helo_hostname": settings.smtp_helo_hostname,
    }


def set_smtp_settings(
    smtp_server=None,
    smtp_port=None,
    smtp_username=None,
    smtp_password=None,
    smtp_use_tls=True,
    smtp_from_email=None,
    smtp_helo_hostname=None,
):
    """Set SMTP configuration"""
    settings = _ensure_settings_row()

    if smtp_server is not None:
        settings.smtp_server = smtp_server
    if smtp_port is not None:
        settings.smtp_port = smtp_port
    if smtp_username is not None:
        settings.smtp_username = smtp_username
    if smtp_password is not None:
        settings.smtp_password_encrypted = _encrypt_password(smtp_password)
    if smtp_use_tls is not None:
        settings.smtp_use_tls = smtp_use_tls
    if smtp_from_email is not None:
        settings.smtp_from_email = smtp_from_email
    if smtp_helo_hostname is not None:
        settings.smtp_helo_hostname = smtp_helo_hostname

    db_session.commit()
    logger.info("SMTP settings updated successfully")


def get_security_settings():
    """Get security configuration (cached for 1 hour)"""
    cache_key = "security_settings"

    if cache_key in _settings_cache:
        return _settings_cache[cache_key]

    settings = _ensure_settings_row()

    result = {
        "auto_ban_enabled": bool(settings.security_auto_ban_enabled)
        if settings.security_auto_ban_enabled is not None
        else False,
        "404_threshold": settings.security_404_threshold or 100,
        "404_ban_duration": settings.security_404_ban_duration
        if settings.security_404_ban_duration is not None
        else 0,
        "api_threshold": settings.security_api_threshold or 100,
        "api_ban_duration": settings.security_api_ban_duration
        if settings.security_api_ban_duration is not None
        else 0,
        "repeat_offender_limit": settings.security_repeat_offender_limit or 2,
    }

    _settings_cache[cache_key] = result
    return result


def set_security_settings(
    auto_ban_enabled=None,
    threshold_404=None,
    ban_duration_404=None,
    threshold_api=None,
    ban_duration_api=None,
    repeat_offender_limit=None,
):
    """Set security configuration"""
    settings = _ensure_settings_row()

    if auto_ban_enabled is not None:
        settings.security_auto_ban_enabled = auto_ban_enabled
    if threshold_404 is not None:
        settings.security_404_threshold = threshold_404
    if ban_duration_404 is not None:
        settings.security_404_ban_duration = ban_duration_404
    if threshold_api is not None:
        settings.security_api_threshold = threshold_api
    if ban_duration_api is not None:
        settings.security_api_ban_duration = ban_duration_api
    if repeat_offender_limit is not None:
        settings.security_repeat_offender_limit = repeat_offender_limit

    db_session.commit()
    logger.info("Security settings updated successfully")
    _invalidate_cache("security_settings")


def clear_settings_cache():
    """
    Clear all settings caches.
    Called on logout/session expiry to ensure fresh data on next login.
    """
    _settings_cache.clear()
    logger.info("Settings cache cleared")


# Test hooks ---------------------------------------------------------------


def _reset_engine_for_tests() -> None:
    """Rebind the module-global engine/session to the current DATABASE_URL."""
    global DATABASE_URL, engine
    DATABASE_URL = os.getenv("DATABASE_URL")
    try:
        db_session.remove()
    except Exception:
        pass
    try:
        engine.dispose()
    except Exception:
        pass
    engine = _build_engine(DATABASE_URL)
    db_session.configure(bind=engine)
    clear_settings_cache()


__all__ = [
    "Settings",
    "clear_settings_cache",
    "db_session",
    "get_analyze_mode",
    "get_default_market_region",
    "get_market_region_settings",
    "get_security_settings",
    "get_smtp_settings",
    "init_db",
    "set_analyze_mode",
    "set_default_market_region",
    "set_security_settings",
    "set_smtp_settings",
]
