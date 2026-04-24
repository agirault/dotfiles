#!/usr/bin/env bash
# Validate system setup
set -euo pipefail

PASS=0
FAIL=0

check() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        echo "  PASS: $desc"
        ((PASS++))
    else
        echo "  FAIL: $desc"
        ((FAIL++))
    fi
}

phase="${1:-configs}"

if [[ "$phase" == "configs" ]]; then
    echo "== Validating configs =="

    # Symlinks exist
    echo "-- Symlinks --"
    check ".gitconfig is a symlink" test -L "$HOME/.gitconfig"
    check ".tmux.conf is a symlink" test -L "$HOME/.tmux.conf"
    check ".config/fish/config.fish is a symlink" test -L "$HOME/.config/fish/config.fish"
    check ".config/fish/conf.d/env_loader.fish is a symlink" test -L "$HOME/.config/fish/conf.d/env_loader.fish"
    check ".claude/settings.json is a symlink" test -L "$HOME/.claude/settings.json"
    check ".claude/CLAUDE.md is a symlink" test -L "$HOME/.claude/CLAUDE.md"
    check ".claude/executable_statusline.sh is a symlink" test -L "$HOME/.claude/executable_statusline.sh"
    check ".bashrc.d/00-env-loader.sh is a symlink" test -L "$HOME/.bashrc.d/00-env-loader.sh"
    check ".config/env/env.conf is a symlink" test -L "$HOME/.config/env/env.conf"
    check ".config/env/pre_env.sh is a symlink" test -L "$HOME/.config/env/pre_env.sh"
    check ".config/env/post_env.sh is a symlink" test -L "$HOME/.config/env/post_env.sh"
    check ".local/bin/tm is a symlink" test -L "$HOME/.local/bin/tm"
    check ".local/bin/ssh-refresh-agent is a symlink" test -L "$HOME/.local/bin/ssh-refresh-agent"

    # Backups created for pre-existing files
    echo "-- Backups --"
    check ".gitconfig.bak exists" test -f "$HOME/.gitconfig.bak"
    check ".tmux.conf.bak exists" test -f "$HOME/.tmux.conf.bak"
    check ".config/fish/config.fish.bak exists" test -f "$HOME/.config/fish/config.fish.bak"
    check ".claude/settings.json.bak exists" test -f "$HOME/.claude/settings.json.bak"

    # Content checks
    echo "-- Content --"
    check ".gitconfig has [include] for .local" grep -q 'path = ~/.gitconfig.local' "$HOME/.gitconfig"
    check ".gitconfig has NO [user] section" ! grep -q '^\[user\]' "$HOME/.gitconfig"
    check ".claude/settings.json uses ~ not /home/" ! grep -q '/home/' "$HOME/.claude/settings.json"
    check ".bashrc sources .bashrc.d" grep -q 'bashrc.d' "$HOME/.bashrc"
    check "tm is executable" test -x "$HOME/.local/bin/tm"

    # Commands available
    echo "-- Commands --"
    check "stow is installed" command -v stow
    check "fish is installed" command -v fish
    check "tmux is installed" command -v tmux
    check "fzf is installed" command -v fzf
    check "git is installed" command -v git

    # Syntax checks
    echo "-- Syntax --"
    check "env_loader.fish has no syntax errors" fish -n "$HOME/.config/fish/conf.d/env_loader.fish"
    check "00-env-loader.sh has no syntax errors" bash -n "$HOME/.bashrc.d/00-env-loader.sh"

elif [[ "$phase" == "unlink" ]]; then
    echo "== Validating unlink =="

    # Symlinks should be gone
    echo "-- Symlinks removed --"
    check ".gitconfig is NOT a symlink" ! test -L "$HOME/.gitconfig"
    check ".tmux.conf is NOT a symlink" ! test -L "$HOME/.tmux.conf"
    check ".config/fish/config.fish is NOT a symlink" ! test -L "$HOME/.config/fish/config.fish"
    check ".claude/settings.json is NOT a symlink" ! test -L "$HOME/.claude/settings.json"

    # Originals should be restored
    echo "-- Originals restored --"
    check ".gitconfig restored" test -f "$HOME/.gitconfig"
    check ".tmux.conf restored" test -f "$HOME/.tmux.conf"
    check ".config/fish/config.fish restored" test -f "$HOME/.config/fish/config.fish"
    check ".claude/settings.json restored" test -f "$HOME/.claude/settings.json"

    # .bak files should be gone (renamed back)
    echo "-- Backups cleaned up --"
    check ".gitconfig.bak gone" ! test -f "$HOME/.gitconfig.bak"
    check ".tmux.conf.bak gone" ! test -f "$HOME/.tmux.conf.bak"

    # Restored content should be the original
    echo "-- Content --"
    check ".gitconfig has original content" grep -q 'Old Name' "$HOME/.gitconfig"
    check ".claude/settings.json has original content" grep -q '"old"' "$HOME/.claude/settings.json"
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]] || exit 1
