#!/usr/bin/env bash
set -euo pipefail

# Sets up bwrap (bubblewrap) sandbox for Claude Code on Ubuntu 24.04+ with
# kernel 6.17+, where AppArmor restricts unprivileged user namespaces by default.
#
# Without the AppArmor profile, bwrap fails with errors like:
#   bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
#   bwrap: setting up uid map: Permission denied
#
# A targeted AppArmor profile is installed instead of the broader alternative
# (sysctl -w kernel.apparmor_restrict_unprivileged_userns=0), which would
# allow any binary to create user namespaces.

echo "==> Setting up bwrap sandbox..."

# -- Install prerequisites (needed by Claude Code's /sandbox) --
sudo apt-get install -y -qq bubblewrap socat

# -- Install AppArmor profile --
profile=/etc/apparmor.d/bwrap-userns-allow
if ! sudo test -f "$profile"; then
    sudo tee "$profile" > /dev/null <<'EOF'
abi <abi/4.0>,

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
}
EOF
    sudo apparmor_parser -r "$profile"
    echo "    Installed AppArmor profile for bwrap."
else
    echo "    AppArmor profile already present."
fi

# -- Verify --
if /usr/bin/bwrap --ro-bind / / --dev /dev echo ok >/dev/null 2>&1; then
    echo "==> bwrap sandbox ready."
else
    echo "ERROR: bwrap sandbox still not working" >&2
    exit 1
fi
