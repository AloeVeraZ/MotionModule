#!/usr/bin/env bash
set -Eeuo pipefail

[ "$(id -u)" -eq 0 ] || { printf 'Run through: motionmodule hotspot ...\n' >&2; exit 1; }
HELPER="/usr/local/sbin/motionmodule-network"
[ -x "$HELPER" ] || { printf 'The MotionModule network helper is not installed.\n' >&2; exit 1; }
action="${1:-status}"

case "$action" in
    on)
        if [ "$#" -eq 1 ]; then
            printf '{}\n' | "$HELPER" hotspot
        elif [ "$#" -eq 2 ]; then
            python3 -c 'import json,sys; print(json.dumps({"ssid": sys.argv[1]}))' "$2" | "$HELPER" hotspot
        elif [ "$#" -eq 3 ]; then
            python3 -c 'import json,sys; print(json.dumps({"ssid": sys.argv[1], "password": sys.argv[2]}))' "$2" "$3" | "$HELPER" hotspot
        else
            printf 'Usage: motionmodule hotspot on [SSID] [PASSWORD]\n' >&2
            exit 2
        fi
        ;;
    off)
        "$HELPER" preferred
        ;;
    status)
        "$HELPER" status
        ;;
    *)
        printf 'Usage: motionmodule hotspot on [SSID] [PASSWORD] | off | status\n' >&2
        exit 2
        ;;
esac
