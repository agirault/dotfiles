#!/usr/bin/env bash
set -euo pipefail

echo "==> Setting up Docker..."

arch=$(dpkg --print-architecture)

# Install Docker if needed
if ! command -v docker >/dev/null 2>&1; then
    sudo apt-get install -y \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
fi
if ! docker buildx version &>/dev/null; then
    sudo apt-get install -y docker-buildx
fi

# Add user to docker group
sudo groupadd docker 2>/dev/null || true
if ! groups "$USER" | grep -q docker; then
    sudo usermod -aG docker "$USER"
    echo "    Added $USER to docker group (re-login required for effect)."
fi

# Install docker-credential-pass
if ! command -v docker-credential-pass >/dev/null 2>&1; then
    local_version="v0.8.0"
    local_url="https://github.com/docker/docker-credential-helpers/releases/download/$local_version/docker-credential-pass-$local_version.linux-$arch"
    local_path="/usr/local/bin/docker-credential-pass"
    sudo wget -q "$local_url" -O "$local_path"
    sudo chown "$USER" "$local_path"
    sudo chmod u+x "$local_path"
fi

# Configure docker to use credential store
docker_config="$HOME/.docker/config.json"
mkdir -p "$(dirname "$docker_config")"
if [[ -f "$docker_config" ]]; then
    if ! grep -qF '"credsStore": "pass"' "$docker_config"; then
        sed -i '0,/{/s|{|{\n\t"credsStore": "pass",|' "$docker_config"
    fi
else
    printf '{\n\t"credsStore": "pass"\n}\n' > "$docker_config"
fi

# Set up pinentry for TTY
sudo update-alternatives --set pinentry "$(which pinentry-tty)" 2>/dev/null || true

echo "==> Docker configured."
