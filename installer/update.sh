#!/usr/bin/env bash
# Install a MotionModule branch on this Pi, started from the dashboard.
#
# The dashboard runs this through sudo, which allows exactly two commands:
# this script followed by "main" or by "testing" (see
# /etc/sudoers.d/motionmodule-update). Nothing else is accepted here either.
#
# The install itself runs as the MotionModule user in its own transient
# service, so restarting MotionModule partway through the update does not kill
# the update. Its output goes to /var/log/motionmodule-update.log, which the
# dashboard shows while it works and after it reconnects.

set -Eeuo pipefail

UNIT="motionmodule-update"
LOG="/var/log/motionmodule-update.log"

fail() { printf '[MotionModule ERROR] %s\n' "$*" >&2; exit 2; }

REF="${1:-}"
[ "$#" -eq 1 ] || fail "Usage: motionmodule-update main|testing"
case "$REF" in
    main|testing) ;;
    *) fail "Unsupported update branch: $REF" ;;
esac

[ "$(id -u)" -eq 0 ] || fail "This helper is run by the dashboard through sudo."
OWNER="${SUDO_USER:-}"
[ -n "$OWNER" ] && [ "$OWNER" != "root" ] || fail "Run this as the MotionModule user through sudo."
HOME_DIR="$(getent passwd "$OWNER" | cut -d: -f6)"
[ -n "$HOME_DIR" ] || fail "No home directory for $OWNER."

if systemctl is-active --quiet "$UNIT.service"; then
    fail "An update is already running. Watch its progress on the dashboard."
fi
systemctl reset-failed "$UNIT.service" >/dev/null 2>&1 || true

# A fresh log per update, readable by the dashboard.
printf '[MotionModule] Updating to %s, started by %s at %s\n' "$REF" "$OWNER" "$(date -Is)" > "$LOG"
chmod 0644 "$LOG"

# --no-reboot: restarting the MotionModule service is enough, and a robot in
# the middle of a match should not disappear for a minute.
systemd-run \
    --unit="$UNIT" \
    --description="MotionModule update to $REF" \
    --uid="$OWNER" \
    --setenv=HOME="$HOME_DIR" \
    --property=StandardOutput=append:"$LOG" \
    --property=StandardError=append:"$LOG" \
    --property=TimeoutStartSec=infinity \
    /usr/local/bin/motionmodule install "$REF" --no-reboot >/dev/null

printf 'Started the update to %s. Progress is in %s\n' "$REF" "$LOG"
