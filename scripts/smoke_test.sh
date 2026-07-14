#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "unit tests: uv run pytest tests/unit -q"
uv run pytest tests/unit -q

echo "Gitea health: curl -fsS http://localhost:3000/api/healthz"
if ! curl -fsS http://localhost:3000/api/healthz; then
  echo "Gitea health check failed — run scripts/reset_demo.sh" >&2
  exit 1
fi

echo "integration tests: uv run pytest tests/integration -q"
uv run pytest tests/integration -q

if [[ -d data/runs/run-m3-nollm-4 ]]; then
  echo "link: uv run blast-agent link --run-id run-m3-nollm-4"
  uv run blast-agent link --run-id run-m3-nollm-4
else
  echo "no crawl run present — run: uv run blast-agent crawl"
fi

echo "SMOKE OK"
