#!/usr/bin/env bash
set -Eeuo pipefail

PACKAGE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DB_CONTAINER=${DB_CONTAINER:-ruoyi-db}
WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
SCREEN_CONTAINER=${SCREEN_CONTAINER:-ruoyi-screen}
WEB_HOST_PORT=${WEB_HOST_PORT:-53221}
SCREEN_HOST_PORT=${SCREEN_HOST_PORT:-53231}
MYSQL_USER=${MYSQL_USER:-root}
WEB_STOPPED=false
SCREEN_STOPPED=false
STAGE=/tmp/monthly-analysis-update

recover_services() {
  local status=$?
  trap - ERR
  if [ "$WEB_STOPPED" = true ]; then
    docker exec "$WEB_CONTAINER" sh -c 'test -x /usr/local/bin/start-ruoyi-web.sh && sh /usr/local/bin/start-ruoyi-web.sh' \
      || echo 'WARNING: web services did not restart; inspect their container logs.' >&2
  fi
  if [ "$SCREEN_STOPPED" = true ]; then
    docker exec "$SCREEN_CONTAINER" sh -c 'test -x /usr/local/bin/start-ruoyi-screen.sh && sh /usr/local/bin/start-ruoyi-screen.sh' \
      || echo 'WARNING: screen service did not restart; inspect its container logs.' >&2
  fi
  exit "$status"
}
trap recover_services ERR

cd "$PACKAGE_ROOT"
sha256sum -c SHA256SUMS

for container in "$DB_CONTAINER" "$WEB_CONTAINER" "$SCREEN_CONTAINER"; do
  test "$(docker inspect -f '{{.State.Running}}' "$container")" = true
done

read -rsp 'MySQL password: ' MYSQL_PASSWORD
echo
mysql_query() {
  docker exec -e MYSQL_PWD="$MYSQL_PASSWORD" "$DB_CONTAINER" \
    mysql --protocol=TCP -h127.0.0.1 -P3306 "-u$MYSQL_USER" --default-character-set=utf8mb4 \
    -N -B carbon_emissions -e "$1"
}
mysql_query 'SELECT 1;'
monthly_tables=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('emission_collection_node_data_month','emission_calc_node_summary_month','emission_company_energy_summary_month');")
if [ "$monthly_tables" != 3 ]; then
  echo "ERROR: expected monthly analysis tables are missing ($monthly_tables/3). No application files were changed." >&2
  exit 1
fi

for container in "$WEB_CONTAINER" "$SCREEN_CONTAINER"; do
  docker exec "$container" sh -c 'command -v java >/dev/null && command -v nginx >/dev/null && command -v pgrep >/dev/null'
done
docker exec "$WEB_CONTAINER" sh -c 'test -f /etc/carbon-integration.env && test -x /usr/local/bin/start-ruoyi-web.sh && test -x /usr/local/lib/carbon-integration/runtime-common.sh'
docker exec "$SCREEN_CONTAINER" sh -c 'test -f /home/goview/sqllite/goview.db && test -x /usr/local/bin/start-ruoyi-screen.sh && test -x /usr/local/lib/carbon-integration/runtime-common.sh'
test -s web-main/jar/ruoyi-admin.jar
test -s web-main/jar/carbon-emission-model.jar
test -s web-main/html/dist/index.html
test -s web-screen/html/dist/index.html

docker exec "$WEB_CONTAINER" rm -rf "$STAGE"
docker exec "$SCREEN_CONTAINER" rm -rf "$STAGE"
docker exec "$WEB_CONTAINER" mkdir -p "$STAGE/web-main/jar" "$STAGE/web-main/html/dist" "$STAGE/web-main/renderer/carbon_report_agent"
docker exec "$SCREEN_CONTAINER" mkdir -p "$STAGE/web-screen/html/dist"
docker cp web-main/jar/. "$WEB_CONTAINER:$STAGE/web-main/jar/"
docker cp web-main/html/dist/. "$WEB_CONTAINER:$STAGE/web-main/html/dist/"
docker cp web-main/renderer/carbon_report_agent/. "$WEB_CONTAINER:$STAGE/web-main/renderer/carbon_report_agent/"
docker cp web-screen/html/dist/. "$SCREEN_CONTAINER:$STAGE/web-screen/html/dist/"

docker exec "$WEB_CONTAINER" sh -c '. /usr/local/lib/carbon-integration/runtime-common.sh; stop_java ruoyi-admin.jar; stop_java carbon-emission-model.jar; stop_java uncertainty-app.jar; stop_java prediction-platform.jar; stop_process "prediction-engine/scripts/run_api.py"'
WEB_STOPPED=true
docker exec "$SCREEN_CONTAINER" sh -c '. /usr/local/lib/carbon-integration/runtime-common.sh; stop_java goview.war'
SCREEN_STOPPED=true

docker exec "$WEB_CONTAINER" sh -c 'set -eu; rm -rf /home/ruoyi/projects/ruoyi-ui; mv "$1/web-main/html/dist" /home/ruoyi/projects/ruoyi-ui; cp "$1/web-main/jar/ruoyi-admin.jar" /home/ruoyi/ruoyi-admin.jar; cp "$1/web-main/jar/carbon-emission-model.jar" /home/ruoyi/carbon-emission-model.jar; rm -rf /home/ruoyi/renderer/carbon_report_agent; cp -r "$1/web-main/renderer/carbon_report_agent" /home/ruoyi/renderer/' sh "$STAGE"
docker exec "$SCREEN_CONTAINER" sh -c 'set -eu; rm -rf /home/goview/projects/goview; mv "$1/web-screen/html/dist" /home/goview/projects/goview' sh "$STAGE"

docker exec "$WEB_CONTAINER" chmod -R a+rX /home/ruoyi/projects/ruoyi-ui
docker exec "$SCREEN_CONTAINER" chmod -R a+rX /home/goview/projects/goview
docker exec "$WEB_CONTAINER" sh /usr/local/bin/start-ruoyi-web.sh
WEB_STOPPED=false
docker exec "$SCREEN_CONTAINER" sh /usr/local/bin/start-ruoyi-screen.sh
SCREEN_STOPPED=false

wait_http() {
  local url=$1 code= round
  for round in $(seq 1 120); do
    code=$(curl -sS --connect-timeout 3 -m 5 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)
    case "$code" in 200|401|403) echo "PASS $url -> $code"; return 0 ;; esac
    sleep 1
  done
  echo "ERROR: service did not become healthy: $url -> ${code:-connection-error}" >&2
  return 1
}
wait_http "http://127.0.0.1:$WEB_HOST_PORT/"
wait_http "http://127.0.0.1:$WEB_HOST_PORT/carbon-model/"
wait_http "http://127.0.0.1:$SCREEN_HOST_PORT/"
docker exec "$WEB_CONTAINER" sh -c 'pgrep -x java >/dev/null && nginx -t'
docker exec "$SCREEN_CONTAINER" sh -c 'pgrep -x java >/dev/null && nginx -t'
docker exec "$WEB_CONTAINER" rm -rf "$STAGE"
docker exec "$SCREEN_CONTAINER" rm -rf "$STAGE"
unset MYSQL_PASSWORD
echo 'Update completed. No SQL was executed and no server backup was created.'
