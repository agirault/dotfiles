#!/usr/bin/env bash
set -euo pipefail

# Run system setup tests in a Docker container
# Usage:
#   ./run_tests.sh              # build image + run tests in Docker
#   ./run_tests.sh --no-docker  # run tests directly on this machine (destructive!)

DOTFILES_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ "${1:-}" == "--no-docker" ]]; then
    echo "==> Running tests directly (no Docker)..."
    cd "$DOTFILES_DIR"
    ./setup.sh all
    bash test/validate.sh configs
    ./setup.sh unlink
    bash test/validate.sh unlink
    exit $?
fi

echo "==> Building test image..."
docker build -t dotfiles-test -f "$DOTFILES_DIR/test/Dockerfile" "$DOTFILES_DIR"

echo "==> Running install + validate in container..."
docker run --rm \
    -v "$DOTFILES_DIR:/home/testuser/dotfiles" \
    dotfiles-test \
    bash -c '
        cd dotfiles
        ./setup.sh --no-docker --no-identity all
        bash test/validate.sh configs
        ./setup.sh unlink
        bash test/validate.sh unlink
    '

echo "==> All tests passed!"
