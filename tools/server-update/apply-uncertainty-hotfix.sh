#!/bin/sh
set -eu

PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DB_CONTAINER=${DB_CONTAINER:-ruoyi-db}
WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
WEB_HOST_PORT=${WEB_HOST_PORT:-53221}
MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD:-}
UPDATE_ID=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=${BACKUP_DIR:-/opt/ruoyi-backups/uncertainty-hotfix-$UPDATE_ID}

if [ -z "$MYSQL_ROOT_PASSWORD" ]; then
  echo 'MYSQL_ROOT_PASSWORD is required.' >&2
  exit 1
fi

for container in "$DB_CONTAINER" "$WEB_CONTAINER"; do
  test "$(docker inspect -f '{{.State.Running}}' "$container")" = true || {
    echo "Container is not running: $container" >&2
    exit 1
  }
done
test -s "$PACKAGE_ROOT/uncertainty-app.jar"
test -s "$PACKAGE_ROOT/V2__bit_compatibility.sql"
mkdir -p "$BACKUP_DIR"

echo 'Checking database connection...'
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" \
  mysql --protocol=TCP -h127.0.0.1 -P3306 -uroot \
  --default-character-set=utf8mb4 carbon_emissions -e 'SELECT 1;'

echo "Backing up current uncertainty JAR to $BACKUP_DIR"
docker exec "$WEB_CONTAINER" sh -c 'test -f /home/ruoyi/uncertainty-app.jar'
docker exec "$WEB_CONTAINER" sh -c "cp /home/ruoyi/uncertainty-app.jar /home/ruoyi/uncertainty-app.jar.before-$UPDATE_ID"
docker exec "$WEB_CONTAINER" sh -c "tar -C /home/ruoyi -czf - uncertainty-app.jar uncertainty-app.jar.before-$UPDATE_ID" > "$BACKUP_DIR/uncertainty-jars.tgz"

echo 'Applying idempotent BIT/TINYINT compatibility migration...'
docker cp "$PACKAGE_ROOT/V2__bit_compatibility.sql" "$DB_CONTAINER:/tmp/V2__bit_compatibility.sql"
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" sh -c \
  'mysql --protocol=TCP -h127.0.0.1 -P3306 -uroot --default-character-set=utf8mb4 carbon_emissions < /tmp/V2__bit_compatibility.sql'

echo 'Installing corrected uncertainty JAR...'
docker cp "$PACKAGE_ROOT/uncertainty-app.jar" "$WEB_CONTAINER:/tmp/uncertainty-app.jar"
docker cp "$PACKAGE_ROOT/start-web.sh" "$WEB_CONTAINER:/tmp/start-ruoyi-web.sh"
docker exec -e UPDATE_ID="$UPDATE_ID" "$WEB_CONTAINER" sh -c \
  'cp /tmp/uncertainty-app.jar /home/ruoyi/uncertainty-app.jar && tr -d "\\r" < /tmp/start-ruoyi-web.sh > /tmp/start-ruoyi-web.lf && cp /tmp/start-ruoyi-web.lf /usr/local/bin/start-ruoyi-web.sh && chmod 700 /usr/local/bin/start-ruoyi-web.sh'

echo 'Restarting application runtimes...'
docker exec "$WEB_CONTAINER" sh -c 'sh /usr/local/bin/start-ruoyi-web.sh'

last_code=000
for _ in $(seq 1 90); do
  last_code=$(curl -sS --connect-timeout 3 -m 5 -o /dev/null -w '%{http_code}' \
    "http://127.0.0.1:$WEB_HOST_PORT/uncertainty/uncertainty-wizard.html" 2>/dev/null || true)
  case ",$last_code," in
    *,200,*)
      echo "PASS uncertainty endpoint -> $last_code"
      echo "Backup: $BACKUP_DIR"
      exit 0
      ;;
  esac
  sleep 1
done

echo "FAIL uncertainty endpoint -> $last_code" >&2
docker exec "$WEB_CONTAINER" sh -c \
  'pgrep -af uncertainty-app.jar || true; tail -n 200 /home/ruoyi/logs/uncertainty-app.log 2>/dev/null || true' >&2
echo "Backup: $BACKUP_DIR" >&2
exit 1
