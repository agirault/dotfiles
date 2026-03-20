#!/usr/bin/env bash
set -euo pipefail

# Dotfiles installer
# Usage:
#   ./install.sh              # run all phases
#   ./install.sh packages     # install system packages only
#   ./install.sh configs      # stow configs only
#   ./install.sh identity     # set up git identity + GPG only
#   ./install.sh uninstall    # remove symlinks and restore backups
#
# Flags:
#   --no-docker     skip Docker setup (e.g., when running inside a container)
#   --no-identity   skip identity setup (e.g., non-interactive environments)

if [[ $EUID -eq 0 ]]; then
    echo "This script must not be run as root."
    exit 1
fi

DOTFILES_DIR="$(cd "$(dirname "$0")" && pwd)"
SETUP_DIR="$DOTFILES_DIR/setup"
NO_DOCKER=false
NO_IDENTITY=false

# Parse flags
args=()
for arg in "$@"; do
    case "$arg" in
        --no-docker) NO_DOCKER=true ;;
        --no-identity) NO_IDENTITY=true ;;
        *) args+=("$arg") ;;
    esac
done
set -- "${args[@]+"${args[@]}"}"

# ---- Phase: packages ----
phase_packages() {
    bash "$SETUP_DIR/packages.sh"
    bash "$SETUP_DIR/fisher-plugins.sh"
    if [[ "$NO_DOCKER" == true ]]; then
        echo "==> Skipping Docker setup (--no-docker)."
    else
        bash "$SETUP_DIR/docker.sh"
    fi

    # Claude CLI
    if ! command -v claude >/dev/null 2>&1; then
        echo "==> Installing Claude CLI..."
        curl -fsSL https://claude.ai/install.sh | bash
    else
        echo "==> Claude CLI already installed."
    fi
}

# ---- Phase: configs ----
phase_configs() {
    # Check dependencies
    local missing=()
    for cmd in stow fish; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "ERROR: Missing required commands: ${missing[*]}"
        echo "Run './install.sh packages' first."
        exit 1
    fi

    echo "==> Stowing configs..."

    cd "$DOTFILES_DIR"

    stow_packages=(git fish tmux claude bash env)

    for pkg in "${stow_packages[@]}"; do
        if [[ ! -d "$DOTFILES_DIR/stow/$pkg" ]]; then
            echo "    Skipping $pkg (directory not found)"
            continue
        fi

        # Back up existing non-symlink files that would conflict
        while IFS= read -r target; do
            target="$HOME/$target"
            if [[ -e "$target" && ! -L "$target" ]]; then
                echo "    Backing up $target -> ${target}.bak"
                mv "$target" "${target}.bak"
            fi
        done < <(cd "$DOTFILES_DIR/stow/$pkg" && find . -type f | sed 's|^\./||')

        stow -d "$DOTFILES_DIR/stow" -t "$HOME" --restow "$pkg"
        echo "    Stowed $pkg"
    done

    # Integrate .bashrc.d sourcing into .bashrc
    bashrc="$HOME/.bashrc"
    marker="# Source dotfiles customizations"
    if [[ -f "$bashrc" ]] && ! grep -qF "$marker" "$bashrc"; then
        cat >> "$bashrc" <<'BASH'

# Source dotfiles customizations
for f in ~/.bashrc.d/*.sh; do [ -r "$f" ] && . "$f"; done
BASH
        echo "    Added .bashrc.d sourcing to ~/.bashrc"
    fi

    # Clean up stale ~/AGENTS.md if CLAUDE.md is now a symlink
    if [[ -L "$HOME/.claude/CLAUDE.md" && -f "$HOME/AGENTS.md" ]]; then
        rm "$HOME/AGENTS.md"
        echo "    Removed stale ~/AGENTS.md (now at ~/.claude/CLAUDE.md)"
    fi

    echo "==> Configs stowed."
}

# ---- Phase: identity ----
phase_identity() {
    bash "$SETUP_DIR/identity.sh"
}

# ---- Phase: uninstall ----
phase_uninstall() {
    echo "==> Unstowing configs..."

    cd "$DOTFILES_DIR"

    stow_packages=(git fish tmux claude bash env)

    for pkg in "${stow_packages[@]}"; do
        if [[ ! -d "$DOTFILES_DIR/stow/$pkg" ]]; then
            continue
        fi

        stow -d "$DOTFILES_DIR/stow" -t "$HOME" -D "$pkg" 2>/dev/null || true
        echo "    Unstowed $pkg"

        # Restore .bak files
        while IFS= read -r target; do
            target="$HOME/$target"
            if [[ -f "${target}.bak" ]]; then
                mv "${target}.bak" "$target"
                echo "    Restored $target"
            fi
        done < <(cd "$DOTFILES_DIR/stow/$pkg" && find . -type f | sed 's|^\./||')
    done

    echo "==> Configs restored."
}

# ---- Main ----

phase="${1:-all}"

case "$phase" in
    packages)
        phase_packages
        ;;
    configs)
        phase_configs
        ;;
    identity)
        phase_identity
        ;;
    all)
        phase_packages
        phase_configs
        if [[ "$NO_IDENTITY" == true ]]; then
            echo "==> Skipping identity setup (--no-identity)."
        else
            phase_identity
        fi
        ;;
    uninstall)
        phase_uninstall
        ;;
    *)
        echo "Usage: $0 [packages|configs|identity|uninstall]"
        exit 1
        ;;
esac

echo ""
echo "Done! You may need to restart your shell for all changes to take effect."
