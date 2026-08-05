#!/bin/sh
# Deploy the dev branch as an isolated Compose project on the shared VPS.
set -eu

compose() {
    docker compose -f docker-compose.dev.yml "$@"
}

# Keep the current dev image available if the replacement fails health checks.
if docker image inspect psv-website-dev:latest >/dev/null 2>&1; then
    docker tag psv-website-dev:latest psv-website-dev:previous
fi

# A build failure leaves the running dev container untouched.
compose build

if ! compose up -d --wait --wait-timeout 120; then
    if docker image inspect psv-website-dev:previous >/dev/null 2>&1; then
        echo "New dev container failed its health check; rolling back." >&2
        docker tag psv-website-dev:previous psv-website-dev:latest
        compose up -d --no-build --wait --wait-timeout 120
    fi
    exit 1
fi
