#!/usr/bin/env bash
set -euo pipefail

echo "==> Setting up identity..."

local_config="$HOME/.gitconfig.local"

# Check existing identity
if [[ -f "$local_config" ]]; then
    echo "    Existing identity found:"
    echo "      Name:  $(git config --file "$local_config" user.name 2>/dev/null || echo '(not set)')"
    echo "      Email: $(git config --file "$local_config" user.email 2>/dev/null || echo '(not set)')"
    read -p "    Reconfigure? [y/N] " reconfigure
    if [[ ! "$reconfigure" =~ ^[yY] ]]; then
        echo "    Keeping existing identity."
        echo "==> Identity configured."
        return 0 2>/dev/null || exit 0
    fi
fi

# Prompt for identity
read -p "[Git] Full Name: " fullname
read -p "[Git] Email: " email

# Write .gitconfig.local
cat > "$local_config" <<EOF
[user]
    name = $fullname
    email = $email
[commit]
    gpgsign = true
EOF

# GPG key setup
export GPG_TTY=$(tty)
gpgconf --kill gpg-agent 2>/dev/null || true

gpg_id_regex='^\s*\K[[:alnum:]]+$'
gpg_id=$(gpg2 --list-keys 2>/dev/null | grep -oP "$gpg_id_regex" || true)

if [[ -z "$gpg_id" ]]; then
    read -p "    No GPG key found. Generate one? [Y/n] " gen_gpg
    if [[ ! "$gen_gpg" =~ ^[nN] ]]; then
        gpg2 --batch --generate-key <<EOF
%echo Generating GPG key
Key-Type: EDDSA
Key-Curve: Ed25519
Subkey-Type: ECDH
Subkey-Curve: Curve25519
Name-Real: $fullname
Name-Email: $email
Expire-Date: 0
%commit
%echo done
EOF
        gpg_id=$(gpg2 --list-keys | grep -oP "$gpg_id_regex")
        echo "    GPG key generated: $gpg_id"
        echo ""
        echo "    Add this public key to GitHub:"
        gpg2 --armor --export "$gpg_id"
        echo ""
    fi
fi

# Set signing key if we have one
if [[ -n "$gpg_id" ]]; then
    git config --file "$local_config" user.signingkey "$gpg_id"

    # Initialize pass
    if ! pass ls >/dev/null 2>&1; then
        pass init "$gpg_id"
    fi
fi

# Set up git-lfs
git lfs install 2>/dev/null || true

echo "==> Identity configured."
