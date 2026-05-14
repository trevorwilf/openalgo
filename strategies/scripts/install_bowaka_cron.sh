#!/usr/bin/env bash
# ============================================================
# install_bowaka_cron.sh
#
# Linux/macOS equivalent of install_bowaka_task.cmd. Installs
# bowaka_prefilter.cron at /etc/cron.d/bowaka_prefilter so the
# prefilter fires at 02:00 MT on weekdays with hourly retries
# through 06:00 MT.
#
# REQUIRES root (writes /etc/cron.d/ — owned by root:root,
# mode 0644). Re-run after editing bowaka_prefilter.cron.
#
# Usage:
#   sudo ./install_bowaka_cron.sh                  # install
#   sudo ./install_bowaka_cron.sh --remove         # uninstall
#   sudo OPENALGO_ROOT=/srv/openalgo \
#        BOWAKA_USER=trader \
#        ./install_bowaka_cron.sh                  # custom paths
#
# For macOS / non-systemd Linux, edit the per-user crontab via
# ``crontab -e`` instead — /etc/cron.d/ is Debian/RHEL-only.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/bowaka_prefilter.cron"
DEST="/etc/cron.d/bowaka_prefilter"

OPENALGO_ROOT="${OPENALGO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
BOWAKA_USER="${BOWAKA_USER:-$(id -un)}"

if [ "${1:-}" = "--remove" ]; then
    if [ ! -f "$DEST" ]; then
        echo "Already removed: $DEST does not exist"
        exit 0
    fi
    sudo rm -f "$DEST"
    echo "Removed $DEST"
    # Cron picks up the change without an explicit reload, but
    # reload-if-systemd to be explicit.
    if command -v systemctl >/dev/null 2>&1; then
        sudo systemctl reload cron 2>/dev/null \
            || sudo systemctl reload crond 2>/dev/null \
            || true
    fi
    exit 0
fi

if [ ! -f "$SRC" ]; then
    echo "ERROR: $SRC not found" 1>&2
    exit 2
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: must run as root (try: sudo $0 $*)" 1>&2
    exit 1
fi

# Substitute OPENALGO_ROOT + BOWAKA_USER into the template before
# install. The template carries placeholder defaults; the operator's
# environment wins.
echo "Installing $DEST"
echo "  OPENALGO_ROOT=$OPENALGO_ROOT"
echo "  BOWAKA_USER=$BOWAKA_USER"

# sed -E for cross-distro portability (GNU + BSD)
sed -E \
    -e "s|^OPENALGO_ROOT=.*|OPENALGO_ROOT=${OPENALGO_ROOT}|" \
    -e "s|^BOWAKA_USER=.*|BOWAKA_USER=${BOWAKA_USER}|" \
    "$SRC" > "$DEST"

chmod 0644 "$DEST"
chown root:root "$DEST"

# Reload cron service. Different distros use different service names.
if command -v systemctl >/dev/null 2>&1; then
    if systemctl list-units --type=service --all 2>/dev/null | grep -q '\bcron\b'; then
        systemctl reload cron || true
    elif systemctl list-units --type=service --all 2>/dev/null | grep -q '\bcrond\b'; then
        systemctl reload crond || true
    fi
fi

echo "Done. Verify with:  cat $DEST"
echo "First scheduled run: next weekday at 02:00 ${CRON_TZ:-America/Denver}."
