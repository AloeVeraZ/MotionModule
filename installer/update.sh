#!/usr/bin/env bash
# Install a MotionModule branch on this Pi, started from the dashboard.
#
# The dashboard runs this through sudo, which allows exactly three commands:
# this script followed by "main", "testing" or "password" (see
# /etc/sudoers.d/motionmodule-update). Nothing else is accepted here either,
# apart from "forget", which only systemd runs, as root.
#
# The install itself runs as the MotionModule user in its own transient
# service, so restarting MotionModule partway through the update does not kill
# the update. Its output goes to /var/log/motionmodule-update.log, which the
# dashboard shows while it works and after it reconnects.
#
# The install runs sudo many times. When sudo asks that user for a password,
# the dashboard asks for it, checks it, and sends it here on stdin. It is kept
# in a root-only file for as long as that update runs. Each sudo in the install
# reads it through /usr/local/sbin/motionmodule-askpass, which calls this
# script with "password", and only processes inside the update get it.

set -Eeuo pipefail

UNIT="motionmodule-update"
LOG="/var/log/motionmodule-update.log"
ASKPASS="/usr/local/sbin/motionmodule-askpass"
# The install replaces this script partway through, and the newer copy then
# serves the password an older copy stored. Keep this path the same.
SECRET_DIR="/run/motionmodule-update"
SECRET="$SECRET_DIR/sudo-password"

fail() { printf '[MotionModule ERROR] %s\n' "$*" >&2; exit 2; }

REF="${1:-}"
[ "$#" -eq 1 ] || fail "Usage: motionmodule-update main|testing"
[ "$(id -u)" -eq 0 ] || fail "This helper is run by the dashboard through sudo."

case "$REF" in
    main|testing) ;;
    password)
        # sudo asking, through the askpass helper, for a command in the update.
        # Processes elsewhere, such as robot code, are refused.
        grep -Eq ":/system\.slice/$UNIT\.service\$" /proc/self/cgroup \
            || fail "Only the running update can ask for its password."
        [ -f "$SECRET" ] || fail "This update was started without a password."
        cat -- "$SECRET"
        exit 0
        ;;
    forget)
        # Started by systemd beside an update that has a password, never
        # through sudo: once that update ends, however it ends, delete it.
        while :; do
            case "$(systemctl show -p ActiveState --value "$UNIT.service" 2>/dev/null || true)" in
                active|activating|deactivating|reloading) sleep 5 ;;
                *) break ;;
            esac
        done
        rm -rf -- "$SECRET_DIR"
        exit 0
        ;;
    *) fail "Unsupported update branch: $REF" ;;
esac

OWNER="${SUDO_USER:-}"
[ -n "$OWNER" ] && [ "$OWNER" != "root" ] || fail "Run this as the MotionModule user through sudo."
HOME_DIR="$(getent passwd "$OWNER" | cut -d: -f6)"
[ -n "$HOME_DIR" ] || fail "No home directory for $OWNER."

# The dashboard sends the password on stdin, or nothing when sudo needs none.
# A person running this from a terminal is never asked for one.
PASSWORD=""
if [ ! -t 0 ]; then
    IFS= read -r -t 10 PASSWORD || true
fi

if systemctl is-active --quiet "$UNIT.service"; then
    fail "An update is already running. Watch its progress on the dashboard."
fi
systemctl reset-failed "$UNIT.service" >/dev/null 2>&1 || true

# Nothing is left of an earlier update: not its password, and not the wait
# to delete it, which could otherwise delete this update's.
systemctl stop "$UNIT-forget.service" >/dev/null 2>&1 || true
systemctl reset-failed "$UNIT-forget.service" >/dev/null 2>&1 || true
rm -rf -- "$SECRET_DIR"

password_options=()
if [ -n "$PASSWORD" ]; then
    (umask 077 && mkdir -- "$SECRET_DIR" && printf '%s\n' "$PASSWORD" > "$SECRET")
    # With no terminal, sudo reads its password from the SUDO_ASKPASS program
    # when DISPLAY is set. Nothing in the install opens a display, so it stays
    # empty.
    password_options=(--setenv=SUDO_ASKPASS="$ASKPASS" --setenv=DISPLAY=)
fi
PASSWORD=""

# A fresh log per update, readable by the dashboard.
printf '[MotionModule] Updating to %s, started by %s at %s\n' "$REF" "$OWNER" "$(date -Is)" > "$LOG"
chmod 0644 "$LOG"

# --no-reboot: restarting the MotionModule service is enough, and a robot in
# the middle of a match should not disappear for a minute.
if ! systemd-run \
    --unit="$UNIT" \
    --description="MotionModule update to $REF" \
    --uid="$OWNER" \
    --setenv=HOME="$HOME_DIR" \
    "${password_options[@]}" \
    --property=StandardOutput=append:"$LOG" \
    --property=StandardError=append:"$LOG" \
    --property=TimeoutStartSec=infinity \
    /usr/local/bin/motionmodule install "$REF" --no-reboot >/dev/null; then
    rm -rf -- "$SECRET_DIR"
    fail "Could not start the update."
fi

if [ -f "$SECRET" ]; then
    systemd-run \
        --unit="$UNIT-forget" \
        --description="Delete the password given to the MotionModule update" \
        /usr/local/sbin/motionmodule-update forget >/dev/null 2>&1 \
        || printf '[MotionModule] The update password is deleted at the next update or restart.\n' >> "$LOG"
fi

printf 'Started the update to %s. Progress is in %s\n' "$REF" "$LOG"
