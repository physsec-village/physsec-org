#!/bin/sh
# Remove a pull request's containers, network, media volume, images, and worktree.
set -eu

preview_id=${1:-}
preview_root=${2:-}
preview_env_file=${3:-}

case "$preview_id" in
    [1-9]|[1-9][0-9]|[1-9][0-9][0-9]|[1-9][0-9][0-9][0-9]) ;;
    *) echo "Preview ID must be a canonical number between 1 and 9999." >&2; exit 2 ;;
esac
case "$preview_root" in /*) ;; *) echo "PREVIEW_ROOT must be an absolute path." >&2; exit 2 ;; esac
case "$preview_env_file" in /*) ;; *) echo "PREVIEW_ENV_FILE must be an absolute path." >&2; exit 2 ;; esac
[ "$preview_root" != / ] || { echo "PREVIEW_ROOT cannot be /." >&2; exit 2; }

preview_dir="$preview_root/pr-$preview_id"
checkout="$preview_dir/source"
control_compose="$PWD/docker-compose.preview.yml"
export PREVIEW_ID="$preview_id" PREVIEW_ENV_FILE="$preview_env_file" PREVIEW_CONTEXT="$PWD"

if [ -f "$control_compose" ]; then
    docker compose --project-name "psv-preview-$preview_id" \
        --file "$control_compose" down --volumes --remove-orphans
fi
docker image rm "psv-website-preview-$preview_id:latest" \
    "psv-website-preview-$preview_id:previous" 2>/dev/null || true
if [ -e "$checkout" ]; then
    git worktree remove --force "$checkout"
fi
rmdir "$preview_dir" 2>/dev/null || true
