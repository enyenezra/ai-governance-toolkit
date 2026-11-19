#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
env_file="${AIGOVKIT_DEMO_ENV_FILE:-.env.aigovkit-demo}"
project="${AIGOVKIT_DEMO_PROJECT:-aigovkit-demo}"
port="${AIGOVKIT_DEMO_PORT:-8001}"
if [ ! -f "$env_file" ]; then
  umask 077
  (
    set -o noclobber
    printf 'AIGOVKIT_DB_PASSWORD=%s\n' "$(openssl rand -hex 24)"
    printf 'AIGOVKIT_API_KEY=%s\n' "$(openssl rand -hex 32)"
    printf 'AIGOVKIT_DEVICE_HASH_KEY=%s\n' "$(openssl rand -hex 32)"
    printf 'AIGOVKIT_PORT=%s\n' "$port"
  ) > "$env_file"
fi
compose=(env -u AIGOVKIT_TENANTS -u AIGOVKIT_DISCOVERY_CONNECTIONS -u AIGOVKIT_AI_SIGNAL_DOMAINS
  -u AIGOVKIT_INCIDENT_OWNER -u AIGOVKIT_DB_PASSWORD -u AIGOVKIT_API_KEY
  -u AIGOVKIT_DEVICE_HASH_KEY -u AIGOVKIT_PORT docker compose -f compose.yaml --env-file "$env_file" -p "$project")
port="$(sed -n 's/^AIGOVKIT_PORT=//p' "$env_file")"
case "${1:-start}" in
  start)
    "${compose[@]}" up --build --wait
    printf '%s\n' "Workspace: http://127.0.0.1:$port/workspace" "Use AIGOVKIT_API_KEY from $env_file."
    ;;
  seed)
    "${compose[@]}" exec -T api python -m aigovkit.bootstrap --import-json examples/department-inventory.json
    ;;
  stop)
    "${compose[@]}" down
    ;;
  *)
    printf '%s\n' "Usage: bash scripts/demo.sh [start|seed|stop]" >&2
    exit 2
    ;;
esac
