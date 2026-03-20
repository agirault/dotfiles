#!/bin/sh
# Runs on interactive shell startup (executed by both fish and bash)
# Fish runs this as a subprocess (bash login.sh), bash sources it (. login.sh)
# Only use for side-effects (files, output) - env changes won't persist in fish

# SSH agent forwarding fix for tmux: keep a stable symlink
# so reconnected SSH sessions update the agent socket for existing tmux sessions
if [ -n "$SSH_AUTH_SOCK" ] && [ "$SSH_AUTH_SOCK" != "$HOME/.ssh/ssh_auth_sock" ]; then
    ln -sf "$SSH_AUTH_SOCK" "$HOME/.ssh/ssh_auth_sock"
fi

# Show system info
command -v fastfetch >/dev/null 2>&1 && fastfetch
