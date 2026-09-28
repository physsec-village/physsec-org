#!/bin/sh
# Blue/green, zero-downtime deployment for one checkout/environment.
#
# The idle colour is built and started while the active colour keeps serving.
# Once the new container passes its compose health check, the host nginx
# upstream include is pointed at the new colour's port and nginx is reloaded
# gracefully; only then is the old colour stopped. If the new colour fails its
# health check, or nginx rejects the new configuration, the active colour is
# left untouched and the deploy fails. Run from the repository root (the
# systemd unit's ExecReload does this via WorkingDirectory).
#
# Configuration comes from the checkout's .env (or the environment):
#   PSV_UPSTREAM_FILE   nginx include holding the active `server` line; the
#                       deploy account must own it (see deploy/README.md)
#   PSV_NGINX_TEST_CMD  command that validates nginx config
#                       (default: sudo -n /usr/sbin/nginx -t)
#   PSV_NGINX_RELOAD_CMD command that reloads nginx
#                       (default: sudo -n /usr/bin/systemctl reload nginx)
set -eu

env_value() {
    sed -n "s/^$1=//p" .env 2>/dev/null | tail -n 1
}

UPSTREAM_FILE=${PSV_UPSTREAM_FILE:-$(env_value PSV_UPSTREAM_FILE)}
NGINX_TEST_CMD=${PSV_NGINX_TEST_CMD:-$(env_value PSV_NGINX_TEST_CMD)}
NGINX_RELOAD_CMD=${PSV_NGINX_RELOAD_CMD:-$(env_value PSV_NGINX_RELOAD_CMD)}
: "${NGINX_TEST_CMD:=sudo -n /usr/sbin/nginx -t}"
: "${NGINX_RELOAD_CMD:=sudo -n /usr/bin/systemctl reload nginx}"

if [ -z "$UPSTREAM_FILE" ]; then
    echo "PSV_UPSTREAM_FILE is not set; see deploy/README.md." >&2
    exit 1
fi

# Enable both profiles so every command can see both colours.
compose() {
    docker compose --profile blue --profile green "$@"
}

is_running() {
    compose ps --services --status running 2>/dev/null | grep -qx "$1"
}

# Published host port of a colour; only valid once its container exists.
host_port() {
    compose port "$1" 8080 | sed 's/.*://'
}

other_colour() {
    if [ "$1" = blue ]; then echo green; else echo blue; fi
}

# Determine the active colour. Normally exactly one is running. If both are
# (an interrupted deploy), trust the upstream include; if neither is, this is
# a first install or a migration from the single-service layout.
active=""
if is_running blue && is_running green; then
    if [ -f "$UPSTREAM_FILE" ] && grep -q ":$(host_port blue);" "$UPSTREAM_FILE"; then
        active=blue
    else
        active=green
    fi
elif is_running blue; then
    active=blue
elif is_running green; then
    active=green
fi

# Legacy single-service container (`app`) from before blue/green. It holds
# the blue port, so migrate onto green and retire it after the switch.
project=$(compose config --format json 2>/dev/null | sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' | head -n 1)
legacy=""
if [ -n "$project" ]; then
    legacy=$(docker ps -q \
        --filter "label=com.docker.compose.project=$project" \
        --filter "label=com.docker.compose.service=app")
fi

if [ -n "$active" ]; then
    new=$(other_colour "$active")
elif [ -n "$legacy" ]; then
    new=green
else
    new=blue
fi

echo "Deploying $new${active:+ (replacing $active)}."

# A build failure aborts here and leaves the running container untouched.
compose build "$new"

if ! compose up -d --no-build --wait --wait-timeout 120 "$new"; then
    echo "New $new container failed its health check; $active keeps serving." >&2
    compose logs --no-log-prefix --tail 50 "$new" >&2 || true
    compose stop "$new" >/dev/null 2>&1 || true
    exit 1
fi

new_port=$(host_port "$new")
if [ -z "$new_port" ]; then
    echo "Could not determine the published port of $new." >&2
    compose stop "$new" >/dev/null 2>&1 || true
    exit 1
fi

# Switch nginx. Keep the previous include so a rejected config can be undone.
previous_upstream=""
if [ -f "$UPSTREAM_FILE" ]; then
    previous_upstream=$(cat "$UPSTREAM_FILE")
fi
printf 'server 127.0.0.1:%s;\n' "$new_port" > "$UPSTREAM_FILE"

restore_upstream() {
    if [ -n "$previous_upstream" ]; then
        printf '%s\n' "$previous_upstream" > "$UPSTREAM_FILE"
    else
        rm -f "$UPSTREAM_FILE"
    fi
}

if ! $NGINX_TEST_CMD; then
    echo "nginx rejected the new upstream; restoring the previous one." >&2
    restore_upstream
    compose stop "$new" >/dev/null 2>&1 || true
    exit 1
fi

if ! $NGINX_RELOAD_CMD; then
    echo "nginx reload failed; restoring the previous upstream." >&2
    restore_upstream
    $NGINX_RELOAD_CMD || true
    compose stop "$new" >/dev/null 2>&1 || true
    exit 1
fi

echo "nginx now routes to $new on 127.0.0.1:$new_port."

# Old nginx workers finish in-flight requests after the reload; give them a
# moment before the old colour receives SIGTERM (uvicorn then drains too).
sleep 5

if [ -n "$active" ]; then
    compose stop "$active"
fi
if [ -n "$legacy" ]; then
    echo "Retiring legacy single-service container."
    docker stop $legacy >/dev/null
    docker rm $legacy >/dev/null
fi
