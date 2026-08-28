#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${MOTIONMODULE_REPO_URL:-https://github.com/AloeVeraZ/MotionModule.git}"
REF="${MOTIONMODULE_VERSION:-main}"

args=("$@")
for ((index = 0; index < ${#args[@]}; index++)); do
    if [ "${args[$index]}" = "--version" ] && [ $((index + 1)) -lt ${#args[@]} ]; then
        REF="${args[$((index + 1))]}"
    fi
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
if [ -n "$script_dir" ] && [ -f "$script_dir/installer/install.sh" ] && [ -f "$script_dir/pyproject.toml" ]; then
    exec bash "$script_dir/installer/install.sh" --source "$script_dir" "$@"
fi

temporary="$(mktemp -d)"
cleanup() { rm -rf -- "$temporary"; }
trap cleanup EXIT

printf '\n[MotionModule] Downloading version %s...\n' "$REF"
if ! command -v git >/dev/null 2>&1; then
    command -v sudo >/dev/null 2>&1 || { printf '[MotionModule ERROR] sudo is required to install Git.\n' >&2; exit 1; }
    sudo env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=60 update
    sudo env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=60 install -y git ca-certificates
fi
git clone --filter=blob:none --no-checkout "$REPO_URL" "$temporary/source"
git -C "$temporary/source" fetch --depth=1 origin "$REF"
git -C "$temporary/source" checkout --detach FETCH_HEAD
bash "$temporary/source/installer/install.sh" --source "$temporary/source" "$@"
