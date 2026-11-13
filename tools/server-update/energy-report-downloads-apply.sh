#!/bin/sh
set -eu

WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
WEB_HOST_PORT=${WEB_HOST_PORT:-53221}
PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
UPDATE_ID=$(date +%Y%m%d-%H%M%S)
STAGING=/tmp/energy-report-update-$UPDATE_ID
BACKUP_DIR=${BACKUP_DIR:-/opt/ruoyi-backups/energy-report-$UPDATE_ID}
MIN_FREE_KB=${MIN_FREE_KB:-262144}
ROLLBACK_NEEDED=false

rollback() {
  if [ "$ROLLBACK_NEEDED" != true ]; then
    return
  fi
  echo '更新失败，正在恢复更新前的主前端和重空协同算法目录...' >&2
  docker exec "$WEB_CONTAINER" sh -c '
    set -eu
    ui_before=$1
    engine_before=$2
    if [ -d "$ui_before" ]; then
      rm -rf /home/ruoyi/projects/ruoyi-ui
      mv "$ui_before" /home/ruoyi/projects/ruoyi-ui
    fi
    if [ -d "$engine_before" ]; then
      rm -rf /home/ruoyi/energy-engine
      mv "$engine_before" /home/ruoyi/energy-engine
    fi
    test -x /usr/local/bin/start-ruoyi-web.sh
    sh /usr/local/bin/start-ruoyi-web.sh
  ' sh "/home/ruoyi/projects/ruoyi-ui.before-$UPDATE_ID" "/home/ruoyi/energy-engine.before-$UPDATE_ID" || true
}
trap rollback EXIT HUP INT TERM

cd "$PACKAGE_ROOT"
sha256sum -c SHA256SUMS
docker inspect -f '{{.State.Running}}' "$WEB_CONTAINER" | grep -qx true

free_kb=$(docker exec "$WEB_CONTAINER" sh -c "df -Pk /home/ruoyi | awk 'NR==2 {print \$4}'")
if [ "$free_kb" -lt "$MIN_FREE_KB" ]; then
  echo "容器可用空间不足：${free_kb}KB，至少需要 ${MIN_FREE_KB}KB。未修改任何线上文件。" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
docker exec "$WEB_CONTAINER" rm -rf "$STAGING"
docker exec "$WEB_CONTAINER" mkdir -p "$STAGING"
docker cp "$PACKAGE_ROOT/web-main/html/dist" "$WEB_CONTAINER:$STAGING/ruoyi-ui"
docker cp "$PACKAGE_ROOT/web-main/energy-engine" "$WEB_CONTAINER:$STAGING/energy-engine"

echo '使用容器实际 Python 与字体环境执行中文字形预检...'
docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  fc-cache -f >/dev/null 2>&1 || true
  rm -rf /root/.cache/matplotlib /home/ruoyi/.cache/matplotlib
  PYTHONPATH="$1/energy-engine" /opt/carbon-report-venv/bin/python \
    "$1/energy-engine/tools/verify_matplotlib_chinese_font.py" \
    --output "$1/rolling-font-check.png"
' sh "$STAGING"

echo "备份更新前的前端和算法目录到 $BACKUP_DIR ..."
docker exec "$WEB_CONTAINER" sh -c \
  'tar --ignore-failed-read -C / -czf - home/ruoyi/projects/ruoyi-ui home/ruoyi/energy-engine' \
  > "$BACKUP_DIR/web-ui-energy-before.tgz"

docker exec "$WEB_CONTAINER" sh -c '
  if [ -x /usr/local/bin/start-ruoyi-web.sh ]; then
    . /usr/local/lib/carbon-integration/runtime-common.sh
    stop_java ruoyi-admin.jar
  fi
'

ROLLBACK_NEEDED=true
docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  staging=$1
  update_id=$2
  ui_before=/home/ruoyi/projects/ruoyi-ui.before-$update_id
  engine_before=/home/ruoyi/energy-engine.before-$update_id
  rm -rf "$ui_before" "$engine_before"
  mv /home/ruoyi/projects/ruoyi-ui "$ui_before"
  mv /home/ruoyi/energy-engine "$engine_before"
  mv "$staging/ruoyi-ui" /home/ruoyi/projects/ruoyi-ui
  mv "$staging/energy-engine" /home/ruoyi/energy-engine
  chmod -R a+rX /home/ruoyi/projects/ruoyi-ui /home/ruoyi/energy-engine
  test -x /usr/local/bin/start-ruoyi-web.sh
  sh /usr/local/bin/start-ruoyi-web.sh
' sh "$STAGING" "$UPDATE_ID"

sleep 5
curl -fsS --max-time 15 "http://127.0.0.1:$WEB_HOST_PORT/" >/dev/null

echo '核对实际 Java 进程使用的 ENERGY_PROJECT_ROOT ...'
docker exec "$WEB_CONTAINER" sh -c '
  pid=$(pgrep -f "[r]uoyi-admin.jar" | head -n 1)
  test -n "$pid"
  tr "\000" "\n" < "/proc/$pid/environ" | grep -Fx "ENERGY_PROJECT_ROOT=/home/ruoyi/energy-engine"
  PYTHONPATH=/home/ruoyi/energy-engine /opt/carbon-report-venv/bin/python \
    /home/ruoyi/energy-engine/tools/verify_matplotlib_chinese_font.py \
    --output /tmp/rolling-font-check-after-update.png
'

ROLLBACK_NEEDED=false
trap - EXIT HUP INT TERM
docker exec "$WEB_CONTAINER" rm -rf \
  "/home/ruoyi/projects/ruoyi-ui.before-$UPDATE_ID" \
  "/home/ruoyi/energy-engine.before-$UPDATE_ID" \
  "$STAGING"

echo "定向更新完成。可回滚备份：$BACKUP_DIR/web-ui-energy-before.tgz"
echo '请新建一个“滚动重调度”任务验收新生成的 rolling_state_timeline.png；旧任务图片不会自动重绘。'
