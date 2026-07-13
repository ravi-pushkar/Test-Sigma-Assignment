#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
GITEA_DIR="$REPO_ROOT/data/gitea"
APP_INI="$GITEA_DIR/app.ini"
PID_FILE="$GITEA_DIR/gitea.pid"
LOG_DIR="$GITEA_DIR/log"
GITEA_BIN="$REPO_ROOT/third_party/gitea/gitea"
GITEA=("$GITEA_BIN" --config "$APP_INI")

export GITEA_WORK_DIR="$GITEA_DIR"

stop_server() {
  if [[ -f "$PID_FILE" ]]; then
    pid="$(cat "$PID_FILE")"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid"
      while kill -0 "$pid" 2>/dev/null; do
        sleep 0.2
      done
    fi
    rm -f "$PID_FILE"
  fi

  pkill -f 'third_party/gitea/gitea' 2>/dev/null || true
}

wait_for_server() {
  local deadline=$((SECONDS + 90))

  until curl -fsS -o /dev/null http://localhost:3000/api/healthz; do
    if (( SECONDS >= deadline )); then
      echo "Gitea did not become healthy within 90 seconds" >&2
      return 1
    fi
    sleep 1
  done
}

start_server() {
  mkdir -p "$LOG_DIR"
  nohup "${GITEA[@]}" web --pid "$PID_FILE" \
    >> "$LOG_DIR/server-stdout.log" 2>&1 &
  wait_for_server
}

case "${1:-}" in
  --stop)
    if (( $# != 1 )); then
      echo "Usage: $0 [--stop|--start]" >&2
      exit 2
    fi
    stop_server
    exit 0
    ;;
  --start)
    if (( $# != 1 )); then
      echo "Usage: $0 [--stop|--start]" >&2
      exit 2
    fi
    if [[ ! -f "$APP_INI" ]]; then
      echo "Missing Gitea configuration: $APP_INI" >&2
      exit 1
    fi
    start_server
    exit 0
    ;;
  "")
    ;;
  *)
    echo "Usage: $0 [--stop|--start]" >&2
    exit 2
    ;;
esac

stop_server
rm -rf "$GITEA_DIR"
mkdir -p "$GITEA_DIR/repos" "$LOG_DIR"

SECRET_KEY="$(openssl rand -hex 32)"
cat > "$APP_INI" <<EOF
RUN_MODE = prod
WORK_PATH = $GITEA_DIR

[server]
PROTOCOL = http
HTTP_ADDR = 127.0.0.1
HTTP_PORT = 3000
ROOT_URL = http://localhost:3000/
DISABLE_SSH = true
OFFLINE_MODE = true
STATIC_ROOT_PATH = $REPO_ROOT/third_party/gitea

[database]
DB_TYPE = sqlite3
PATH = $GITEA_DIR/gitea.db

[repository]
ROOT = $GITEA_DIR/repos

[security]
INSTALL_LOCK = true
SECRET_KEY = $SECRET_KEY

[service]
DISABLE_REGISTRATION = true
REQUIRE_SIGNIN_VIEW = false

[mailer]
ENABLED = false

[actions]
ENABLED = false

[log]
MODE = file
ROOT_PATH = $LOG_DIR
LEVEL = info
EOF

"${GITEA[@]}" migrate
"${GITEA[@]}" admin user create \
  --admin \
  --username demo-admin \
  --password 'DemoAdmin2026!' \
  --email demo-admin@example.local \
  --must-change-password=false
"${GITEA[@]}" admin user create \
  --username demo-user \
  --password 'DemoUser2026!' \
  --email demo-user@example.local \
  --must-change-password=false

TOKEN="$("${GITEA[@]}" admin user generate-access-token \
  --username demo-admin \
  --token-name "seed-$(date +%s)" \
  --scopes all \
  --raw | tail -n 1)"

start_server

API_URL='http://localhost:3000/api/v1'
AUTH_HEADER="Authorization: token $TOKEN"

curl -fsS -X POST \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","visibility":"public"}' \
  "$API_URL/orgs" >/dev/null

curl -fsS -X POST \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"name":"demo-repo","auto_init":true,"default_branch":"main","private":false}' \
  "$API_URL/orgs/demo/repos" >/dev/null

curl -fsS -X PUT \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"permission":"write"}' \
  "$API_URL/repos/demo/demo-repo/collaborators/demo-user" >/dev/null

BUG_LABEL_RESPONSE="$(curl -fsS -X POST \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"name":"bug","color":"#ee0701"}' \
  "$API_URL/repos/demo/demo-repo/labels")"
BUG_LABEL_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<< "$BUG_LABEL_RESPONSE")"

ENHANCEMENT_LABEL_RESPONSE="$(curl -fsS -X POST \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"name":"enhancement","color":"#84b6eb"}' \
  "$API_URL/repos/demo/demo-repo/labels")"
ENHANCEMENT_LABEL_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<< "$ENHANCEMENT_LABEL_RESPONSE")"

MILESTONE_RESPONSE="$(curl -fsS -X POST \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"title":"v1.0","description":"First stable demo milestone"}' \
  "$API_URL/repos/demo/demo-repo/milestones")"
MILESTONE_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<< "$MILESTONE_RESPONSE")"

ISSUE_ONE_JSON="$(python3 -c 'import json,sys; print(json.dumps({"title":"Sidebar labels are not saved on first click","body":"The issue sidebar does not save labels on the first click.","labels":[int(sys.argv[1])],"milestone":int(sys.argv[2])}))' "$BUG_LABEL_ID" "$MILESTONE_ID")"
curl -fsS -X POST \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d "$ISSUE_ONE_JSON" \
  "$API_URL/repos/demo/demo-repo/issues" >/dev/null

ISSUE_TWO_JSON="$(python3 -c 'import json,sys; print(json.dumps({"title":"Add keyboard shortcut for creating issues","body":"Add a keyboard shortcut that opens the issue creation flow.","labels":[int(sys.argv[1])]}))' "$ENHANCEMENT_LABEL_ID")"
curl -fsS -X POST \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d "$ISSUE_TWO_JSON" \
  "$API_URL/repos/demo/demo-repo/issues" >/dev/null

curl -fsS -X POST \
  -H "$AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Watch button state unclear after page reload","body":"The notifications and watching state is unclear after reloading the page."}' \
  "$API_URL/repos/demo/demo-repo/issues" >/dev/null

cat <<'EOF'
URL: http://localhost:3000/
Admin username: demo-admin
Admin password: DemoAdmin2026!
User username: demo-user
User password: DemoUser2026!
Repo URL: http://localhost:3000/demo/demo-repo
SEEDED OK
EOF
