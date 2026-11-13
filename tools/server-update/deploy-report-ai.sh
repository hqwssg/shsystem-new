#!/bin/bash
set -Eeuo pipefail
PACKAGE_ROOT=$(cd -- "$(dirname -- "$0")" && pwd)
WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
DB_CONTAINER=${DB_CONTAINER:-ruoyi-db}
WEB_HOST_PORT=${WEB_HOST_PORT:-53221}
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD:?Set MYSQL_ROOT_PASSWORD}
RUNTIME_DIR=/opt/ruoyi-runtime/report-ai
UPDATE_ID=$(date +%Y%m%d-%H%M%S)
STAGING=/opt/carbon-report-ai-update/$UPDATE_ID
APPLY_STARTED=false
cleanup() {
  docker exec "$WEB_CONTAINER" rm -f "$STAGING/runtime-key.input" >/dev/null 2>&1 || true
}
recover() {
  code=$?
  trap - ERR
  echo 'ERROR: report AI update failed. No server update backup was created; preserve the execution log.' >&2
  if [ "$APPLY_STARTED" = true ]; then
    docker exec "$WEB_CONTAINER" sh /usr/local/bin/start-ruoyi-web.sh || true
  fi
  exit "$code"
}
case "${1:-}" in ''|--check) ;; *) echo 'Usage: bash deploy-report-ai.sh [--check]' >&2; exit 1 ;; esac
[ "$#" -le 1 ]
trap recover ERR
(cd "$PACKAGE_ROOT" && sha256sum -c SHA256SUMS > /dev/null)
for container in "$WEB_CONTAINER" "$DB_CONTAINER"; do
  [ "$(docker inspect -f '{{.State.Running}}' "$container")" = true ]
done
# Only SELECT statements are used; this delivery contains no database migration.
encrypted_count=$(docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" \
  mysql --protocol=TCP -h127.0.0.1 -P3306 -uroot --default-character-set=utf8mb4 -N -B carbon_emissions \
  -e "SELECT COUNT(*) FROM sys_config WHERE config_key='carbon.report.llm.default.apiKeyEncrypted' AND config_value IS NOT NULL AND config_value<>'';")
[[ "$encrypted_count" =~ ^[0-9]+$ ]]
docker exec "$WEB_CONTAINER" sh -c '
  test -s /etc/carbon-integration.env
  test -x /usr/local/bin/start-ruoyi-web.sh
  test -s /usr/local/lib/carbon-integration/runtime-common.sh
  test -s /home/ruoyi/ruoyi-admin.jar
  test -s /home/ruoyi/projects/ruoyi-ui/index.html
  test -s /home/ruoyi/renderer/carbon_report_agent/cli.py
  java -version
  nginx -t
  /opt/carbon-report-venv/bin/python -c "import sys, pydantic, docx, PIL, matplotlib, jinja2, httpx; assert (3,10) <= sys.version_info[:2] <= (3,12)"
'
if [ "${1:-}" = --check ]; then
  echo 'Preflight passed. No database, runtime configuration or application files were changed.'
  exit 0
fi
trap cleanup EXIT
docker exec "$WEB_CONTAINER" mkdir -p "$STAGING"
docker cp "$PACKAGE_ROOT/web-main/." "$WEB_CONTAINER:$STAGING/"
docker cp "$PACKAGE_ROOT/scripts/." "$WEB_CONTAINER:$STAGING/"
docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  PYTHONPATH="$1/renderer" /opt/carbon-report-venv/bin/python -m carbon_report_agent.cli --help | grep -q test-llm
  sh -n "$1/start-web.sh"
' sh "$STAGING"

# Persist the actual server key as protected runtime configuration, never in Git or the package.
# Reuse the original key and refuse to generate a replacement for existing encrypted data.
umask 077
mkdir -p "$RUNTIME_DIR"
chmod 700 "$RUNTIME_DIR"
if [ -e "$RUNTIME_DIR/llm-encryption.key" ]; then
  [ -s "$RUNTIME_DIR/llm-encryption.key" ]
  docker cp "$RUNTIME_DIR/llm-encryption.key" "$WEB_CONTAINER:$STAGING/runtime-key.input"
fi
docker exec -e HAS_ENCRYPTED_LLM_KEY="$encrypted_count" "$WEB_CONTAINER" sh -c '
  set -eu
  set -a
  . /etc/carbon-integration.env
  set +a
  /opt/carbon-report-venv/bin/python "$1/prepare-report-ai-key.py" "$1/runtime-key.input"
' sh "$STAGING"
if [ ! -e "$RUNTIME_DIR/llm-encryption.key" ]; then
  docker cp "$WEB_CONTAINER:/etc/carbon-report/llm-encryption.key" "$RUNTIME_DIR/llm-encryption.key"
fi
chmod 600 "$RUNTIME_DIR/llm-encryption.key"
docker exec "$WEB_CONTAINER" rm -f "$STAGING/runtime-key.input"

echo 'Replacing the main backend, main frontend and report renderer. No SQL migrations will run.'
APPLY_STARTED=true
docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  . /usr/local/lib/carbon-integration/runtime-common.sh
  stop_java ruoyi-admin.jar
  cp "$1/jar/ruoyi-admin.jar" /home/ruoyi/ruoyi-admin.jar
  rm -rf /home/ruoyi/projects/ruoyi-ui /home/ruoyi/renderer/carbon_report_agent
  cp -r "$1/html/dist" /home/ruoyi/projects/ruoyi-ui
  cp -r "$1/renderer/carbon_report_agent" /home/ruoyi/renderer/carbon_report_agent
  chmod -R a+rX /home/ruoyi/projects/ruoyi-ui /home/ruoyi/renderer/carbon_report_agent
  cp "$1/start-web.sh" /usr/local/bin/start-ruoyi-web.sh
  chmod 700 /usr/local/bin/start-ruoyi-web.sh
  sh /usr/local/bin/start-ruoyi-web.sh
' sh "$STAGING"
APPLY_STARTED=false
docker exec -i "$WEB_CONTAINER" /opt/carbon-report-venv/bin/python -c \
  "$(cat "$PACKAGE_ROOT/scripts/verify-report-ai-files.py")" < "$PACKAGE_ROOT/SHA256SUMS"
WEB_CONTAINER="$WEB_CONTAINER" DB_CONTAINER="$DB_CONTAINER" WEB_HOST_PORT="$WEB_HOST_PORT" \
  bash "$PACKAGE_ROOT/scripts/check-report-ai-health.sh"

echo 'Report AI update completed. Restarted web application services; runtime key retained. Sign in again and verify AI settings.'
