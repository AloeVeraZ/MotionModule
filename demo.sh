#!/usr/bin/env bash
# MotionModule demo: the robot dashboard on this computer, with a simulated robot.
#
# Paste into a macOS or Linux terminal:
#
#   curl -fsSL https://raw.githubusercontent.com/AloeVeraZ/MotionModule/testing/demo.sh | bash
#
# It downloads MotionModule, sets up Python for it, and opens the dashboard in
# your browser. No Raspberry Pi is needed and nothing on the computer is
# changed outside its own folder. Run it again to get the latest version; if
# there is no internet, it reuses the last download.
#
# Inside a clone of the repository, run ./demo.sh instead. That copy is used as
# it is, so changes to the dashboard show up the next time the demo starts.
#
# Optional settings, as environment variables:
#   MOTIONMODULE_DEMO_BRANCH   branch to download (default: testing)
#   MOTIONMODULE_DEMO_PORT     first port to try (default: 8080)
#   MOTIONMODULE_DEMO_HOST     0.0.0.0 to open it from a phone on the same Wi-Fi
#   MOTIONMODULE_DEMO_HOME     folder for the download and Python environment
#                              (default: ~/.local/share/motionmodule-demo)
set -euo pipefail

BRANCH="${MOTIONMODULE_DEMO_BRANCH:-testing}"
PORT="${MOTIONMODULE_DEMO_PORT:-8080}"
BIND_HOST="${MOTIONMODULE_DEMO_HOST:-127.0.0.1}"
DATA="${MOTIONMODULE_DEMO_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/motionmodule-demo}"

say() { printf '\033[1;36m[MotionModule demo]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[MotionModule demo]\033[0m %s\n' "$*" >&2; exit 1; }

mkdir -p "$DATA"

# ---- the MotionModule files: this clone, or a fresh download ---------------
script_dir=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [ -n "$script_dir" ] && [ -f "$script_dir/core/motion_module/demo.py" ]; then
    source_dir="$script_dir"
    say "Using this copy of MotionModule: $source_dir"
else
    source_dir="$DATA/source-${BRANCH//[^A-Za-z0-9._-]/-}"
    staging="$(mktemp -d "$DATA/staging.XXXXXX")"
    say "Downloading the $BRANCH branch of MotionModule..."
    if curl -fsSL "https://codeload.github.com/AloeVeraZ/MotionModule/tar.gz/refs/heads/$BRANCH" \
            | tar -xz -C "$staging" --strip-components=1 \
        && [ -f "$staging/core/motion_module/demo.py" ]; then
        rm -rf "$source_dir"
        mv "$staging" "$source_dir"
    elif [ -f "$source_dir/core/motion_module/demo.py" ]; then
        rm -rf "$staging"
        say "Could not download $BRANCH. Using the copy from last time."
    else
        rm -rf "$staging"
        fail "Could not download the $BRANCH branch, or it does not include the demo. Check the internet connection."
    fi
fi

# ---- Python 3.11 or newer --------------------------------------------------
python=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
        && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
        python="$(command -v "$candidate")"
        break
    fi
done
[ -n "$python" ] || fail "Python 3.11 or newer is needed. macOS: brew install python@3.12. Ubuntu or Debian: sudo apt install python3 python3-venv. Then run this again."

venv="$DATA/venv"
if [ ! -x "$venv/bin/python" ]; then
    say "Setting up Python for the demo (first run only)..."
    "$python" -m venv "$venv" || fail "Could not create a Python environment. On Ubuntu or Debian: sudo apt install python3-venv"
fi
say "Checking Flask and the other requirements..."
"$venv/bin/python" -m pip install --disable-pip-version-check --quiet -r "$source_dir/requirements.txt" \
    || fail "Could not install the requirements. Check the internet connection and try again."

# ---- run it ------------------------------------------------------------------
say "Starting the dashboard with a simulated robot. Press Ctrl+C to stop."
PYTHONPATH="$source_dir/core" exec "$venv/bin/python" -m motion_module.demo --host "$BIND_HOST" --port "$PORT"
