#!/bin/sh
# Post-env hook: runs after env.conf is loaded
# Must be POSIX-compatible (executed by bash from fish, sourced by bash)

# Skip when stdout isn't a terminal (scp, rsync, git-over-ssh, ...).
# Any output here corrupts the non-interactive protocol channel.
[ -t 1 ] || return 0 2>/dev/null || exit 0

# Show system info
command -v fastfetch >/dev/null 2>&1 && fastfetch --ds-force-drm sysfs-only
