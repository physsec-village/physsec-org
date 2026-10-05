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
#   PSV_DRAIN_TIMEOUT   max seconds to wait for old nginx workers to finish
#                       in-flight requests before stopping the old colour
#                       (default: 60; nginx proxy_read_timeout is 30s)
set -eu

# Serialize deploys per checkout: two concurrent runs could both pick the same
# idle colour. Re-exec under an exclusive lock held for the whole run.
if [ -z "${PSV_DEPLOY_LOCKED:-}" ]; then
    PSV_DEPLOY_LOCKED=1 exec flock -w 900 .deploy.lock "$0" "$@"
fi

# Read KEY=value from .env, stripping one matching layer of surrounding quotes
# the way Compose does, so a quoted value means the same thing to both.
env_value() {
    sed -n "s/^$1=//p" .env 2>/dev/null | tail -n 1 \
        | sed -e "s/^'\(.*\)'\$/\1/" -e 's/^"\(.*\)"$/\1/'
}

UPSTREAM_FILE=${PSV_UPSTREAM_FILE:-$(env_value PSV_UPSTREAM_FILE)}
NGINX_TEST_CMD=${PSV_NGINX_TEST_CMD:-$(env_value PSV_NGINX_TEST_CMD)}
NGINX_RELOAD_CMD=${PSV_NGINX_RELOAD_CMD:-$(env_value PSV_NGINX_RELOAD_CMD)}
DRAIN_TIMEOUT=${PSV_DRAIN_TIMEOUT:-$(env_value PSV_DRAIN_TIMEOUT)}
: "${NGINX_TEST_CMD:=sudo -n /usr/sbin/nginx -t}"
: "${NGINX_RELOAD_CMD:=sudo -n /usr/bin/systemctl reload nginx}"
: "${DRAIN_TIMEOUT:=60}"

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

is_healthy() {
    [ "$(docker inspect --format '{{.State.Health.Status}}' "$(compose ps -q "$1")" 2>/dev/null)" = healthy ]
}

# Wait for nginx workers from before the reload to finish their in-flight
# requests. Graceful-shutdown workers retitle themselves, which any user can
# see in the process list, so this needs no privileges. Bounded because a
# hung client keeps a worker alive indefinitely.
drain_old_workers() {
    waited=0
    while ps -eo args= | grep -q '^nginx: worker process is shutting down'; do
        if [ "$waited" -ge "$DRAIN_TIMEOUT" ]; then
            echo "Old nginx workers still draining after ${DRAIN_TIMEOUT}s; proceeding." >&2
            return
        fi
        sleep 1
        waited=$((waited + 1))
    done
}

# Determine the active colour. Normally exactly one is running. If neither
# is, this is a first install or a migration from the single-service layout.
#
# If both are running, an earlier deploy was interrupted. The include file
# alone does not say whether nginx ever loaded it, so converge first: if the
# colour named in the file is healthy, (re)load nginx so the file and the
# loaded config agree and finish the switch; otherwise restore the file to the
# other colour. Either way, exactly one colour is left running before the
# normal flow chooses which colour to replace.
active=""
if is_running blue && is_running green; then
    echo "Both colours are running; recovering an interrupted deploy." >&2
    filed=green
    if [ -f "$UPSTREAM_FILE" ] && grep -q ":$(host_port blue);" "$UPSTREAM_FILE"; then
        filed=blue
    fi
    unfiled=$(other_colour "$filed")
    if is_healthy "$filed"; then
        # Finish the switch. An nginx failure here means nothing is known
        # about what nginx serves, so leave both colours running and stop.
        if ! $NGINX_TEST_CMD || ! $NGINX_RELOAD_CMD; then
            echo "nginx test or reload failed during recovery; leaving both colours running." >&2
            exit 1
        fi
        drain_old_workers
        compose stop "$unfiled"
        active=$filed
    else
        echo "$filed is unhealthy; reverting the include to $unfiled." >&2
        recovery_previous=$(cat "$UPSTREAM_FILE" 2>/dev/null || true)
        printf 'server 127.0.0.1:%s;\n' "$(host_port "$unfiled")" > "$UPSTREAM_FILE"
        if ! $NGINX_TEST_CMD || ! $NGINX_RELOAD_CMD; then
            echo "nginx test or reload failed during recovery; restoring the include and leaving both colours running." >&2
            if [ -n "$recovery_previous" ]; then
                printf '%s\n' "$recovery_previous" > "$UPSTREAM_FILE"
            else
                rm -f "$UPSTREAM_FILE"
            fi
            exit 1
        fi
        compose stop "$filed"
        active=$unfiled
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

# Old nginx workers finish in-flight requests after the reload; stop the old
# colour only once they are gone (uvicorn then drains its own connections
# within Compose's stop grace period).
drain_old_workers

if [ -n "$active" ]; then
    compose stop "$active"
fi
if [ -n "$legacy" ]; then
    echo "Retiring legacy single-service container."
    docker stop $legacy >/dev/null
    docker rm $legacy >/dev/null
fi
