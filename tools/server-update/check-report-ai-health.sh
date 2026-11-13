#!/bin/bash
# Shared by the installer and the read-only post-deployment verifier.
set -Eeuo pipefail
WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
DB_CONTAINER=${DB_CONTAINER:-ruoyi-db}
SCREEN_CONTAINER=${SCREEN_CONTAINER:-ruoyi-screen}
WEB_HOST_PORT=${WEB_HOST_PORT:-53221}
SCREEN_HOST_PORT=${SCREEN_HOST_PORT:-53231}
HEALTH_ATTEMPTS=${HEALTH_ATTEMPTS:-120}
[[ "$HEALTH_ATTEMPTS" =~ ^[1-9][0-9]*$ ]]

for container in "$WEB_CONTAINER" "$DB_CONTAINER" "$SCREEN_CONTAINER"; do
  [ "$(docker inspect -f '{{.State.Running}}' "$container")" = true ]
done
wait_http() {
  local url=$1 allowed=$2 code round
  for ((round=1; round<=HEALTH_ATTEMPTS; round++)); do
    code=$(curl -sS --connect-timeout 3 --max-time 5 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)
    case ",$allowed," in *",$code,"*) echo "PASS $url -> $code"; return 0 ;; esac
    if [ "$round" -lt "$HEALTH_ATTEMPTS" ]; then sleep 1; fi
  done
  echo "ERROR: health check failed: $url -> $code" >&2
  case "$url" in
    *'/uncertainty/'*|*'/api/uncertainty/'*)
      # Never print runtime environment or API keys.
      docker exec "$WEB_CONTAINER" sh -c '
        pgrep -af "[u]ncertainty-app.jar" || true
        curl -sS -i --max-time 10 http://127.0.0.1:8085/uncertainty-wizard.html | head -c 1500
      ' >&2 || true
      echo 'Inspect /home/ruoyi/logs/uncertainty-app.log in ruoyi-web for startup errors.' >&2
      ;;
  esac
  return 1
}
wait_http "http://127.0.0.1:$WEB_HOST_PORT/" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/prod-api/code" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/carbon-model/" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/api/template/list" 200,401,403
# This is the page used by ruoyi-ui; the application has no root/index page.
wait_http "http://127.0.0.1:$WEB_HOST_PORT/uncertainty/uncertainty-wizard.html" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/api/uncertainty/calculation-tasks" 401,403
wait_http "http://127.0.0.1:$WEB_HOST_PORT/prediction/" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/prediction-api/platform/health" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/prediction-api/platform/orgs" 401,403
wait_http "http://127.0.0.1:$SCREEN_HOST_PORT/" 200
wait_http "http://127.0.0.1:$SCREEN_HOST_PORT/api/goview/sys/getOssInfo" 200,401,403

docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  pgrep -f "[r]uoyi-admin.jar" >/dev/null
  pgrep -f "[c]arbon-emission-model.jar" >/dev/null
  pgrep -f "[u]ncertainty-app.jar" >/dev/null
  pgrep -f "[p]rediction-platform.jar" >/dev/null
  curl -fsS --max-time 10 http://127.0.0.1:8090/health | grep -q "\"code\":0"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/ruoyi/renderer /opt/carbon-report-venv/bin/python -m carbon_report_agent.cli --help | grep -q test-llm
  /opt/carbon-report-venv/bin/python -c "from pathlib import Path; p=Path(\"/etc/carbon-report/llm-encryption.key\"); assert p.is_file() and p.stat().st_size > 0 and p.stat().st_mode & 0o077 == 0"
'
echo 'PASS service health, protected API routes, report CLI and runtime key permissions.'
