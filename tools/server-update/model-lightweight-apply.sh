#!/bin/sh
set -eu

WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
UPDATE_ID=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=${BACKUP_DIR:-/opt/ruoyi-backups/model-light-$UPDATE_ID}
PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STAGING=/tmp/ruoyi-model-light-$UPDATE_ID

mkdir -p "$BACKUP_DIR"
(cd "$PACKAGE_ROOT" && sha256sum -c SHA256SUMS)
docker inspect -f '{{.State.Running}}' "$WEB_CONTAINER" | grep -qx true
docker exec "$WEB_CONTAINER" sh -c 'test -f /etc/carbon-integration.env && test -f /usr/local/lib/carbon-integration/runtime-common.sh'

echo '备份当前碳模型 JAR、前端和日志...'
docker exec "$WEB_CONTAINER" sh -c 'tar --ignore-failed-read -C / -czf - home/ruoyi/carbon-emission-model.jar home/ruoyi/projects/carbon-model home/ruoyi/logs/carbon-emission-model.log' > "$BACKUP_DIR/model-before.tgz"

echo '停止碳模型进程...'
docker exec "$WEB_CONTAINER" sh -c '. /usr/local/lib/carbon-integration/runtime-common.sh; stop_java carbon-emission-model.jar'

docker exec "$WEB_CONTAINER" mkdir -p "$STAGING"
docker cp "$PACKAGE_ROOT/web-main/." "$WEB_CONTAINER:$STAGING/"
docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  mkdir -p /home/ruoyi/projects
  rm -rf /home/ruoyi/projects/carbon-model.new
  cp "$1/jar/carbon-emission-model.jar" /home/ruoyi/carbon-emission-model.jar.new
  cp -r "$1/html/carbon-model" /home/ruoyi/projects/carbon-model.new
  chmod a+r /home/ruoyi/carbon-emission-model.jar.new
  chmod -R a+rX /home/ruoyi/projects/carbon-model.new
  mv /home/ruoyi/carbon-emission-model.jar.new /home/ruoyi/carbon-emission-model.jar
  rm -rf /home/ruoyi/projects/carbon-model
  mv /home/ruoyi/projects/carbon-model.new /home/ruoyi/projects/carbon-model
  rm -rf "$1"
' sh "$STAGING"

echo '仅重启碳模型进程...'
docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  . /etc/carbon-integration.env
  . /usr/local/lib/carbon-integration/runtime-common.sh
  cd /home/ruoyi
  export LANG=${LANG:-C.UTF-8}
  export LC_ALL=${LC_ALL:-C.UTF-8}
  export PYTHONUTF8=1
  export PYTHONIOENCODING=utf-8
  nohup env \
    CARBON_SERVER_PORT=8082 \
    CARBON_DB_URL="jdbc:mysql://$DB_HOST:3306/carbon_emissions?useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&characterEncoding=UTF-8&useUnicode=true&connectionCollation=utf8mb4_unicode_ci" \
    CARBON_DB_USERNAME="$APP_DB_USERNAME" CARBON_DB_PASSWORD="$APP_DB_PASSWORD" \
    SPRING_SQL_INIT_MODE=never CARBON_SQL_INIT_MODE=never SPRING_PROFILES_ACTIVE=job \
    RUOYI_SECURITY_ENABLED=true RUOYI_SECURITY_ENDPOINT=http://127.0.0.1:8081/internal/security/context \
    RUOYI_AUDIT_ENABLED=true RUOYI_AUDIT_ENDPOINT=http://127.0.0.1:8081/internal/carbon/audit/operation \
    PYTHON_PATH="$REPORT_PYTHON" STEAM_CALCULATOR_SCRIPT=/home/ruoyi/steam_calculator.py \
    java -jar /home/ruoyi/carbon-emission-model.jar > /home/ruoyi/logs/carbon-emission-model.log 2>&1 < /dev/null &
'
sleep 3
docker exec "$WEB_CONTAINER" sh -c 'pgrep -f "carbon-emission-model.jar" >/dev/null'
echo "模型轻量更新完成。备份目录: $BACKUP_DIR"
