#!/bin/sh
# Post-env hook: runs after env.conf is loaded
# Must be POSIX-compatible (executed by bash from fish, sourced by bash)

# Show system info
command -v fastfetch >/dev/null 2>&1 && fastfetch
