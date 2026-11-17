#!/usr/bin/env bash
#
# Apply the macOS changes that need root. Every other setup script runs as
# your own user, so all privileged work is collected here. You then type your
# password once, and you can read this one file to see what runs as root.
#
# This script is safe to run again. Each step checks the current state first.
set -euo pipefail

if [[ "$(uname -s)" != Darwin ]]; then
    echo "==> macos-privileged.sh only applies to macOS."
    exit 0
fi

echo "==> Privileged macOS setup. Your password unlocks sudo for this script."
sudo -v

# Hold the sudo timestamp open until this script ends, so a slow step does not
# cause a second prompt. The loop stops when the script stops.
while true; do
    sudo -n true
    sleep 50
    kill -0 "$$" 2>/dev/null || exit
done 2>/dev/null &

# ---- Touch ID for sudo ----
#
# Apple reads /etc/pam.d/sudo_local and leaves it for you to write. Change
# that file, not /etc/pam.d/sudo, because a macOS update replaces sudo and
# would remove the setting without telling you.
echo "==> Touch ID for sudo"
pam_local=/etc/pam.d/sudo_local

if [[ ! -f "$pam_local" ]]; then
    sudo cp /etc/pam.d/sudo_local.template "$pam_local"
    echo "    Created $pam_local from Apple's template."
fi

if grep -qE '^auth\s+sufficient\s+pam_tid.so' "$pam_local"; then
    echo "    Touch ID already enabled."
else
    sudo sed -i '' 's/^#auth/auth/' "$pam_local"
    echo "    Enabled Touch ID."
fi

# Touch ID does not reach a tmux or screen session, because that session is
# detached from the window server and the prompt cannot appear. pam_reattach
# connects the session back, so the prompt works inside tmux.
#
# The module is "optional" on purpose. If Homebrew ever moves it, sudo still
# accepts your password instead of locking you out.
reattach="$(brew --prefix 2>/dev/null)/lib/pam/pam_reattach.so"

if [[ ! -f "$reattach" ]]; then
    echo "    pam_reattach not found. Install it with: brew install pam-reattach"
elif grep -q 'pam_reattach.so' "$pam_local"; then
    echo "    pam_reattach already configured."
else
    # pam_reattach must run before pam_tid, so insert it above that line.
    sudo sed -i '' "s|^auth\(.*\)pam_tid.so|auth       optional       $reattach\nauth\1pam_tid.so|" "$pam_local"
    echo "    Added pam_reattach, so Touch ID works inside tmux."
fi

# ---- Sleep settings for a machine you connect into ----
#
# A sleeping Mac stops answering the network, so an ssh session to it hangs.
# This is only useful on a machine you reach over ssh, so it is a question
# rather than a default.
echo "==> Power settings"
echo "    A sleeping Mac drops ssh connections to it."
read -r -p "    Stop this Mac sleeping while on power? [y/N] " answer

if [[ "$answer" =~ ^[Yy]$ ]]; then
    # -c means "while on power", so behaviour on battery does not change.
    sudo pmset -c sleep 0   # do not sleep
    sudo pmset -c womp 1    # wake when a network packet arrives
    echo "    Set. Check with 'pmset -g custom' later, because device"
    echo "    management can replace this with its own power policy."
else
    echo "    Skipped."
fi

echo "==> Privileged setup done."
