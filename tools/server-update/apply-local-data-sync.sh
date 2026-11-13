#!/bin/bash
set -Eeuo pipefail

PACKAGE_ROOT=$(cd -- "$(dirname -- "$0")" && pwd)
DB_CONTAINER=${DB_CONTAINER:-ruoyi-db}
WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
SCREEN_CONTAINER=${SCREEN_CONTAINER:-ruoyi-screen}
WEB_HOST_PORT=${WEB_HOST_PORT:-53221}
SCREEN_HOST_PORT=${SCREEN_HOST_PORT:-53231}
SYNC_ID=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=${BACKUP_DIR:-/opt/ruoyi-backups/local-sync-$SYNC_ID}
DB_DUMP="$PACKAGE_ROOT/data/carbon_emissions.sql"
GOVIEW_DB="$PACKAGE_ROOT/data/goview.db"
GOVIEW_UPLOAD="$PACKAGE_ROOT/data/goview-upload"

trap 'echo "ERROR: local data sync failed at line $LINENO. Backups: $BACKUP_DIR. Do not reinitialize the database." >&2' ERR

if [ -z "${MYSQL_ROOT_PASSWORD:-}" ]; then
  read -rsp 'MySQL/MariaDB root password: ' MYSQL_ROOT_PASSWORD
  echo
fi

cd "$PACKAGE_ROOT"
sha256sum -c SHA256SUMS
test -s "$DB_DUMP"
test -s "$GOVIEW_DB"
for container in "$DB_CONTAINER" "$WEB_CONTAINER" "$SCREEN_CONTAINER"; do
  test "$(docker inspect -f '{{.State.Running}}' "$container")" = true
done

echo "Stopping application writers..."
docker exec "$WEB_CONTAINER" sh -c '. /usr/local/lib/carbon-integration/runtime-common.sh; stop_java ruoyi-admin.jar; stop_java carbon-emission-model.jar'
docker exec "$SCREEN_CONTAINER" sh -c '. /usr/local/lib/carbon-integration/runtime-common.sh; stop_java goview.war'

echo "Backing up server state to $BACKUP_DIR"
umask 077
mkdir -p "$BACKUP_DIR"
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" \
  mysqldump --protocol=TCP -h127.0.0.1 -P3306 -uroot --default-character-set=utf8mb4 \
  --single-transaction --routines --triggers carbon_emissions > "$BACKUP_DIR/database.sql"
test -s "$BACKUP_DIR/database.sql"
docker cp "$SCREEN_CONTAINER:/home/goview/sqllite" "$BACKUP_DIR/goview-sqllite"
docker exec "$SCREEN_CONTAINER" tar -C /home/goview -czf - upload > "$BACKUP_DIR/goview-upload.tgz"
docker exec "$WEB_CONTAINER" tar -C /home/ruoyi -czf - uploadPath > "$BACKUP_DIR/main-upload.tgz"

echo "Replacing carbon_emissions with the local snapshot..."
docker cp "$DB_DUMP" "$DB_CONTAINER:/tmp/local-carbon-emissions.sql"
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" sh -c \
  'mysql --protocol=TCP -h127.0.0.1 -P3306 -uroot --default-character-set=utf8mb4 < /tmp/local-carbon-emissions.sql'
docker exec "$WEB_CONTAINER" redis-cli -h127.0.0.1 FLUSHALL >/dev/null

echo "Replacing GoView projects and resources with the local snapshot..."
docker exec "$SCREEN_CONTAINER" sh -c 'rm -f /home/goview/sqllite/goview.db /home/goview/sqllite/goview.db-wal /home/goview/sqllite/goview.db-shm; rm -rf /home/goview/upload/*; mkdir -p /home/goview/sqllite /home/goview/upload'
docker cp "$GOVIEW_DB" "$SCREEN_CONTAINER:/home/goview/sqllite/goview.db"
if [ -d "$GOVIEW_UPLOAD" ]; then
  docker cp "$GOVIEW_UPLOAD/." "$SCREEN_CONTAINER:/home/goview/upload/"
fi
docker exec "$SCREEN_CONTAINER" chmod 600 /home/goview/sqllite/goview.db

echo "Restarting services..."
docker exec "$WEB_CONTAINER" sh /usr/local/bin/start-ruoyi-web.sh
docker exec "$SCREEN_CONTAINER" sh /usr/local/bin/start-ruoyi-screen.sh

wait_http() {
  local url=$1 codes=$2 code round
  for round in $(seq 1 180); do
    code=$(curl -sS --connect-timeout 3 -m 5 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)
    case ",$codes," in *",$code,"*) echo "PASS $url -> $code"; return 0 ;; esac
    sleep 1
  done
  echo "FAIL $url -> ${code:-connection-error}" >&2
  return 1
}

wait_http "http://127.0.0.1:$WEB_HOST_PORT/" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/prod-api/code" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/carbon-model/" 200
wait_http "http://127.0.0.1:$SCREEN_HOST_PORT/" 200
wait_http "http://127.0.0.1:$SCREEN_HOST_PORT/api/goview/sys/getOssInfo" 200,401,403

docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" \
  mysql --protocol=TCP -h127.0.0.1 -P3306 -uroot --default-character-set=utf8mb4 carbon_emissions -e \
  "SELECT COUNT(*) AS tables_count FROM information_schema.tables WHERE table_schema='carbon_emissions'; SELECT COUNT(*) AS config_count FROM sys_config; SELECT COUNT(*) AS node_count FROM emission_node; SELECT COUNT(*) AS collection_count FROM emission_collection_record;"

echo "Local data snapshot synchronized successfully."
echo "Backups: $BACKUP_DIR"
