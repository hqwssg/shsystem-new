#!/bin/sh
set -eu

WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STAGING=/tmp/prediction-admin-permission-update-$$

(cd "$PACKAGE_ROOT" && sha256sum -c SHA256SUMS)
test -s "$PACKAGE_ROOT/web-main/jar/ruoyi-admin.jar"
docker inspect -f '{{.State.Running}}' "$WEB_CONTAINER" | grep -qx true

docker exec "$WEB_CONTAINER" rm -rf "$STAGING"
docker exec "$WEB_CONTAINER" mkdir -p "$STAGING"
docker cp "$PACKAGE_ROOT/web-main/jar/ruoyi-admin.jar" \
  "$WEB_CONTAINER:$STAGING/ruoyi-admin.jar.new"

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
  mv '$STAGING/ruoyi-admin.jar.new' /home/ruoyi/ruoyi-admin.jar
  rm -rf '$STAGING'
"

docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  if [ -f /etc/carbon-integration.env ]; then . /etc/carbon-integration.env; fi
  mkdir -p /home/ruoyi/logs
  nohup env java ${JAVA_OPTS:-} -jar /home/ruoyi/ruoyi-admin.jar \
    > /home/ruoyi/logs/ruoyi-admin.log 2>&1 < /dev/null &
  pgrep -f "[r]uoyi-admin.jar" >/dev/null
  ready=0
  i=0
  while [ "$i" -lt 60 ]; do
    if python3 -c "import socket; s=socket.create_connection((\"127.0.0.1\", 8081), 1); s.close()" 2>/dev/null; then
      ready=1
      break
    fi
    sleep 2
    i=$((i + 1))
  done
  if [ "$ready" -ne 1 ]; then
    echo "ruoyi-admin.jar did not open port 8081" >&2
    tail -n 80 /home/ruoyi/logs/ruoyi-admin.log >&2 || true
    exit 1
  fi
  nginx -t
  nginx -s reload 2>/dev/null || true
'

echo 'Prediction administrator permission update completed.'
