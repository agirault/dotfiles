#!/usr/bin/env bash
set -euo pipefail

# Set up the git identity and SSH commit signing.
#
# Name, email and the signing key go in ~/.gitconfig.local, which is
# gitignored. The shared ~/.gitconfig includes that file.
#
# Commits are signed with an SSH key, not a GPG key. The same key that
# authenticates to the git remote also signs the commits, so there is one key
# to protect and one key to move between machines.

echo "==> Setting up identity..."

local_config="$HOME/.gitconfig.local"
ssh_key="$HOME/.ssh/id_ed25519"
allowed_signers="$HOME/.config/git/allowed_signers"

case "$(uname -s)" in
    Darwin) OS=macos ;;
    *)      OS=linux ;;
esac

# Remove the write protection that a previous run applied, so this run can
# rewrite the file.
unlock_config() {
    [[ -f "$local_config" ]] || return 0
    if [[ "$OS" == macos ]]; then
        chflags nouchg "$local_config" 2>/dev/null || true
    elif command -v chattr >/dev/null 2>&1; then
        sudo chattr -i "$local_config" 2>/dev/null || true
    fi
    chmod u+w "$local_config" 2>/dev/null || true
}

# Protect the identity file. chmod 444 stops accidental writes. The immutable
# flag stops even the owner from writing without extra privilege, which limits
# the damage a compromised sandboxed agent can do.
lock_config() {
    chmod 444 "$local_config"
    if [[ "$OS" == macos ]]; then
        chflags uchg "$local_config"
        echo "    $local_config locked. To edit: chflags nouchg '$local_config' && chmod u+w '$local_config'"
    elif command -v chattr >/dev/null 2>&1; then
        if sudo chattr +i "$local_config" 2>/dev/null; then
            echo "    $local_config locked. To edit: sudo chattr -i '$local_config' && chmod u+w '$local_config'"
        else
            echo "    note: chmod 444 applied, but the immutable flag needs sudo"
        fi
    fi
}

# ---- Existing identity ----

if [[ -f "$local_config" ]]; then
    echo "    Existing identity found:"
    echo "      Name:  $(git config --file "$local_config" user.name 2>/dev/null || echo '(not set)')"
    echo "      Email: $(git config --file "$local_config" user.email 2>/dev/null || echo '(not set)')"
    read -r -p "    Reconfigure? [y/N] " reconfigure
    if [[ ! "$reconfigure" =~ ^[yY] ]]; then
        echo "    Keeping existing identity."
        echo "==> Identity configured."
        exit 0
    fi
fi

read -r -p "[Git] Full Name: " fullname
read -r -p "[Git] Email: " email

# ---- SSH key ----

if [[ ! -f "$ssh_key" ]]; then
    echo "    No SSH key at $ssh_key."
    read -r -p "    Generate one? [Y/n] " gen_key
    if [[ ! "$gen_key" =~ ^[nN] ]]; then
        ssh-keygen -t ed25519 -C "$email" -f "$ssh_key"
    fi
fi

if [[ ! -f "${ssh_key}.pub" ]]; then
    echo "    WARNING: no SSH key, so commit signing is not configured."
    unlock_config
    cat > "$local_config" <<EOF
[user]
    name = $fullname
    email = $email
EOF
    lock_config
    echo "==> Identity configured (without signing)."
    exit 0
fi

# ---- Write the identity file ----

unlock_config
cat > "$local_config" <<EOF
[user]
    name = $fullname
    email = $email
    signingkey = ${ssh_key}.pub
EOF
lock_config

# ---- Allowed signers ----

# Git verifies a signature by looking the key up in this file. Without it,
# `git log --show-signature` reports the commit as unverified even though the
# signature is good.
mkdir -p "$(dirname "$allowed_signers")"
entry="$email namespaces=\"git\" $(cat "${ssh_key}.pub")"
if [[ -f "$allowed_signers" ]] && grep -qF "$(cut -d' ' -f1,2 < "${ssh_key}.pub")" "$allowed_signers"; then
    echo "    Signing key already in $allowed_signers."
else
    echo "$entry" >> "$allowed_signers"
    echo "    Added signing key to $allowed_signers."
fi

# ---- SSH agent ----

# On macOS, ask ssh to load the key from the login Keychain so the passphrase
# is typed once, not on every signed commit.
if [[ "$OS" == macos ]]; then
    # Do not write to ~/.ssh/config here. That path is a symlink into this
    # repository, so an append would change the committed file and add a
    # second "Host *" block. The shared config already sets AddKeysToAgent
    # and UseKeychain. Only load the key, which puts the passphrase in the
    # Keychain now instead of at the next connection.
    ssh-add --apple-use-keychain "$ssh_key" 2>/dev/null || true
fi

# ---- GitLab CLI ----

if command -v glab >/dev/null 2>&1; then
    read -r -p "[glab] Default GitLab hostname (leave empty to skip): " gitlab_host
    if [[ -n "$gitlab_host" ]]; then
        glab config set host "$gitlab_host"
        echo "    glab: default host set to $gitlab_host."
    fi
fi

# ---- Reminder ----

cat <<EOF

    Add this key to GitHub TWICE: once as an Authentication key, and once as a
    Signing key. GitHub treats them as separate entries.

$(cat "${ssh_key}.pub")

EOF

echo "==> Identity configured."
