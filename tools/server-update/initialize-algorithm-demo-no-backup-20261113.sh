#!/bin/sh
set -eu
PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DB_CONTAINER=${DB_CONTAINER:-ruoyi-db}
DB_NAME=${DB_NAME:-carbon_emissions}
DB_USER=${DB_USER:-root}
DEMO_ACCOUNT=${DEMO_ACCOUNT:-admin}
test "$#" -eq 0 || { echo 'Use DB_CONTAINER, DB_NAME, DB_USER and DEMO_ACCOUNT environment variables; no positional arguments supported' >&2; exit 2; }
: "${MYSQL_ROOT_PASSWORD:?Set MYSQL_ROOT_PASSWORD in the shell before running}"
SQL="$PACKAGE_ROOT/payload/optional-data-init/init_algorithm_demo.sql"
test -s "$SQL"
docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" | grep -qx true
cd "$PACKAGE_ROOT"
sha256sum -c SHA256SUMS >/dev/null
account_hex=$(printf '%s' "$DEMO_ACCOUNT" | od -An -v -tx1 | tr -d ' \n')
test -n "$account_hex"
{
  printf 'SET @algorithm_seed_account=CONVERT(0x%s USING utf8mb4);\n' "$account_hex"
  cat "$SQL"
} | docker exec -i -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" mysql --protocol=TCP -h127.0.0.1 -P3306 -u"$DB_USER" --default-character-set=utf8mb4 --max-allowed-packet=256M "$DB_NAME"
docker exec -i -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" mysql --protocol=TCP -h127.0.0.1 -P3306 -u"$DB_USER" --default-character-set=utf8mb4 "$DB_NAME" < "$PACKAGE_ROOT/payload/optional-data-init/verify_algorithm_demo.sql"
echo 'Completed: original transaction/conflict guards retained; no backup and no tasks/results created.'
