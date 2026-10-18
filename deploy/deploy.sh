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
#                       deploy account must be able to write its directory. On the app host the
#                       physsec-oci Ansible `website` role sets it.
#   PSV_NGINX_CONF_DIRS directories searched for a config that includes
#                       PSV_UPSTREAM_FILE (default: /etc/nginx/sites-enabled
#                       /etc/nginx/conf.d)
#   PSV_NGINX_TEST_CMD  command that validates nginx config
#                       (default: sudo -n /usr/sbin/nginx -t)
#   PSV_NGINX_RELOAD_CMD command that reloads nginx
#                       (default: sudo -n /usr/bin/systemctl reload nginx)
#   PSV_DRAIN_TIMEOUT   max seconds to wait for old nginx workers to finish
#                       in-flight requests before stopping the old colour
#                       (default: 60; nginx proxy_read_timeout is 30s)
#   PSV_SWITCH_LOCK     host-wide lock serializing nginx switches across
#                       environments (default: .switch.lock next to
#                       PSV_UPSTREAM_FILE)
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
# At 0 the deadline would pass before nginx retitles its old workers, so
# every switch would look like a rejected reload.
case $DRAIN_TIMEOUT in
    ''|*[!0-9]*) drain_ok="" ;;
    *) [ "$DRAIN_TIMEOUT" -ge 1 ] && drain_ok=1 || drain_ok="" ;;
esac
if [ -z "$drain_ok" ]; then
    echo "PSV_DRAIN_TIMEOUT must be a whole number of seconds, at least 1; got '$DRAIN_TIMEOUT'." >&2
    exit 1
fi
SWITCH_LOCK=${PSV_SWITCH_LOCK:-$(env_value PSV_SWITCH_LOCK)}

if [ -z "$UPSTREAM_FILE" ]; then
    echo "PSV_UPSTREAM_FILE is not set; the physsec-oci website role sets it." >&2
    exit 1
fi
: "${SWITCH_LOCK:=$(dirname "$UPSTREAM_FILE")/.switch.lock}"

# Switching the include does nothing unless an enabled vhost reads it. The
# vhosts are installed by Ansible from a checkout, so a host whose vhost
# predates blue/green would keep proxying to the old port and lose traffic
# when the old colour stops. Refuse to deploy until the playbook has run.
CONF_DIRS=${PSV_NGINX_CONF_DIRS:-$(env_value PSV_NGINX_CONF_DIRS)}
: "${CONF_DIRS:=/etc/nginx/sites-enabled /etc/nginx/conf.d}"
# shellcheck disable=SC2086 # CONF_DIRS is a space-separated list.
if ! grep -RqsF -- "$UPSTREAM_FILE" $CONF_DIRS; then
    echo "No enabled nginx config includes $UPSTREAM_FILE; run the physsec-oci playbook first." >&2
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

# PIDs of the current nginx workers, read from the process list so this needs
# no privileges. Matches both "nginx: worker process" and the "... is shutting
# down" title a worker takes on while it drains.
nginx_worker_pids() {
    ps -eo pid=,args= | awk '$2 == "nginx:" && $3 == "worker" && $4 == "process" { print $1 }'
}

# Reload nginx, first recording which workers predate the reload. The reload
# command only signals the master and returns at once, so the workers it will
# retire cannot be identified afterwards by looking for "shutting down".
old_workers=""
reload_nginx() {
    old_workers=$(nginx_worker_pids)
    $NGINX_RELOAD_CMD
}

# Wait for the workers recorded by reload_nginx to exit, i.e. to finish their
# in-flight requests. Bounded because a hung client keeps a worker alive
# indefinitely. Returns 1 if, at the deadline, an old worker has not even
# started shutting down: the reload signal returns before nginx parses the
# config, so that is how a rejected reload shows up.
drain_old_workers() {
    waited=0
    while [ -n "$old_workers" ]; do
        still_running=""
        not_retired=""
        for pid in $old_workers; do
            title=$(ps -o args= -p "$pid" 2>/dev/null || true)
            case $title in
                "nginx: worker process") not_retired=1 ;;
                "nginx: worker process"*) ;;
                *) continue ;;
            esac
            still_running="$still_running $pid"
        done
        old_workers=${still_running# }
        [ -n "$old_workers" ] || break
        if [ "$waited" -ge "$DRAIN_TIMEOUT" ]; then
            old_workers=""
            if [ -n "$not_retired" ]; then
                echo "nginx did not apply the reload within ${DRAIN_TIMEOUT}s." >&2
                return 1
            fi
            echo "Old nginx workers still draining after ${DRAIN_TIMEOUT}s; proceeding." >&2
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
}

# Replace the include atomically so a concurrent nginx -t or reload never
# reads a truncated file.
write_upstream() {
    printf '%s\n' "$1" > "$UPSTREAM_FILE.tmp.$$" && mv -f "$UPSTREAM_FILE.tmp.$$" "$UPSTREAM_FILE"
}

# Point nginx at a running colour: rewrite the include, validate, reload, and
# wait for the old workers to drain. Production and dev share one nginx, so
# this holds a host-wide lock; otherwise one environment's reload could pick
# up the other's half-finished switch. On failure the previous include is
# restored and nothing is stopped.
switch_to() {
    sw_port=$(host_port "$1")
    if [ -z "$sw_port" ]; then
        echo "Could not determine the published port of $1." >&2
        return 1
    fi
    exec 9>>"$SWITCH_LOCK"
    if ! flock -w 300 9; then
        echo "Timed out waiting for $SWITCH_LOCK." >&2
        exec 9>&-
        return 1
    fi
    sw_previous=$(cat "$UPSTREAM_FILE" 2>/dev/null || true)
    # switch_to always runs in a condition, where set -e does not apply, so
    # check the write. A failed printf or mv leaves the include untouched.
    if ! write_upstream "server 127.0.0.1:$sw_port;"; then
        echo "Could not write $UPSTREAM_FILE; is its directory writable?" >&2
        exec 9>&-
        return 1
    fi
    sw_ok=""
    if ! $NGINX_TEST_CMD; then
        echo "nginx rejected the upstream for $1." >&2
    elif ! reload_nginx; then
        echo "nginx reload failed." >&2
    elif ! drain_old_workers; then
        :
    else
        sw_ok=1
    fi
    if [ -z "$sw_ok" ]; then
        echo "Restoring the previous upstream." >&2
        if [ -n "$sw_previous" ]; then
            write_upstream "$sw_previous" || echo "Could not restore $UPSTREAM_FILE." >&2
        else
            rm -f "$UPSTREAM_FILE"
        fi
    fi
    exec 9>&-
    [ -n "$sw_ok" ] || return 1
    echo "nginx now routes to $1 on 127.0.0.1:$sw_port."
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
    if is_healthy "$filed"; then
        keep=$filed
    else
        echo "$filed is unhealthy; reverting to $(other_colour "$filed")." >&2
        keep=$(other_colour "$filed")
    fi
    # An nginx failure here means nothing is known about what nginx serves,
    # so leave both colours running and stop.
    if ! switch_to "$keep"; then
        echo "Recovery failed; leaving both colours running." >&2
        exit 1
    fi
    compose stop "$(other_colour "$keep")"
    active=$keep
elif is_running blue; then
    active=blue
elif is_running green; then
    active=green
fi

# Legacy single-service container (`app`) from before blue/green. It holds
# the blue port, so migrate onto green and retire it after the switch.
project=$(compose config --format json 2>/dev/null | sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' | head -n 1)
legacy=""
retire_legacy() {
    echo "Retiring legacy single-service container."
    # shellcheck disable=SC2086 # one or more container IDs
    docker stop $legacy >/dev/null
    # shellcheck disable=SC2086
    docker rm $legacy >/dev/null
    legacy=""
}
if [ -n "$project" ]; then
    legacy=$(docker ps -q \
        --filter "label=com.docker.compose.project=$project" \
        --filter "label=com.docker.compose.service=app")
fi

# A colour running beside the legacy container means the first blue/green
# deploy was interrupted. Finish it before choosing a colour: the legacy
# container holds the blue port, so deploying blue would fail forever.
if [ -n "$active" ] && [ -n "$legacy" ]; then
    echo "Legacy container still running beside $active; finishing the migration." >&2
    if is_healthy "$active" && switch_to "$active"; then
        retire_legacy
    else
        echo "Could not move traffic to $active; redeploying it." >&2
        compose stop "$active"
        active=""
    fi
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

# Migrations run before the new colour starts, while the active colour keeps
# serving, and are forward-only: every migration must stay backward compatible
# with the release still running. The runner skips itself when
# MIGRATION_DATABASE_URL is empty.
compose run --rm --no-deps "$new" python -m src.store.migrate || exit 1

if ! compose up -d --no-build --wait --wait-timeout 120 "$new"; then
    echo "New $new container failed its health check; $active keeps serving." >&2
    compose logs --no-log-prefix --tail 50 "$new" >&2 || true
    compose stop "$new" >/dev/null 2>&1 || true
    exit 1
fi

# Old nginx workers finish in-flight requests after the reload; switch_to
# returns once they are gone, so the old colour is stopped only afterwards
# (uvicorn then drains its own connections within Compose's stop grace
# period).
if ! switch_to "$new"; then
    echo "$new was not put into service; ${active:-the previous container} keeps serving." >&2
    compose stop "$new" >/dev/null 2>&1 || true
    exit 1
fi

if [ -n "$active" ]; then
    compose stop "$active"
fi
if [ -n "$legacy" ]; then
    retire_legacy
fi
