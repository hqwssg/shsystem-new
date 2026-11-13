#!/bin/sh
set -eu

WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
UPDATE_ID=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=${BACKUP_DIR:-/opt/ruoyi-backups/report-subject-$UPDATE_ID}
PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STAGING=/tmp/report-subject-update-$UPDATE_ID

mkdir -p "$BACKUP_DIR"
(cd "$PACKAGE_ROOT" && sha256sum -c SHA256SUMS)
test -s "$PACKAGE_ROOT/web-main/jar/ruoyi-admin.jar"
test -f "$PACKAGE_ROOT/web-main/html/dist/index.html"
docker inspect -f '{{.State.Running}}' "$WEB_CONTAINER" | grep -qx true

echo "Backing up main service to $BACKUP_DIR ..."
docker exec "$WEB_CONTAINER" sh -c \
  'tar --ignore-failed-read -C / -czf - home/ruoyi/ruoyi-admin.jar home/ruoyi/projects/ruoyi-ui home/ruoyi/logs/ruoyi-admin.log' \
  > "$BACKUP_DIR/web-before.tgz"

docker exec "$WEB_CONTAINER" rm -rf "$STAGING"
docker exec "$WEB_CONTAINER" mkdir -p "$STAGING/jar" "$STAGING/html"
docker cp "$PACKAGE_ROOT/web-main/jar/ruoyi-admin.jar" "$WEB_CONTAINER:$STAGING/jar/ruoyi-admin.jar"
docker cp "$PACKAGE_ROOT/web-main/html/dist/." "$WEB_CONTAINER:$STAGING/html/"

echo 'Stopping only ruoyi-admin.jar ...'
docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  if [ -f /usr/local/lib/carbon-integration/runtime-common.sh ]; then
    . /usr/local/lib/carbon-integration/runtime-common.sh
    stop_java ruoyi-admin.jar
  else
    for pid in $(pgrep -f "[r]uoyi-admin.jar" || true); do kill "$pid" 2>/dev/null || true; done
  fi
'

docker exec "$WEB_CONTAINER" sh -c "
  set -eu
  rm -rf /home/ruoyi/ruoyi-admin.jar.new /home/ruoyi/projects/ruoyi-ui.new
  cp '$STAGING/jar/ruoyi-admin.jar' /home/ruoyi/ruoyi-admin.jar.new
  cp -r '$STAGING/html' /home/ruoyi/projects/ruoyi-ui.new
  mv /home/ruoyi/ruoyi-admin.jar /home/ruoyi/ruoyi-admin.jar.previous
  mv /home/ruoyi/ruoyi-admin.jar.new /home/ruoyi/ruoyi-admin.jar
  # The durable pre-update backup is stored under BACKUP_DIR above. Remove
  # only the disposable container-local previous frontend before replacing it;
  # otherwise mv fails when an earlier update left this directory behind.
  rm -rf /home/ruoyi/projects/ruoyi-ui.previous
  mv /home/ruoyi/projects/ruoyi-ui /home/ruoyi/projects/ruoyi-ui.previous
  mv /home/ruoyi/projects/ruoyi-ui.new /home/ruoyi/projects/ruoyi-ui
  chmod a+rx /home /home/ruoyi /home/ruoyi/projects
  chmod -R a+rX /home/ruoyi/projects/ruoyi-ui
  rm -rf '$STAGING'
"

echo 'Starting only ruoyi-admin.jar ...'
docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  if [ -f /etc/carbon-integration.env ]; then
    . /etc/carbon-integration.env
  fi
  mkdir -p /home/ruoyi/logs
  nohup env java ${JAVA_OPTS:-} -jar /home/ruoyi/ruoyi-admin.jar \
    > /home/ruoyi/logs/ruoyi-admin.log 2>&1 < /dev/null &
  pgrep -f "[r]uoyi-admin.jar" >/dev/null
  ready=0
  i=0
  while [ "$i" -lt 60 ]; do
    if python3 -c "import socket; s=socket.create_connection(('127.0.0.1', 8081), 1); s.close()" 2>/dev/null; then
      ready=1
      break
    fi
    sleep 2
    i=$((i + 1))
  done
  if [ "$ready" -ne 1 ]; then
    echo 'ruoyi-admin.jar did not open port 8081; recent log:' >&2
    tail -n 80 /home/ruoyi/logs/ruoyi-admin.log >&2 || true
    echo 'Rolling back the main JAR and frontend ...' >&2
    for pid in $(pgrep -f "[r]uoyi-admin.jar" || true); do
      kill "$pid" 2>/dev/null || true
    done
    rm -rf /home/ruoyi/ruoyi-admin.jar
    if [ -f /home/ruoyi/ruoyi-admin.jar.previous ]; then
      mv /home/ruoyi/ruoyi-admin.jar.previous /home/ruoyi/ruoyi-admin.jar
    fi
    rm -rf /home/ruoyi/projects/ruoyi-ui
    if [ -d /home/ruoyi/projects/ruoyi-ui.previous ]; then
      mv /home/ruoyi/projects/ruoyi-ui.previous /home/ruoyi/projects/ruoyi-ui
    fi
    if [ -f /etc/carbon-integration.env ]; then
      . /etc/carbon-integration.env
    fi
    nohup env java ${JAVA_OPTS:-} -jar /home/ruoyi/ruoyi-admin.jar \
      > /home/ruoyi/logs/ruoyi-admin.log 2>&1 < /dev/null &
    nginx -t && nginx -s reload 2>/dev/null || true
    exit 1
  fi
  nginx -t
  nginx -s reload 2>/dev/null || true
'

echo "Lightweight report-subject update completed. Backup: $BACKUP_DIR"
