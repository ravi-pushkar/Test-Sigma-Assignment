#!/usr/bin/env bash
set -euo pipefail

GITEA_SHA=daf581fa892320f5d495b4073d6812b0ad8ddfc8
GITEA_PR_HEAD_SHA=e7095e0957a6b46273c2c21afff3450543cb8257
GITEA_DIR=third_party/gitea

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

force=false
if [[ ${1:-} == "--force" ]]; then
  force=true
  shift
fi

if (( $# != 0 )); then
  printf 'Usage: %s [--force]\n' "$0" >&2
  exit 2
fi

cd -- "$REPO_ROOT"

if [[ ! -d "$GITEA_DIR/.git" ]]; then
  mkdir -p -- "$GITEA_DIR"
  git -C "$GITEA_DIR" init
  git -C "$GITEA_DIR" remote add origin https://github.com/go-gitea/gitea.git
fi

current_sha="$(git -C "$GITEA_DIR" rev-parse HEAD 2>/dev/null || true)"
if [[ "$current_sha" != "$GITEA_SHA" ]]; then
  git -C "$GITEA_DIR" fetch --depth 1 origin "$GITEA_SHA"
  git -C "$GITEA_DIR" checkout --detach FETCH_HEAD
fi

# The code indexer, not the build, needs the PR head commit in the object store.
if ! git -C "$GITEA_DIR" cat-file -e "$GITEA_PR_HEAD_SHA^{commit}" 2>/dev/null; then
  git -C "$GITEA_DIR" fetch --depth 1 origin "$GITEA_PR_HEAD_SHA"
fi

if ! command -v go >/dev/null 2>&1; then
  printf 'Error: go is required but was not found on PATH.\n' >&2
  exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
  printf 'Error: pnpm is required but was not found on PATH.\n' >&2
  exit 1
fi

export GOTOOLCHAIN=auto

if [[ ! -x "$GITEA_DIR/gitea" || "$force" == true ]]; then
  (
    cd -- "$GITEA_DIR"
    TAGS='sqlite sqlite_unlock_notify' make build
  )
fi

binary_path="$REPO_ROOT/$GITEA_DIR/gitea"
printf 'Built binary: %s\n' "$binary_path"
printf 'Version: %s\n' "$(cd -- "$GITEA_DIR" && ./gitea --version)"
