# shellcheck shell=bash
# Sourced by install.sh: decides what an install leaves behind.
#
# Installing MotionModule replaces the MotionModule software on the Pi. That is
# what lets a robot move between the main and testing branches, or to any tag
# or commit, in either direction without files from one mixing with the other.
#
# Nothing here touches the robot's own files: robot projects and their backups
# in ~/MotionModule, the active-project link, the pin names in
# ~/.config/motionmodule/hardware.py, and the Wi-Fi and hotspot settings.

# Print the branch, tag, or commit a release was installed from.
release_ref() {
    local ref=""
    if [ -f "$1/INSTALL_REF" ]; then
        ref="$(head -n 1 "$1/INSTALL_REF" 2>/dev/null || true)"
    fi
    printf '%s' "$ref"
    return 0
}

# Print the release an install keeps for an offline `motionmodule rollback`:
# the one that was active before it, but only when it was installed from the
# same branch, tag, or commit. A release from any other line is never kept.
rollback_candidate() {
    local previous="$1" ref="$2"
    if [ -n "$previous" ] && [ -f "$previous/.complete" ] && [ "$(release_ref "$previous")" = "$ref" ]; then
        printf '%s' "$previous"
    fi
    return 0
}

# Delete every release in RELEASES_DIR except the paths listed after it, and
# print the name of each one removed. Empty arguments are ignored. Nothing that
# resolves outside RELEASES_DIR is deleted.
remove_other_releases() {
    local releases_dir="$1" root release resolved keep
    shift
    [ -d "$releases_dir" ] || return 0
    root="$(readlink -f "$releases_dir")"
    for release in "$releases_dir"/* "$releases_dir"/.[!.]*; do
        [ -e "$release" ] || [ -L "$release" ] || continue
        resolved="$(readlink -f "$release" 2>/dev/null || true)"
        for keep in "$@"; do
            [ -n "$keep" ] || continue
            [ "$resolved" = "$(readlink -f "$keep" 2>/dev/null || true)" ] && continue 2
        done
        case "$resolved" in
            "$root"/*) ;;
            *) continue ;;
        esac
        rm -rf -- "$release"
        printf '%s\n' "${release##*/}"
    done
    return 0
}

# Read candidate paths on stdin and print the ones not listed as arguments.
# install.sh feeds it every MotionModule system file on the Pi and lists the
# ones it has just written; whatever is printed came from an older install and
# is removed, so a file one branch installs never lingers after switching to a
# branch that does not ship it.
unlisted_paths() {
    local candidate installed
    while IFS= read -r candidate; do
        [ -n "$candidate" ] || continue
        for installed in "$@"; do
            [ "$candidate" = "$installed" ] && continue 2
        done
        printf '%s\n' "$candidate"
    done
    return 0
}
