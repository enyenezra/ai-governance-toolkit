#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${AIGOVKIT_TEST_DATABASE_URL:?Set the disposable PostgreSQL test database URL}"
export AIGOVKIT_DATABASE_URL="$AIGOVKIT_TEST_DATABASE_URL"
export AIGOVKIT_BROWSER_EDITOR="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export AIGOVKIT_BROWSER_READER="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export AIGOVKIT_TENANTS="$(python -c 'import json, os, secrets; print(json.dumps([{"id":"browser-"+secrets.token_hex(5), "members":[{"id":"editor","role":"editor","key":os.environ["AIGOVKIT_BROWSER_EDITOR"]},{"id":"reader","role":"reader","key":os.environ["AIGOVKIT_BROWSER_READER"]}]}]))')"
port="$(python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
export AIGOVKIT_BROWSER_URL="http://127.0.0.1:$port"
python -m aigovkit.bootstrap
python -m uvicorn main:app --host 127.0.0.1 --port "$port" --no-access-log &
app_pid=$!
trap 'kill "$app_pid" 2>/dev/null || true' EXIT
for attempt in {1..30}; do
  if curl -fsS "$AIGOVKIT_BROWSER_URL/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
node tests/browser/smoke.cjs
