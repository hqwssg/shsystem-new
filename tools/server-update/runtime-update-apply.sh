#!/bin/bash
set -Eeuo pipefail

DB_CONTAINER=${DB_CONTAINER:-ruoyi-db}
WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
SCREEN_CONTAINER=${SCREEN_CONTAINER:-ruoyi-screen}
INTERNAL_NETWORK=${INTERNAL_NETWORK:-ruoyi-internal}
UPDATE_ID=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=${BACKUP_DIR:-/opt/ruoyi-backups/runtime-$UPDATE_ID}
PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STAGING=/tmp/runtime-update-$UPDATE_ID
WEB_BACKUP=$BACKUP_DIR/web-before.tgz
SCREEN_BACKUP=$BACKUP_DIR/screen-before.tgz
WEB_CONTAINER_BACKUP=/tmp/runtime-web-backup-$UPDATE_ID.tgz
SCREEN_CONTAINER_BACKUP=/tmp/runtime-screen-backup-$UPDATE_ID.tgz
FAILED=1

mkdir -p "$BACKUP_DIR"
(cd "$PACKAGE_ROOT" && sha256sum -c SHA256SUMS)
test -s "$PACKAGE_ROOT/web-main/jar/ruoyi-admin.jar"
test -s "$PACKAGE_ROOT/web-main/jar/carbon-emission-model.jar"
test -s "$PACKAGE_ROOT/web-screen/jar/goview.war"
test -f "$PACKAGE_ROOT/web-main/html/dist/index.html"
test -d "$PACKAGE_ROOT/web-main/html/dist/static"
test -f "$PACKAGE_ROOT/web-main/html/carbon-model/index.html"
test -f "$PACKAGE_ROOT/web-screen/html/dist/index.html"

for container in "$DB_CONTAINER" "$WEB_CONTAINER" "$SCREEN_CONTAINER"; do
  docker inspect -f '{{.State.Running}}' "$container" | grep -qx true
done

docker network inspect "$INTERNAL_NETWORK" >/dev/null 2>&1 || docker network create "$INTERNAL_NETWORK" >/dev/null
for container in "$DB_CONTAINER" "$WEB_CONTAINER" "$SCREEN_CONTAINER"; do
  docker network connect "$INTERNAL_NETWORK" "$container" >/dev/null 2>&1 || true
done

docker exec -e EXPECTED_DB_HOST="$DB_CONTAINER" "$WEB_CONTAINER" sh -c '
  set -eu
  f=/etc/carbon-integration.env
  if [ -f "$f" ]; then
    sed -i '/^DB_HOST=/d' "$f"
    printf 'DB_HOST=%s\n' "$EXPECTED_DB_HOST" >> "$f"
  fi
'
docker exec -e EXPECTED_WEB_HOST="$WEB_CONTAINER" "$SCREEN_CONTAINER" sh -c '
  set -eu
  f=/etc/carbon-integration.env
  if [ -f "$f" ]; then
    sed -i '/^WEB_INTERNAL_HOST=/d' "$f"
    printf 'WEB_INTERNAL_HOST=%s\n' "$EXPECTED_WEB_HOST" >> "$f"
  fi
'

docker exec "$WEB_CONTAINER" sh -c \
  'tar --ignore-failed-read -C / -czf - home/ruoyi/ruoyi-admin.jar home/ruoyi/carbon-emission-model.jar home/ruoyi/projects/ruoyi-ui home/ruoyi/projects/carbon-model home/ruoyi/energy-engine home/ruoyi/single_train_recovery_agent home/ruoyi/single_train_algorithm home/ruoyi/renderer/carbon_report_agent home/ruoyi/steam_calculator.py usr/local/bin/start-ruoyi-web.sh usr/local/lib/carbon-integration/runtime-common.sh' \
  > "$BACKUP_DIR/web-before.tgz"
docker exec "$SCREEN_CONTAINER" sh -c \
  'tar --ignore-failed-read -C / -czf - home/goview/goview.war home/goview/projects/goview usr/local/bin/start-ruoyi-screen.sh usr/local/lib/carbon-integration/runtime-common.sh' \
  > "$BACKUP_DIR/screen-before.tgz"
docker inspect "$DB_CONTAINER" > "$BACKUP_DIR/db-container.json"
docker inspect "$WEB_CONTAINER" > "$BACKUP_DIR/web-container.json"
docker inspect "$SCREEN_CONTAINER" > "$BACKUP_DIR/screen-container.json"

restore_and_start() {
  set +e
  docker exec "$WEB_CONTAINER" sh -c '. /usr/local/lib/carbon-integration/runtime-common.sh 2>/dev/null || true; stop_java ruoyi-admin.jar; stop_java carbon-emission-model.jar' >/dev/null 2>&1
  docker exec "$SCREEN_CONTAINER" sh -c '. /usr/local/lib/carbon-integration/runtime-common.sh 2>/dev/null || true; stop_java goview.war' >/dev/null 2>&1
  docker cp "$WEB_BACKUP" "$WEB_CONTAINER:$WEB_CONTAINER_BACKUP" >/dev/null 2>&1
  docker cp "$SCREEN_BACKUP" "$SCREEN_CONTAINER:$SCREEN_CONTAINER_BACKUP" >/dev/null 2>&1
  docker exec "$WEB_CONTAINER" sh -c "tar -xzf '$WEB_CONTAINER_BACKUP' -C /; rm -f '$WEB_CONTAINER_BACKUP'" >/dev/null 2>&1
  docker exec "$SCREEN_CONTAINER" sh -c "tar -xzf '$SCREEN_CONTAINER_BACKUP' -C /; rm -f '$SCREEN_CONTAINER_BACKUP'" >/dev/null 2>&1
  docker exec "$WEB_CONTAINER" sh -c 'test -x /usr/local/bin/start-ruoyi-web.sh && sh /usr/local/bin/start-ruoyi-web.sh' >/dev/null 2>&1
  docker exec "$SCREEN_CONTAINER" sh -c 'test -x /usr/local/bin/start-ruoyi-screen.sh && sh /usr/local/bin/start-ruoyi-screen.sh' >/dev/null 2>&1
}
on_error() {
  code=$?
  echo "Runtime update failed. Application backups: $BACKUP_DIR" >&2
  if [ -s "$WEB_BACKUP" ] && [ -s "$SCREEN_BACKUP" ]; then restore_and_start; fi
  exit "$code"
}
trap on_error INT TERM HUP ERR

echo 'Stopping application writers while keeping the database running ...'
docker exec "$WEB_CONTAINER" sh -c '. /usr/local/lib/carbon-integration/runtime-common.sh; stop_java ruoyi-admin.jar; stop_java carbon-emission-model.jar'
docker exec "$SCREEN_CONTAINER" sh -c '. /usr/local/lib/carbon-integration/runtime-common.sh; stop_java goview.war'

docker exec -e EXPECTED_DB_HOST="$DB_CONTAINER" "$WEB_CONTAINER" python3 -c \
  'import os,socket; s=socket.create_connection((os.environ["EXPECTED_DB_HOST"],3306),10); s.close()'

docker exec "$WEB_CONTAINER" rm -rf "$STAGING"
docker exec "$SCREEN_CONTAINER" rm -rf "$STAGING"
docker exec "$WEB_CONTAINER" mkdir -p "$STAGING/web-main" "$STAGING/scripts"
docker exec "$SCREEN_CONTAINER" mkdir -p "$STAGING/web-screen" "$STAGING/scripts"
docker cp "$PACKAGE_ROOT/web-main/." "$WEB_CONTAINER:$STAGING/web-main/"
docker cp "$PACKAGE_ROOT/scripts/." "$WEB_CONTAINER:$STAGING/scripts/"
docker cp "$PACKAGE_ROOT/web-screen/." "$SCREEN_CONTAINER:$STAGING/web-screen/"
docker cp "$PACKAGE_ROOT/scripts/." "$SCREEN_CONTAINER:$STAGING/scripts/"

docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  for d in /home/ruoyi/projects/ruoyi-ui /home/ruoyi/projects/carbon-model /home/ruoyi/energy-engine /home/ruoyi/single_train_recovery_agent /home/ruoyi/single_train_algorithm /home/ruoyi/renderer/carbon_report_agent; do
    test -e "$d" && mv "$d" "$d.before-$2" || true
  done
  for f in /home/ruoyi/ruoyi-admin.jar /home/ruoyi/carbon-emission-model.jar /home/ruoyi/steam_calculator.py; do
    test -e "$f" && mv "$f" "$f.before-$2" || true
  done
  mkdir -p /home/ruoyi/projects /home/ruoyi/renderer /home/ruoyi/python
  cp -r "$1/web-main/html/dist" /home/ruoyi/projects/ruoyi-ui
  cp -r "$1/web-main/html/carbon-model" /home/ruoyi/projects/carbon-model
  cp -r "$1/web-main/energy-engine" /home/ruoyi/energy-engine
  cp -r "$1/web-main/single-train-engine" /home/ruoyi/single_train_recovery_agent
  cp -r "$1/web-main/single-train-algorithm" /home/ruoyi/single_train_algorithm
  cp -r "$1/web-main/renderer/carbon_report_agent" /home/ruoyi/renderer/carbon_report_agent
  cp "$1/web-main/jar/ruoyi-admin.jar" /home/ruoyi/ruoyi-admin.jar
  cp "$1/web-main/jar/carbon-emission-model.jar" /home/ruoyi/carbon-emission-model.jar
  cp "$1/web-main/python/steam_calculator.py" /home/ruoyi/steam_calculator.py
  cp "$1/scripts/runtime-common.sh" /usr/local/lib/carbon-integration/runtime-common.sh
  cp "$1/scripts/start-web.sh" /usr/local/bin/start-ruoyi-web.sh
  chmod 700 /usr/local/bin/start-ruoyi-web.sh
  chmod -R a+rX /home/ruoyi/projects /home/ruoyi/energy-engine /home/ruoyi/single_train_recovery_agent /home/ruoyi/single_train_algorithm /home/ruoyi/renderer/carbon_report_agent
' sh "$STAGING" "$UPDATE_ID"

docker exec "$SCREEN_CONTAINER" sh -c '
  set -eu
  test -e /home/goview/goview.war && mv /home/goview/goview.war /home/goview/goview.war.before-$2 || true
  test -e /home/goview/projects/goview && mv /home/goview/projects/goview /home/goview/projects/goview.before-$2 || true
  cp "$1/web-screen/jar/goview.war" /home/goview/goview.war
  mkdir -p /home/goview/projects
  cp -r "$1/web-screen/html/dist" /home/goview/projects/goview
  cp "$1/scripts/runtime-common.sh" /usr/local/lib/carbon-integration/runtime-common.sh
  cp "$1/scripts/start-screen.sh" /usr/local/bin/start-ruoyi-screen.sh
  chmod 700 /usr/local/bin/start-ruoyi-screen.sh
  chmod -R a+rX /home/goview/projects/goview
' sh "$STAGING" "$UPDATE_ID"

docker exec "$WEB_CONTAINER" sh -c 'sh /usr/local/bin/start-ruoyi-web.sh'
docker exec "$SCREEN_CONTAINER" sh -c 'sh /usr/local/bin/start-ruoyi-screen.sh'
docker exec "$WEB_CONTAINER" pgrep -f '[r]uoyi-admin.jar'
docker exec "$WEB_CONTAINER" pgrep -f '[c]arbon-emission-model.jar'
docker exec "$SCREEN_CONTAINER" pgrep -f '[g]oview.war'
docker exec "$WEB_CONTAINER" sh -c 'python3 -c "import socket; s=socket.create_connection((\"127.0.0.1\",8081),5); s.close()"'
docker exec "$WEB_CONTAINER" sh -c 'python3 -c "import socket; s=socket.create_connection((\"127.0.0.1\",8082),5); s.close()"'
docker exec "$SCREEN_CONTAINER" sh -c 'python3 -c "import socket; s=socket.create_connection((\"127.0.0.1\",8083),5); s.close()"'
docker exec "$WEB_CONTAINER" nginx -t
docker exec "$SCREEN_CONTAINER" nginx -t
rm -rf "$STAGING"
FAILED=0
trap - INT TERM HUP ERR
echo "Full runtime update completed. No SQL was executed. Backups: $BACKUP_DIR"
