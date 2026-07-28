#!/bin/sh
# Health-gated blue/green deployment through the host nginx instance.
set -eu

LOCK_FILE=${DEPLOY_LOCK_FILE:-/tmp/psv-website-deploy.lock}
STATE_DIR=${DEPLOY_STATE_DIR:-data/deploy}
STATE_FILE=${DEPLOY_STATE_FILE:-$STATE_DIR/active-slot}
WAIT_SECONDS=${DEPLOY_WAIT_SECONDS:-120}
SWITCH_HELPER=${DEPLOY_SWITCH_HELPER:-/usr/local/sbin/psv-switch-upstream}
ROUTE_URL=${DEPLOY_ROUTE_URL:-https://physsec.org/healthz}
ROUTE_RESOLVE=${DEPLOY_ROUTE_RESOLVE:-physsec.org:443:127.0.0.1}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "Another deployment is already running ($LOCK_FILE is locked)." >&2
    exit 1
fi

mkdir -p "$STATE_DIR"
state_tmp=
switched=false
old_slot=
new_service=

switch_command() {
    sudo -n "$SWITCH_HELPER" "$@"
}

route_matches() {
    expected_port=$1
    curl -fsS --noproxy '*' --max-time 10 --resolve "$ROUTE_RESOLVE" \
        -D - -o /dev/null "$ROUTE_URL" |
        tr -d '\r' |
        grep -Eiq "^X-PSV-Upstream:[[:space:]]*127\\.0\\.0\\.1:$expected_port([[:space:]]*)$"
}

cleanup() {
    status=$?
    [ -z "$state_tmp" ] || rm -f "$state_tmp"
    if [ "$status" -ne 0 ] && [ "$switched" = true ]; then
        if [ -n "$old_slot" ]; then
            echo "Deployment failed after cutover; restoring $old_slot." >&2
            switch_command "$old_slot" >/dev/null 2>&1 || true
        else
            # The first migration starts from the committed legacy upstream.
            # The privileged helper keeps that exact config as its rollback
            # file until the next successful switch.
            # shellcheck disable=SC2086
            switch_command rollback >/dev/null 2>&1 || true
        fi
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

if ! active=$(switch_command current); then
    echo "Cannot determine host nginx's active backend; complete the one-time nginx setup first." >&2
    exit 1
fi
case "$active" in
    blue|green)
        old_slot=$active
        ;;
    *)
        # No state is the supported migration from the legacy app on 8080.
        # Prefer blue for the first host-nginx-managed slot.
        active=legacy
        ;;
esac

case "$active" in
    blue) inactive=green ;;
    green) inactive=blue ;;
    legacy) inactive=blue ;;
esac

new_service=app-"$inactive"
new_image=psv-website:"$inactive"

echo "Building $new_image while the current backend continues serving."
APP_IMAGE=$new_image docker compose build "$new_service"

# A graceful nginx reload can leave old workers finishing upstream requests.
# Do not recreate their backend until that exact nginx generation has exited.
if [ "$active" != legacy ]; then
    elapsed=0
    until switch_command drained; do
        if [ "$elapsed" -ge "$WAIT_SECONDS" ]; then
            echo "Timed out waiting for old nginx workers to drain; the current backend is unchanged." >&2
            exit 1
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
fi

echo "Starting $new_service on its fixed loopback port."
if ! APP_IMAGE=$new_image docker compose up -d --no-deps "$new_service"; then
    APP_IMAGE=$new_image docker compose rm -sf "$new_service" >/dev/null 2>&1 || true
    echo "Compose failed to start $new_service; the current backend is unchanged." >&2
    exit 1
fi

container_id=$(APP_IMAGE=$new_image docker compose ps -q "$new_service")
[ -n "$container_id" ] || {
    echo "Compose did not create $new_service." >&2
    exit 1
}

elapsed=0
while :; do
    status=$(docker inspect --format \
        '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$container_id")
    case "$status" in
        healthy) break ;;
        unhealthy|exited|dead)
            echo "$new_service became $status; the current backend is unchanged." >&2
            APP_IMAGE=$new_image docker compose rm -sf "$new_service" >/dev/null 2>&1 || true
            exit 1
            ;;
    esac
    if [ "$elapsed" -ge "$WAIT_SECONDS" ]; then
        echo "Timed out waiting for $new_service; the current backend is unchanged." >&2
        APP_IMAGE=$new_image docker compose rm -sf "$new_service" >/dev/null 2>&1 || true
        exit 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
done

echo "Switching host nginx to $inactive."
switch_command "$inactive"
switched=true

elapsed=0
case "$inactive" in
    blue) inactive_port=8081 ;;
    green) inactive_port=8082 ;;
esac
until route_matches "$inactive_port"; do
    if [ "$elapsed" -ge 30 ]; then
        echo "Host nginx did not route verified traffic to $inactive." >&2
        exit 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
done

state_tmp=$STATE_FILE.tmp.$$
printf '%s\n' "$inactive" >"$state_tmp"
mv "$state_tmp" "$STATE_FILE"
state_tmp=
switched=false

# Keep the previous backend running for any gracefully draining nginx workers.
# The next deployment waits for that recorded generation before reusing it.

echo "Deployment complete: $new_service is active."
