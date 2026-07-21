#!/bin/sh
# Build-then-swap deployment. The new image is built while the current
# container keeps serving; the container is only replaced once the new one
# passes its compose health check, and is rolled back to the previously
# deployed image otherwise. Run from the repository root (the systemd unit's
# ExecReload does this via WorkingDirectory).
set -eu

# Keep the currently deployed image around for rollback.
if docker image inspect psv-website:latest >/dev/null 2>&1; then
    docker tag psv-website:latest psv-website:previous
fi

# A build failure aborts here and leaves the running container untouched.
docker compose build

if ! docker compose up -d --wait --wait-timeout 120; then
    if docker image inspect psv-website:previous >/dev/null 2>&1; then
        echo "New container failed its health check; rolling back." >&2
        docker tag psv-website:previous psv-website:latest
        docker compose up -d --no-build --wait --wait-timeout 120
    fi
    exit 1
fi
