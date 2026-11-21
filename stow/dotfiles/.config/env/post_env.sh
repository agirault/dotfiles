#!/bin/sh
# Post-env hook: runs after env.conf is loaded
# Must be POSIX-compatible (executed by bash from fish, sourced by bash)

# Skip when stdout isn't a terminal (scp, rsync, git-over-ssh, ...).
# Any output here corrupts the non-interactive protocol channel.
[ -t 1 ] || return 0 2>/dev/null || exit 0

# Show system info.
# --ds-force-drm only exists on Linux, where it reads the display list from
# sysfs instead of opening a DRM device. macOS rejects the option and prints
# an error, so pass it only on Linux.
if command -v fastfetch >/dev/null 2>&1; then
    case "$(uname -s)" in
    Linux) fastfetch --ds-force-drm sysfs-only ;;
    *) fastfetch ;;
    esac
fi
