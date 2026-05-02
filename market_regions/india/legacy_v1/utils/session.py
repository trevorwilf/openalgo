import os
from datetime import datetime, timedelta
from functools import wraps

import pytz
from flask import redirect, session, url_for

from utils.logging import get_logger

logger = get_logger(__name__)


# Phase 4 v3 + Phase 2 v4 — Session expiry runs in this timezone,
# configured per-deployment via SESSION_EXPIRY_TIMEZONE. v4 invariant 1
# (ADR 0023): the timezone resolution is fail-closed for non-India
# brokers. If the env var is unset:
#
#   * Active broker resolves to an India region: use Asia/Kolkata
#     (preserves existing Indian deployments).
#   * Active broker resolves to a non-India region: raise
#     ConfigurationError; operator must set SESSION_EXPIRY_TIMEZONE.
#   * No active broker yet (early bootstrap before login): use
#     Asia/Kolkata as the last-resort default and log a one-shot warning
#     so first runs of fresh non-India deployments still come up.
#
# The expiry *time of day* continues to come from SESSION_EXPIRY_TIME
# (HH:MM, default 03:00).
def _session_tz() -> pytz.BaseTzInfo:
    name = os.getenv("SESSION_EXPIRY_TIMEZONE")
    if name:
        try:
            return pytz.timezone(name)
        except pytz.UnknownTimeZoneError:
            logger.warning(
                "SESSION_EXPIRY_TIMEZONE=%r is not a recognised IANA tz; "
                "falling back to Asia/Kolkata",
                name,
            )
            return pytz.timezone("Asia/Kolkata")

    # Env unset — resolve via the active BROKER session. Only a
    # confidently-resolved non-India broker triggers the fail-closed
    # path; absence of a broker session (early bootstrap, settings-
    # only state) now returns UTC and emits a one-shot warning so
    # India deployments do not silently inherit Asia/Kolkata across
    # bootstrap any more (Phase 1 T-08).
    broker_caps = _resolve_active_broker_caps()
    if broker_caps is None:
        # No broker session yet — bootstrap path. Phase 1 T-08:
        # default to UTC so non-India operators do not silently
        # inherit Asia/Kolkata before they have a chance to log in
        # and resolve the active broker. India operators continue
        # to set SESSION_EXPIRY_TIMEZONE=Asia/Kolkata if they want
        # the legacy behavior in the bootstrap window.
        if not getattr(_session_tz, "_bootstrap_warned", False):
            logger.warning(
                "bootstrap_session_tz_default_utc — no active broker "
                "session and SESSION_EXPIRY_TIMEZONE is unset; "
                "defaulting to UTC for the bootstrap window. Set "
                "SESSION_EXPIRY_TIMEZONE explicitly if a non-default "
                "timezone is required pre-login."
            )
            _session_tz._bootstrap_warned = True  # type: ignore[attr-defined]
        return pytz.timezone("UTC")

    regions = list(getattr(broker_caps, "supported_regions", None) or [])
    region_codes = [str(r).strip().lower() for r in regions]
    if not regions or "india" in region_codes:
        return pytz.timezone("Asia/Kolkata")

    # Confidently-resolved non-India broker — fail-closed.
    from domain.errors import ConfigurationError

    raise ConfigurationError(
        f"SESSION_EXPIRY_TIMEZONE must be set for non-India deployments "
        f"(active broker regions: {region_codes!r}). Set the env var to "
        f"a valid IANA timezone identifier (e.g., 'America/New_York', "
        f"'Europe/Berlin').",
        missing_env="SESSION_EXPIRY_TIMEZONE",
    )


def _resolve_active_broker_caps():
    """Return ``BrokerCapabilities`` for the broker in the Flask
    session, or ``None`` when there is no session / capability lookup
    fails. Defensive — never raises.
    """
    try:
        from flask import session

        broker = session.get("broker")
    except Exception:
        return None
    if not broker:
        return None
    try:
        from utils.plugin_loader import get_broker_capabilities

        return get_broker_capabilities(broker)
    except Exception:
        return None


def is_session_expiry_disabled():
    """Check if session expiry is disabled (e.g., for crypto brokers with 24/7 markets).

    Note: Each OpenAlgo instance serves a single broker, so this env var is
    instance-scoped — it only affects the broker configured for this instance,
    not all brokers globally.  The install script sets it automatically when
    a crypto broker (e.g. deltaexchange) is selected.
    """
    return os.getenv("DISABLE_SESSION_EXPIRY", "false").lower() == "true"


def get_session_expiry_time():
    """Get session expiry time at SESSION_EXPIRY_TIME in SESSION_EXPIRY_TIMEZONE.

    The default tz is Asia/Kolkata so existing Indian deployments are
    unchanged. Set SESSION_EXPIRY_TIMEZONE=America/New_York (etc.)
    when running against a US-broker instance.
    """
    if is_session_expiry_disabled():
        logger.debug("Session expiry disabled (crypto broker / 24/7 market)")
        return timedelta(days=365)

    tz = _session_tz()
    now_local = datetime.now(pytz.utc).astimezone(tz)

    expiry_time = os.getenv("SESSION_EXPIRY_TIME", "03:00")
    hour, minute = map(int, expiry_time.split(":"))

    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now_local > target:
        target += timedelta(days=1)

    remaining = target - now_local
    logger.debug("Session expiry time set to: %s (%s)", target, tz.zone)
    return remaining


def set_session_login_time():
    """Set the session login time in the configured session-expiry tz."""
    tz = _session_tz()
    now_local = datetime.now(pytz.utc).astimezone(tz)
    session["login_time"] = now_local.isoformat()
    logger.info("Session login time set to: %s (%s)", now_local, tz.zone)


def is_session_valid():
    """Check if the current session is valid.

    Validity = `session.logged_in` true AND `login_time` present AND
    we haven't crossed the daily SESSION_EXPIRY_TIME boundary in the
    configured SESSION_EXPIRY_TIMEZONE since login.
    """
    if not session.get("logged_in"):
        logger.debug("Session invalid: 'logged_in' flag not set")
        return False

    if "login_time" not in session:
        logger.debug("Session invalid: 'login_time' not in session")
        return False

    if is_session_expiry_disabled():
        logger.debug("Session expiry disabled (crypto broker / 24/7 market)")
        return True

    tz = _session_tz()
    now_local = datetime.now(pytz.utc).astimezone(tz)

    login_time = datetime.fromisoformat(session["login_time"])

    expiry_time = os.getenv("SESSION_EXPIRY_TIME", "03:00")
    hour, minute = map(int, expiry_time.split(":"))

    daily_expiry = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if now_local > daily_expiry and login_time < daily_expiry:
        logger.info("Session expired at %s (%s)", daily_expiry, tz.zone)
        return False

    logger.debug(
        "Session valid. Current time: %s, Login time: %s, Daily expiry: %s",
        now_local,
        login_time,
        daily_expiry,
    )
    return True


def revoke_user_tokens(revoke_db_tokens=True):
    """
    Revoke auth tokens for the current user when session expires.

    Also publishes cache invalidation events via ZeroMQ for multi-process deployments.
    This ensures WebSocket proxy and other processes clear their stale cached tokens.
    See GitHub issue #765 for details on the cross-process cache synchronization problem.

    Args:
        revoke_db_tokens (bool): If True, revokes the token in the database (Invalidates API Key).
                                 If False, only clears local caches (Preserves API Key).
    """
    if "user" in session:
        username = session.get("user")
        try:
            from database.auth_db import auth_cache, feed_token_cache, upsert_auth

            # Clear cache entries first to prevent stale data access
            cache_key_auth = f"auth-{username}"
            cache_key_feed = f"feed-{username}"
            if cache_key_auth in auth_cache:
                del auth_cache[cache_key_auth]
            if cache_key_feed in feed_token_cache:
                del feed_token_cache[cache_key_feed]

            # Publish cache invalidation event via ZeroMQ for other processes
            # This notifies WebSocket proxy and other processes to clear their stale caches
            try:
                from database.cache_invalidation import publish_all_cache_invalidation
                publish_all_cache_invalidation(username)
                logger.debug(f"Published cache invalidation for user: {username}")
            except Exception as invalidation_error:
                # Don't fail logout if cache invalidation fails
                logger.warning(f"Failed to publish cache invalidation for user {username}: {invalidation_error}")

            # Clear symbol cache on logout/session expiry
            try:
                from database.master_contract_cache_hook import clear_cache_on_logout

                clear_cache_on_logout()
            except Exception as cache_error:
                logger.exception(f"Error clearing symbol cache: {cache_error}")

            # Clear settings cache on logout/session expiry
            try:
                from database.settings_db import clear_settings_cache

                clear_settings_cache()
            except Exception as cache_error:
                logger.exception(f"Error clearing settings cache: {cache_error}")

            # Clear strategy cache on logout/session expiry
            try:
                from database.strategy_db import clear_strategy_cache

                clear_strategy_cache()
            except Exception as cache_error:
                logger.exception(f"Error clearing strategy cache: {cache_error}")

            # Clear telegram cache on logout/session expiry
            try:
                from database.telegram_db import clear_telegram_cache

                clear_telegram_cache()
            except Exception as cache_error:
                logger.exception(f"Error clearing telegram cache: {cache_error}")

            if revoke_db_tokens:
                # Revoke the auth token in database
                inserted_id = upsert_auth(username, "", "", revoke=True)
                if inserted_id is not None:
                    logger.info(f"Auto-expiry: Revoked auth tokens for user: {username}")
                else:
                    logger.error(f"Auto-expiry: Failed to revoke auth tokens for user: {username}")

                # Clear all active sessions for this user (tokens are invalid now)
                try:
                    from database.auth_db import clear_user_sessions
                    clear_user_sessions(username)
                    logger.info(f"Auto-expiry: Cleared active sessions for user: {username}")
                except Exception as session_error:
                    logger.warning(f"Error clearing active sessions: {session_error}")
            else:
                logger.info(
                    f"Auto-expiry: Skipped DB revocation for user: {username} (Preserving API access)"
                )

        except Exception as e:
            logger.exception(f"Error revoking tokens during auto-expiry for user {username}: {e}")


def check_session_validity(f):
    """Decorator to check session validity before executing route"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            # Revoke tokens before clearing session
            revoke_user_tokens()
            session.clear()

            # Check if this is an AJAX/fetch request
            from flask import jsonify, request

            is_ajax = (
                request.headers.get("X-Requested-With") == "XMLHttpRequest"
                or request.headers.get("Accept", "").startswith("application/json")
                or request.content_type == "application/json"
                or request.is_json
            )

            if is_ajax:
                # Return JSON response for AJAX requests instead of redirect
                # This prevents consuming rate limits on the login endpoint
                logger.info("Invalid session detected - returning 401 for AJAX request")
                return jsonify(
                    {
                        "status": "error",
                        "error": "session_expired",
                        "message": "Your session has expired. Please log in again.",
                    }
                ), 401

            logger.info("Invalid session detected - redirecting to login")
            return redirect(url_for("auth.login"))
        logger.debug("Session validated successfully")
        return f(*args, **kwargs)

    return decorated_function


def invalidate_session_if_invalid(f):
    """Decorator to invalidate session if invalid without redirecting"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            logger.info("Invalid session detected - clearing session")
            # Revoke tokens before clearing session
            revoke_user_tokens()
            session.clear()
        return f(*args, **kwargs)

    return decorated_function
