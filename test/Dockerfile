FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive

# Bare minimum to bootstrap (git clone would provide these on a real machine)
RUN apt-get update -qq && apt-get install -y -qq \
    sudo curl wget git \
    && rm -rf /var/lib/apt/lists/*

# Create a test user (non-root, like real usage)
RUN useradd -m -s /bin/bash testuser \
    && echo "testuser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER testuser
WORKDIR /home/testuser

# Simulate existing configs (to test backup behavior)
RUN echo -e "[user]\n    name = Old Name" > .gitconfig \
    && mkdir -p .config/fish/functions \
    && echo "# old fish config" > .config/fish/config.fish \
    && echo "# old tmux" > .tmux.conf \
    && mkdir -p .claude \
    && echo '{"old": true}' > .claude/settings.json \
    && mkdir -p .codex \
    && echo 'model = "old"' > .codex/config.toml \
    && echo "# old bashrc" > .bashrc
