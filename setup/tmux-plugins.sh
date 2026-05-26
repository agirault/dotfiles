#!/usr/bin/env bash
set -euo pipefail

echo "==> Installing tmux plugins..."

tpm_dir="$HOME/.tmux/plugins/tpm"
tpm_parent="$HOME/.tmux/plugins"
bootstrap_session=""

tmux_default_socket() {
    local socket_dir="${TMUX_TMPDIR:-/tmp}/tmux-$(id -u)"
    echo "$socket_dir/default"
}

remove_stale_default_socket() {
    local output
    if output=$(tmux has-session 2>&1); then
        return 0
    fi

    if [[ "$output" == *"server exited unexpectedly"* ]]; then
        rm -f "$(tmux_default_socket)"
    fi
}

cleanup() {
    if [[ -n "$bootstrap_session" ]]; then
        tmux kill-session -t "$bootstrap_session" 2>/dev/null || true
    fi
}
trap cleanup EXIT

if [[ ! -d "$tpm_dir/.git" ]]; then
    mkdir -p "$tpm_parent"
    git clone --depth 1 https://github.com/tmux-plugins/tpm "$tpm_dir"
else
    echo "    TPM already installed."
fi

remove_stale_default_socket

if ! tmux has-session >/dev/null 2>&1; then
    bootstrap_session="tpm-bootstrap-$$"
    tmux -f /dev/null new-session -d -s "$bootstrap_session" sleep 300
fi

tmux set-environment -g TMUX_PLUGIN_MANAGER_PATH "$tpm_parent/"
tmux source-file "$HOME/.tmux.conf" >/dev/null 2>&1 || true

if [[ -x "$tpm_dir/bin/install_plugins" ]]; then
    "$tpm_dir/bin/install_plugins"
else
    echo "ERROR: TPM installer not found at $tpm_dir/bin/install_plugins" >&2
    exit 1
fi

echo "==> Tmux plugins installed."
