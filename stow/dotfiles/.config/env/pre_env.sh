#!/bin/sh
# Pre-env hook: runs before env.conf is loaded
# Must be POSIX-compatible (executed by bash from fish, sourced by bash)

# Update SSH agent symlink to a live real socket
command -v ssh-refresh-agent >/dev/null 2>&1 && ssh-refresh-agent >/dev/null
