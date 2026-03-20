if status is-interactive
    # Fix SSH agent forwarding for tmux: keep a stable symlink
    # so reconnected SSH sessions update the agent socket for existing tmux sessions
    if set -q SSH_AUTH_SOCK; and test "$SSH_AUTH_SOCK" != "$HOME/.ssh/ssh_auth_sock"
        ln -sf "$SSH_AUTH_SOCK" "$HOME/.ssh/ssh_auth_sock"
    end
end
