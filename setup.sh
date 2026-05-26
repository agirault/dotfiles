#!/usr/bin/env bash
set -euo pipefail

# System setup: packages, dotfiles, tools, and identity
# Usage:
#   ./setup.sh              # run all phases
#   ./setup.sh packages     # install system packages only
#   ./setup.sh configs      # symlink dotfiles and tools via stow
#   ./setup.sh identity     # set up git identity + GPG only
#   ./setup.sh unlink       # remove symlinks and restore backups
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
STOW_DIR="$DOTFILES_DIR/stow"
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

# ---- Helpers ----

# List all stow package names
stow_packages() {
    find "$STOW_DIR" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort
}

# List target file paths for a stow package (relative to ~)
stow_targets() {
    (cd "$STOW_DIR/$1" && find . -type f | sed 's|^\./||')
}

# ---- Phase: packages ----
phase_packages() {
    bash "$SETUP_DIR/packages.sh"
    bash "$SETUP_DIR/sandbox.sh"
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
        echo "Run './setup.sh packages' first."
        exit 1
    fi

    echo "==> Setting up configs..."

    for pkg in $(stow_packages); do
        # Back up existing files that would conflict with stow
        for target in $(stow_targets "$pkg"); do
            local full="$HOME/$target"
            # Skip symlinks (already stowed)
            if [[ -e "$full" && ! -L "$full" ]]; then
                real_path=$(readlink -f "$full")
                # Skip files inside the repo (tree folding)
                if [[ "$real_path" != "$DOTFILES_DIR"/* ]]; then
                    echo "    Backing up $full -> ${full}.bak"
                    mv "$full" "${full}.bak"
                fi
            fi
        done

        # Stow the package
        stow -d "$STOW_DIR" -t "$HOME" --restow "$pkg"
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

    bash "$SETUP_DIR/tmux-plugins.sh"

    echo "==> Configs set up."
}

# ---- Phase: identity ----
phase_identity() {
    bash "$SETUP_DIR/identity.sh"
}

# ---- Phase: unlink ----
phase_unlink() {
    echo "==> Unlinking dotfiles and tools..."

    for pkg in $(stow_packages); do
        # Unstow the package
        stow -d "$STOW_DIR" -t "$HOME" -D "$pkg" 2>/dev/null || true
        echo "    Unstowed $pkg"

        # Restore .bak files from first-time install
        for target in $(stow_targets "$pkg"); do
            local full="$HOME/$target"
            if [[ -f "${full}.bak" ]]; then
                mv "${full}.bak" "$full"
                echo "    Restored $full"
            fi
        done
    done

    echo "==> Unlinked."
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
    unlink)
        phase_unlink
        ;;
    *)
        echo "Usage: $0 [packages|configs|identity|unlink]"
        exit 1
        ;;
esac

echo ""
echo "Done! You may need to restart your shell for all changes to take effect."
