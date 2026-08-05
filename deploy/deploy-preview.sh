#!/bin/sh
# Deploy a trusted, same-repository pull request as an isolated Compose project.
set -eu

preview_id=${1:-}
revision=${2:-}
preview_root=${3:-}
preview_env_file=${4:-}

case "$preview_id" in *[!0-9]*|'') echo "Preview ID must be numeric." >&2; exit 2 ;; esac
case "$revision" in *[!0-9a-f]*|'') echo "Revision must be a lowercase Git SHA." >&2; exit 2 ;; esac
[ "${#revision}" -eq 40 ] || { echo "Revision must be a complete Git SHA." >&2; exit 2; }
case "$preview_root" in /*) ;; *) echo "PREVIEW_ROOT must be an absolute path." >&2; exit 2 ;; esac
case "$preview_env_file" in /*) ;; *) echo "PREVIEW_ENV_FILE must be an absolute path." >&2; exit 2 ;; esac
[ "$preview_root" != / ] || { echo "PREVIEW_ROOT cannot be /." >&2; exit 2; }
[ "$preview_id" -le 9999 ] || { echo "Preview IDs above 9999 are not supported by the hostname matcher." >&2; exit 2; }
[ -f "$preview_env_file" ] || { echo "Preview environment file does not exist." >&2; exit 2; }

control_compose="$PWD/docker-compose.preview.yml"
[ -f "$control_compose" ] || { echo "Trusted preview Compose file does not exist." >&2; exit 2; }
preview_dir="$preview_root/pr-$preview_id"
checkout="$preview_dir/source"
project="psv-preview-$preview_id"

mkdir -p "$preview_dir"
if [ -e "$checkout" ]; then
    git worktree remove --force "$checkout"
fi
git fetch origin "refs/pull/$preview_id/head"
[ "$(git rev-parse FETCH_HEAD)" = "$revision" ] || {
    echo "Fetched PR revision does not match the requested Git SHA." >&2
    exit 1
}
git worktree add --detach "$checkout" "$revision"

export PREVIEW_ID="$preview_id" PREVIEW_ENV_FILE="$preview_env_file" PREVIEW_CONTEXT="$checkout"
compose() {
    docker compose --project-name "$project" --file "$control_compose" "$@"
}

image="psv-website-preview-$preview_id"
if docker image inspect "$image:latest" >/dev/null 2>&1; then
    docker tag "$image:latest" "$image:previous"
fi

compose build
if ! compose up -d --wait --wait-timeout 120; then
    rolled_back=false
    if docker image inspect "$image:previous" >/dev/null 2>&1; then
        echo "Preview failed its health check; rolling back." >&2
        if docker tag "$image:previous" "$image:latest" && \
            compose up -d --no-build --wait --wait-timeout 120; then
            rolled_back=true
        fi
    fi
    if [ "$rolled_back" = false ]; then
        echo "No healthy rollback is available; removing the failed preview." >&2
        compose down --volumes --remove-orphans || true
    fi
    exit 1
fi
