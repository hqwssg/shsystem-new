#!/bin/sh
set -eu

PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
WEB_HOST_PORT=${WEB_HOST_PORT:-53221}
STAGING=/tmp/carbon-algorithm-upgrade-20261110

case "${1:-}" in
  ''|--check) ;;
  *) echo 'Usage: sh deploy-algorithm-upgrade-20261110.sh [--check]' >&2; exit 2 ;;
esac

cd "$PACKAGE_ROOT"
sha256sum -c SHA256SUMS
command -v docker >/dev/null
command -v sha256sum >/dev/null
test "$(docker inspect -f '{{.State.Running}}' "$WEB_CONTAINER")" = true
docker exec "$WEB_CONTAINER" test -x /opt/carbon-report-venv/bin/python
docker exec "$WEB_CONTAINER" test -r /etc/carbon-integration.env
docker exec "$WEB_CONTAINER" test -x /usr/local/bin/start-ruoyi-web.sh
docker exec "$WEB_CONTAINER" test -r /usr/local/lib/carbon-integration/runtime-common.sh
command -v curl >/dev/null

docker exec "$WEB_CONTAINER" sh -c "rm -rf '$STAGING' && mkdir -p '$STAGING'/energy-engine '$STAGING'/single-train-engine '$STAGING'/single-train-algorithm '$STAGING'/ui-dist"
docker cp "$PACKAGE_ROOT/energy-engine/." "$WEB_CONTAINER:$STAGING/energy-engine/"
docker cp "$PACKAGE_ROOT/single-train-engine/." "$WEB_CONTAINER:$STAGING/single-train-engine/"
docker cp "$PACKAGE_ROOT/single-train-algorithm/." "$WEB_CONTAINER:$STAGING/single-train-algorithm/"
docker cp "$PACKAGE_ROOT/ui-dist/." "$WEB_CONTAINER:$STAGING/ui-dist/"

docker exec "$WEB_CONTAINER" sh -eu -c '
  stage="$1"
  test -f "$stage/energy-engine/run_project.py"
  test -f "$stage/single-train-engine/worker.py"
  test -f "$stage/single-train-algorithm/api_contract.json"
  test -f "$stage/ui-dist/index.html"
  /opt/carbon-report-venv/bin/python -m compileall -q "$stage/energy-engine" "$stage/single-train-engine" "$stage/single-train-algorithm"
' sh "$STAGING"

if [ "${1:-}" = --check ]; then
  echo 'CHECK_OK: staged files and syntax validated; installed files and processes unchanged'
  exit 0
fi

docker exec "$WEB_CONTAINER" sh -eu -c '
  stage="$1"
  for pair in \
    "energy-engine:/home/ruoyi/energy-engine" \
    "single-train-engine:/home/ruoyi/single_train_recovery_agent" \
    "single-train-algorithm:/home/ruoyi/single_train_algorithm" \
    "ui-dist:/home/ruoyi/projects/ruoyi-ui"; do
    src=${pair%%:*}; dst=${pair#*:}
    # Overlay delivered files only; preserve runtime data and create no backup.
    mkdir -p "$dst"
    cp -R "$stage/$src/." "$dst/"
    chmod -R a+rX "$dst"
  done
' sh "$STAGING"

docker exec "$WEB_CONTAINER" sh -lc 'sh /usr/local/bin/start-ruoyi-web.sh'
attempt=0
while [ "$attempt" -lt 90 ]; do
  attempt=$((attempt + 1))
  if [ "$(docker inspect -f '{{.State.Running}}' "$WEB_CONTAINER" 2>/dev/null || true)" = true ]; then
    if command -v curl >/dev/null 2>&1; then
      code=$(curl --silent --connect-timeout 2 --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$WEB_HOST_PORT/" || true)
      if [ "$code" = 200 ] || [ "$code" = 301 ] || [ "$code" = 302 ]; then
        if docker exec "$WEB_CONTAINER" /opt/carbon-report-venv/bin/python -c '
import socket
for port in (80, 8081, 8082, 8085, 8086, 8090):
    with socket.create_connection(("127.0.0.1", port), timeout=1):
        pass
' >/dev/null 2>&1; then
          echo "PASS: web HTTP status is $code; all six application ports accept connections"
          echo 'No database migration, data reset, or server backup was performed.'
          exit 0
        fi
      fi
    else
      echo 'FAIL: curl unavailable' >&2
      exit 1
    fi
  fi
  sleep 1
done
echo 'FAIL: application health check failed; inspect /home/ruoyi/logs/*.log inside ruoyi-web' >&2
exit 1
