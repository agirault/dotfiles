#!/usr/bin/env bash
set -euo pipefail

echo "==> Installing system packages..."

arch=$(dpkg --print-architecture)
rel=$(. /etc/os-release && echo "$VERSION_CODENAME")

# -- Prerequisites for adding repos --

sudo apt-get update -qq
sudo apt-get install -y -qq gnupg software-properties-common

# -- Add source repositories --

sudo mkdir -p -m 755 /etc/apt/keyrings /etc/apt/sources.list.d

setup_apt_list() {
    local name=$1 repo=$2 rel_key_path=$3 rel_config=$4
    local source="/etc/apt/sources.list.d/$name.list"

    [[ -f "$source" ]] && return 0

    local gpg_path="/etc/apt/keyrings/$name.gpg"
    curl -fsSL "$repo/$rel_key_path" | sudo gpg --yes --dearmor -o "$gpg_path"
    sudo chmod go+r "$gpg_path"
    echo "deb [arch=$arch signed-by=$gpg_path] $repo/$rel_config" | \
        sudo tee "$source" > /dev/null
}

setup_apt_list "github-cli" "https://cli.github.com/packages" \
    "githubcli-archive-keyring.gpg" " stable main"
setup_apt_list "vscode" "https://packages.microsoft.com" \
    "keys/microsoft.asc" "repos/code stable main"
setup_apt_list "docker" "https://download.docker.com" \
    "linux/ubuntu/gpg" "linux/ubuntu $rel stable"

sudo apt-add-repository -n ppa:fish-shell/release-3 -y 2>/dev/null || true

sudo apt-get update -qq

# -- Install packages --

sudo apt-get install -y \
    fish vim stow fzf jq bc \
    tmux \
    tldr ripgrep fd-find sd tree lsd duf \
    wget curl unzip apt-transport-https openssh-server \
    lshw pciutils iperf3 ncdu htop \
    apt-rdepends \
    git-gui git-delta tig gh \
    build-essential libtool m4 automake \
    ca-certificates gnupg gnupg2 pass pinentry-tty

# snap packages
command -v glab >/dev/null 2>&1 || sudo snap install glab

# Script-installed tools
command -v dust >/dev/null 2>&1 || \
    (curl -sSfL https://raw.githubusercontent.com/bootandy/dust/refs/heads/master/install.sh | bash)
command -v curlie >/dev/null 2>&1 || \
    (curl -sSfL https://webinstall.dev/curlie | bash)

echo "==> Packages installed."
