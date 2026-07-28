#!/bin/sh
# Health-gated blue/green deployment. Run from the repository root.
set -eu

LOCK_FILE=${DEPLOY_LOCK_FILE:-/tmp/psv-website-deploy.lock}
STATE_DIR=${DEPLOY_STATE_DIR:-data/deploy}
STATE_FILE=${DEPLOY_STATE_FILE:-$STATE_DIR/active-slot}
ROUTE_FILE=${DEPLOY_ROUTE_FILE:-$STATE_DIR/slot.conf}
WAIT_SECONDS=${DEPLOY_WAIT_SECONDS:-120}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "Another deployment is already running ($LOCK_FILE is locked)." >&2
    exit 1
fi

route_tmp=
state_tmp=
legacy_container=
legacy_handoff_complete=false
route_switch_pending=false
cleanup() {
    if [ "$route_switch_pending" = true ]; then
        write_route "$old_service" >/dev/null 2>&1 || true
        docker compose exec -T router nginx -s reload >/dev/null 2>&1 || true
    fi
    [ -z "$route_tmp" ] || rm -f "$route_tmp"
    [ -z "$state_tmp" ] || rm -f "$state_tmp"
    if [ -n "$legacy_container" ] && [ "$legacy_handoff_complete" = false ] &&
        ! docker inspect --format '{{.State.Running}}' "$legacy_container" 2>/dev/null |
            grep -q true; then
        docker compose stop router >/dev/null 2>&1 || true
        docker start "$legacy_container" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

mkdir -p "$STATE_DIR"

case "$(cat "$STATE_FILE" 2>/dev/null || true)" in
    blue) active=blue ;;
    green) active=green ;;
    *)
        # Recover state after an interrupted deploy or on the first deploy.
        if docker compose ps --status running -q app-green | grep -q .; then
            active=green
        else
            active=blue
        fi
        ;;
esac

# The response header reflects the router's loaded configuration, so it also
# repairs ambiguity if a process was interrupted between reload and state save.
loaded_route=$(docker compose exec -T router sh -c \
    "wget -SO /dev/null http://127.0.0.1:8080/healthz 2>&1" 2>/dev/null |
    tr '[:upper:]' '[:lower:]' |
    sed -n 's/.*x-psv-slot: app-\(blue\|green\):8080.*/\1/p' |
    head -n 1 || true)
case "$loaded_route" in
    blue|green) active=$loaded_route ;;
esac

case "$active" in
    blue) inactive=green ;;
    green) inactive=blue ;;
esac

new_service=app-"$inactive"
old_service=app-"$active"
# Fixed per-slot tags avoid accumulating a permanently tagged image on every
# deploy. Docker keeps an old image alive while a stopped container needs it.
new_image=psv-website:"$inactive"

write_route() {
    route_tmp=$ROUTE_FILE.tmp.$$
    printf 'set $active_backend %s:8080;\n' "$1" >"$route_tmp"
    mv "$route_tmp" "$ROUTE_FILE"
    route_tmp=
}

route_matches() {
    docker compose exec -T router sh -c \
        "wget -SO /dev/null http://127.0.0.1:8080/healthz 2>&1 | grep -qi 'X-PSV-Slot: $1:8080'"
}

restore_old_route() {
    write_route "$old_service"
    if docker compose exec -T router nginx -s reload &&
        route_matches "$old_service"; then
        echo "Restored $old_service." >&2
        return 0
    fi
    echo "Could not confirm rollback to $old_service; both app slots remain available for recovery." >&2
    return 1
}

echo "Building $new_image while $old_service continues serving."
APP_IMAGE=$new_image docker compose build "$new_service"

echo "Starting $new_service."
if ! APP_IMAGE=$new_image docker compose up -d --no-deps "$new_service"; then
    APP_IMAGE=$new_image docker compose rm -sf "$new_service" >/dev/null 2>&1 || true
    echo "Compose failed to start $new_service; leaving $old_service in service." >&2
    exit 1
fi
container_id=$(APP_IMAGE=$new_image docker compose ps -q "$new_service")
[ -n "$container_id" ] || {
    echo "Compose did not create $new_service." >&2
    exit 1
}

elapsed=0
while :; do
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")
    case "$status" in
        healthy) break ;;
        unhealthy|exited|dead)
            echo "$new_service became $status; leaving $old_service in service." >&2
            APP_IMAGE=$new_image docker compose rm -sf "$new_service" >/dev/null 2>&1 || true
            exit 1
            ;;
    esac
    if [ "$elapsed" -ge "$WAIT_SECONDS" ]; then
        echo "Timed out waiting for $new_service; leaving $old_service in service." >&2
        APP_IMAGE=$new_image docker compose rm -sf "$new_service" >/dev/null 2>&1 || true
        exit 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
done

route_switch_pending=true
write_route "$new_service"

# The first blue/green deployment replaces the legacy single `app` container,
# which owns the router's host port. Keep it serving until the new slot is
# healthy, then make the one-time handoff immediately before starting the
# router. The working-directory label prevents touching an `app` service from
# another Compose project.
legacy_container=$(docker ps -q \
    --filter "label=com.docker.compose.service=app" \
    --filter "label=com.docker.compose.project.working_dir=$(pwd)" |
    head -n 1)
if [ -n "$legacy_container" ]; then
    echo "Stopping the legacy app container for the one-time router handoff."
    docker stop "$legacy_container" >/dev/null
fi

# On the first deployment the router does not exist yet. On later deployments
# this is a no-op and, importantly, does not recreate it.
if ! docker compose up -d --no-deps router; then
    if [ -n "$legacy_container" ]; then
        docker start "$legacy_container" >/dev/null
        echo "Router failed to start; restored the legacy app container." >&2
    else
        write_route "$old_service"
        docker compose up -d --no-deps router >/dev/null 2>&1 || true
        route_matches "$old_service" >/dev/null 2>&1 || true
        echo "Router failed to start with the new route; restored its previous route file." >&2
    fi
    exit 1
fi
if ! docker compose exec -T router nginx -s reload; then
    if [ -n "$legacy_container" ]; then
        docker compose stop router >/dev/null 2>&1 || true
        docker start "$legacy_container" >/dev/null
        echo "Router reload failed; restored the legacy app container." >&2
        exit 1
    fi
    restore_old_route || true
    echo "Router reload failed." >&2
    exit 1
fi

if ! route_matches "$new_service"; then
    if [ -n "$legacy_container" ]; then
        docker compose stop router >/dev/null 2>&1 || true
        docker start "$legacy_container" >/dev/null
        echo "New route failed verification; restored the legacy app container." >&2
        exit 1
    fi
    restore_old_route || true
    echo "New route failed verification." >&2
    exit 1
fi

state_tmp=$STATE_FILE.tmp.$$
printf '%s\n' "$inactive" >"$state_tmp"
mv "$state_tmp" "$STATE_FILE"
state_tmp=
route_switch_pending=false
legacy_handoff_complete=true

# The old slot is stopped only after traffic through the stable port succeeds.
docker compose stop "$old_service" >/dev/null 2>&1 || true
echo "Deployment complete: $new_service is active."
