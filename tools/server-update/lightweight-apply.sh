#!/bin/sh
set -eu

WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
DB_CONTAINER=${DB_CONTAINER:-ruoyi-db}
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD:?请设置 MYSQL_ROOT_PASSWORD}
UPDATE_ID=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=${BACKUP_DIR:-/opt/ruoyi-backups/light-$UPDATE_ID}
PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STAGING=/tmp/ruoyi-light-$UPDATE_ID
mkdir -p "$BACKUP_DIR"

(cd "$PACKAGE_ROOT" && sha256sum -c SHA256SUMS)
docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" | grep -qx true
docker inspect -f '{{.State.Running}}' "$WEB_CONTAINER" | grep -qx true

echo '备份数据库和主服务文件...'
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" \
  mysqldump --protocol=TCP -h127.0.0.1 -P3306 -uroot --default-character-set=utf8mb4 \
  --single-transaction --routines --triggers carbon_emissions > "$BACKUP_DIR/database.sql"
docker exec "$WEB_CONTAINER" sh -c 'tar --ignore-failed-read -C / -czf - home/ruoyi/ruoyi-admin.jar home/ruoyi/projects/ruoyi-ui home/ruoyi/energy-engine home/ruoyi/single_train_recovery_agent home/ruoyi/single_train_algorithm home/ruoyi/renderer/carbon_report_agent' > "$BACKUP_DIR/web-before.tgz"

echo '停止主后台并执行两项增量迁移...'
docker exec "$WEB_CONTAINER" sh -c 'if [ -x /usr/local/bin/start-ruoyi-web.sh ]; then . /usr/local/lib/carbon-integration/runtime-common.sh; stop_java ruoyi-admin.jar; fi'
for file in "$PACKAGE_ROOT"/mysql/migrations/*.sql; do
  base=$(basename "$file")
  docker cp "$file" "$DB_CONTAINER:/tmp/$base"
  docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" sh -c \
    'mysql --protocol=TCP -h127.0.0.1 -P3306 -uroot --default-character-set=utf8mb4 carbon_emissions < "$1"' sh "/tmp/$base"
done

echo '替换主后台、前端、重空算法和报告渲染器...'
docker exec "$WEB_CONTAINER" mkdir -p "$STAGING"
docker cp "$PACKAGE_ROOT/web-main/." "$WEB_CONTAINER:$STAGING/"
docker cp "$PACKAGE_ROOT/scripts/start-web.sh" "$WEB_CONTAINER:$STAGING/start-web.sh"
docker exec "$WEB_CONTAINER" sh -c '
  set -eu
  /opt/carbon-report-venv/bin/python -m pip install --no-index --find-links "$1/wheels" -r "$1/requirements-cli.txt"
  mkdir -p /home/ruoyi/projects /home/ruoyi/renderer
  rm -rf /home/ruoyi/projects/ruoyi-ui.new /home/ruoyi/energy-engine.new /home/ruoyi/single_train_recovery_agent.new /home/ruoyi/single_train_algorithm.new /home/ruoyi/renderer/carbon_report_agent.new
  cp -r "$1/html/dist" /home/ruoyi/projects/ruoyi-ui.new
  cp -r "$1/energy-engine" /home/ruoyi/energy-engine.new
  cp -r "$1/single-train-engine" /home/ruoyi/single_train_recovery_agent.new
  cp -r "$1/single-train-algorithm" /home/ruoyi/single_train_algorithm.new
  cp -r "$1/renderer/carbon_report_agent" /home/ruoyi/renderer/carbon_report_agent.new
  cp "$1/jar/ruoyi-admin.jar" /home/ruoyi/ruoyi-admin.jar.new
  cp "$1/start-web.sh" /usr/local/bin/start-ruoyi-web.sh
  chmod 700 /usr/local/bin/start-ruoyi-web.sh
  rm -rf /home/ruoyi/projects/ruoyi-ui /home/ruoyi/energy-engine /home/ruoyi/single_train_recovery_agent /home/ruoyi/single_train_algorithm /home/ruoyi/renderer/carbon_report_agent
  mv /home/ruoyi/projects/ruoyi-ui.new /home/ruoyi/projects/ruoyi-ui
  mv /home/ruoyi/energy-engine.new /home/ruoyi/energy-engine
  mv /home/ruoyi/single_train_recovery_agent.new /home/ruoyi/single_train_recovery_agent
  mv /home/ruoyi/single_train_algorithm.new /home/ruoyi/single_train_algorithm
  mv /home/ruoyi/renderer/carbon_report_agent.new /home/ruoyi/renderer/carbon_report_agent
  mv /home/ruoyi/ruoyi-admin.jar.new /home/ruoyi/ruoyi-admin.jar
  chmod -R a+rX /home/ruoyi/projects/ruoyi-ui /home/ruoyi/energy-engine /home/ruoyi/single_train_recovery_agent /home/ruoyi/single_train_algorithm /home/ruoyi/renderer/carbon_report_agent
  if [ -x /usr/local/bin/start-ruoyi-web.sh ]; then sh /usr/local/bin/start-ruoyi-web.sh; else echo "缺少 /usr/local/bin/start-ruoyi-web.sh" >&2; exit 1; fi
' sh "$STAGING"

echo "轻量更新完成。备份目录: $BACKUP_DIR"
