#!/usr/bin/env bash
set -euo pipefail

# Install packages and applications on macOS via Homebrew.

if [[ "$(uname -s)" != Darwin ]]; then
    echo "ERROR: packages-macos.sh must run on macOS."
    exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
    echo "==> Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
fi

if ! command -v brew >/dev/null 2>&1; then
    echo "ERROR: Homebrew not available after install."
    exit 1
fi

echo "==> Installing macOS formulae and casks..."
brew bundle --file="$(cd "$(dirname "$0")" && pwd)/Brewfile"

# Claude CLI is not in Homebrew. Install the official installer if missing.
if ! command -v claude >/dev/null 2>&1; then
    echo "==> Installing Claude CLI..."
    curl -fsSL https://claude.ai/install.sh | bash
else
    echo "==> Claude CLI already installed."
fi

# Codex is not in Homebrew either. The repo stows ~/.codex/config.toml, so the
# Linux setup installs it too. Keep the two platforms in step.
if ! command -v codex >/dev/null 2>&1; then
    echo "==> Installing Codex CLI..."
    npm install -g @openai/codex
else
    echo "==> Codex CLI already installed."
fi

echo "==> macOS packages installed."
