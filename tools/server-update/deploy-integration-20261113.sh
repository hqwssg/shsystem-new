#!/bin/sh
set -eu

PACKAGE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DB_CONTAINER=${DB_CONTAINER:-ruoyi-db}
WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
WEB_HOST_PORT=${WEB_HOST_PORT:-53221}
DB_NAME=${DB_NAME:-carbon_emissions}
DB_USER=${DB_USER:-root}
STAGING=/tmp/carbon-integration-20261113

case "${1:-}" in ''|--check) ;; *) echo 'Usage: sh deploy-integration-20261113.sh [--check]' >&2; exit 2;; esac
cd "$PACKAGE_ROOT"
sha256sum -c SHA256SUMS
command -v docker >/dev/null
command -v sha256sum >/dev/null
command -v curl >/dev/null
: "${MYSQL_ROOT_PASSWORD:?Set MYSQL_ROOT_PASSWORD in the shell before running}"
test "$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER")" = true
test "$(docker inspect -f '{{.State.Running}}' "$WEB_CONTAINER")" = true
docker exec "$WEB_CONTAINER" test -x /opt/carbon-report-venv/bin/python
docker exec "$WEB_CONTAINER" test -r /etc/carbon-integration.env
docker exec "$WEB_CONTAINER" test -x /usr/local/bin/start-ruoyi-web.sh
docker exec "$WEB_CONTAINER" test -r /usr/local/lib/carbon-integration/runtime-common.sh
docker exec "$WEB_CONTAINER" sh -c 'grep -q "root   /home/ruoyi/projects/ruoyi-ui;" /etc/nginx/nginx.conf && grep -q "root   /home/ruoyi/projects;" /etc/nginx/nginx.conf'
docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" mysql --protocol=TCP -h127.0.0.1 -P3306 -u"$DB_USER" --default-character-set=utf8mb4 "$DB_NAME" -Nse 'SELECT VERSION();' >/dev/null

# Do not switch algorithm code while a task is queued or running.
active=$(docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" mysql --protocol=TCP -h127.0.0.1 -P3306 -u"$DB_USER" --default-character-set=utf8mb4 "$DB_NAME" -Nse "SELECT (SELECT COUNT(*) FROM energy_run WHERE status IN ('pending','validating','running')) + (SELECT COUNT(*) FROM single_run WHERE status IN ('queued','running'));" | tr -d '\r')
case "$active" in ''|*[!0-9]*) echo 'FAIL: could not verify active algorithm task count' >&2; exit 1;; esac
if [ "$active" -ne 0 ]; then echo "FAIL: $active algorithm task(s) are pending or running; wait for completion and retry" >&2; exit 1; fi

docker exec "$WEB_CONTAINER" sh -eu -c "rm -rf '$STAGING' && mkdir -p '$STAGING'/ruoyi-ui '$STAGING'/carbon-model '$STAGING'/energy-engine '$STAGING'/single-train-engine '$STAGING'/single-train-algorithm '$STAGING'/carbon-emission-model"
for item in ruoyi-ui carbon-model energy-engine single-train-engine single-train-algorithm carbon-emission-model; do
  docker cp "$PACKAGE_ROOT/payload/$item/." "$WEB_CONTAINER:$STAGING/$item/"
done
docker exec "$WEB_CONTAINER" sh -eu -c '
  stage="$1"
  test -s "$stage/ruoyi-ui/index.html"
  test -s "$stage/carbon-model/index.html"
  test -s "$stage/carbon-emission-model/carbon-emission-model.jar"
  test -f "$stage/energy-engine/run_project.py"
  test -f "$stage/single-train-engine/worker.py"
  test -f "$stage/single-train-algorithm/api_contract.json"
  /opt/carbon-report-venv/bin/python - "$stage" <<"PY"
import ast, pathlib, sys, zipfile
root = pathlib.Path(sys.argv[1])
if not zipfile.is_zipfile(root / "carbon-emission-model/carbon-emission-model.jar"):
    raise SystemExit("FAIL: backend payload is not a valid JAR")
for group in ("energy-engine", "single-train-engine", "single-train-algorithm"):
    for path in (root / group).rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
sys.path[:0] = [str(root / "single-train-algorithm"), "/home/ruoyi/single_train_algorithm",
                str(root / "energy-engine"), "/home/ruoyi/energy-engine"]
from eco_driving.optimizer.eco_driving_optimizer import EcoDrivingOptimizer
from eco_driving.integration.regenerative_interface import evaluate_regenerative_recovery
print("PASS: staged JAR, Python syntax, eco-driving imports and runtime dependencies")
PY
' sh "$STAGING"

if [ "${1:-}" = --check ]; then
  echo 'CHECK_OK: package, runtime paths, database connection, idle task queues, and staged source syntax verified; installed files unchanged'
  exit 0
fi

docker exec "$WEB_CONTAINER" sh -eu -c '
  stage="$1"
  overlay() { src=$1; dst=$2; mkdir -p "$dst"; cp -R "$stage/$src/." "$dst/"; }
  replace_static() {
    src=$1; dst=$2
    case "$dst" in /home/ruoyi/projects/ruoyi-ui|/home/ruoyi/projects/carbon-model) ;; *) exit 1;; esac
    # These two directories contain only published frontend files, never uploads or database files.
    test -s "$stage/$src/index.html"
    test ! -L "$dst"
    mkdir -p "$dst"
    find "$dst" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    cp -R "$stage/$src/." "$dst/"
  }
  overlay energy-engine /home/ruoyi/energy-engine
  overlay single-train-engine /home/ruoyi/single_train_recovery_agent
  overlay single-train-algorithm /home/ruoyi/single_train_algorithm
  replace_static carbon-model /home/ruoyi/projects/carbon-model
  replace_static ruoyi-ui /home/ruoyi/projects/ruoyi-ui
  # Windows tar/copy permissions must not prevent the nginx worker from reading the new assets.
  for dst in /home/ruoyi/projects/ruoyi-ui /home/ruoyi/projects/carbon-model; do
    find "$dst" -type d -exec chmod 755 {} +
    find "$dst" -type f -exec chmod 644 {} +
  done
  install -m 0644 "$stage/carbon-emission-model/carbon-emission-model.jar" /home/ruoyi/carbon-emission-model.jar
  rm -rf "$stage"
' sh "$STAGING"

# Use the site's existing launcher so its private environment and persistent keys remain authoritative.
docker exec "$WEB_CONTAINER" sh -lc 'sh /usr/local/bin/start-ruoyi-web.sh'
attempt=0
while [ "$attempt" -lt 90 ]; do
  attempt=$((attempt + 1))
  code=$(curl --silent --connect-timeout 2 --max-time 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$WEB_HOST_PORT/" || true)
  if { [ "$code" = 200 ] || [ "$code" = 301 ] || [ "$code" = 302 ]; } &&
     docker exec "$WEB_CONTAINER" /opt/carbon-report-venv/bin/python -c '
import socket
for port in (80, 8081, 8082, 8085, 8086, 8090):
    with socket.create_connection(("127.0.0.1", port), timeout=1): pass
' >/dev/null 2>&1; then
    echo "PASS: web HTTP status $code; application ports 80, 8081, 8082, 8085, 8086, 8090 accept connections"
    echo 'No database migration, demo data initialization, server backup, or container recreation was performed.'
    exit 0
  fi
  sleep 1
done
echo 'FAIL: application health check timed out; inspect /home/ruoyi/logs/*.log inside ruoyi-web' >&2
exit 1
