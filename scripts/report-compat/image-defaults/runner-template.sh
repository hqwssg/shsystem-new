#!/usr/bin/env bash
# Self-contained carbon report defaults initializer. MySQL 8.x, Bash, no Python.
set -euo pipefail
umask 077
write_sql() {
cat <<'__CARBON_REPORT_DEFAULTS_SQL__'
__EMBEDDED_SQL__
__CARBON_REPORT_DEFAULTS_SQL__
}
usage() {
  cat <<'USAGE'
Usage:
  bash init_report_images.sh --container MYSQL_CONTAINER [--database carbon_emissions] [--user root] [--backup-dir PATH]
  bash init_report_images.sh --local [--host 127.0.0.1] [--port 3306] [--database carbon_emissions] [--user root] [--backup-dir PATH]
The script prompts for the database password. No password is accepted on the command line.
It backs up the three companies default images, then fills only missing image roles.
Use --container for a Docker database, --local for a host/remote MySQL client connection.
USAGE
}
mode=''; container=''; database='carbon_emissions'; db_user='root'; db_host='127.0.0.1'; db_port='3306'; backup_dir=''
while (($#)); do
  case "$1" in
    --container) [[ $# -ge 2 ]] || { usage; exit 2; }; mode='docker'; container=$2; shift 2;;
    --local) mode='local'; shift;;
    --database) [[ $# -ge 2 ]] || { usage; exit 2; }; database=$2; shift 2;;
    --user) [[ $# -ge 2 ]] || { usage; exit 2; }; db_user=$2; shift 2;;
    --host) [[ $# -ge 2 ]] || { usage; exit 2; }; db_host=$2; shift 2;;
    --port) [[ $# -ge 2 ]] || { usage; exit 2; }; db_port=$2; shift 2;;
    --backup-dir) [[ $# -ge 2 ]] || { usage; exit 2; }; backup_dir=$2; shift 2;;
    --help|-h) usage; exit 0;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage; exit 2;;
  esac
done
[[ $mode == docker || $mode == local ]] || { usage; exit 2; }
[[ $database =~ ^[a-zA-Z0-9_]+$ ]] || { echo 'Invalid database name' >&2; exit 2; }
[[ $db_user =~ ^[a-zA-Z0-9_.@-]+$ ]] || { echo 'Invalid database user name' >&2; exit 2; }
[[ $db_port =~ ^[0-9]+$ ]] || { echo 'Invalid port' >&2; exit 2; }
if [[ $mode == docker ]]; then
  [[ $container =~ ^[a-zA-Z0-9_.-]+$ ]] || { echo 'Invalid container name' >&2; exit 2; }
  command -v docker >/dev/null || { echo 'docker is unavailable' >&2; exit 2; }
  [[ $(docker inspect --format '{{.State.Running}}' "$container") == true ]] || { echo 'Database container is not running' >&2; exit 2; }
else
  command -v mysql >/dev/null || { echo 'mysql client is unavailable' >&2; exit 2; }
  command -v mysqldump >/dev/null || { echo 'mysqldump is unavailable' >&2; exit 2; }
fi
work_dir=$(mktemp -d "${TMPDIR:-/tmp}/carbon-report-init.XXXXXXXX")
local_cnf="$work_dir/client.cnf"; local_sql="$work_dir/defaults.sql"
remote_cnf="/tmp/carbon-report-init-$(date +%Y%m%d%H%M%S)-$$.cnf"
cleanup() {
  if [[ $mode == docker ]]; then docker exec -u 0 "$container" rm -f "$remote_cnf" >/dev/null 2>&1 || true; fi
  rm -f "$local_cnf" "$local_sql"
  rmdir "$work_dir" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'Target: mode=%s database=%s user=%s container=%s\n' "$mode" "$database" "$db_user" "${container:-host-client}"
read -r -s -p 'Database password: ' db_password
printf '\n'
escaped=${db_password//\\/\\\\}; escaped=${escaped//\"/\\\"}
printf '[client]\nuser=%s\npassword="%s"\ndefault-character-set=utf8mb4\n' "$db_user" "$escaped" > "$local_cnf"
unset db_password escaped
chmod 600 "$local_cnf"
write_sql > "$local_sql"
if [[ $mode == docker ]]; then
  docker cp "$local_cnf" "$container:$remote_cnf" >/dev/null
  docker exec -u 0 "$container" chmod 600 "$remote_cnf"
fi
run_client() {
  local executable=$1; shift
  if [[ $mode == docker ]]; then
    docker exec -u 0 -i "$container" "$executable" --defaults-extra-file="$remote_cnf" "$@"
  else
    "$executable" --defaults-extra-file="$local_cnf" --host="$db_host" --port="$db_port" "$@"
  fi
}
run_client mysql --batch --skip-column-names --database="$database" --execute='SELECT VERSION(),DATABASE();'
if [[ -z $backup_dir ]]; then backup_dir="$(pwd)/report-images-backup-$(date +%Y%m%d-%H%M%S)-$$"; fi
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
dump_opts=(--single-transaction --skip-lock-tables --no-create-info --skip-triggers --skip-add-locks --skip-disable-keys --complete-insert --hex-blob --no-tablespaces --set-gtid-purged=OFF)
backup_where="__BACKUP_WHERE__"
run_client mysqldump "${dump_opts[@]}" --where="$backup_where" "$database" report_file > "$backup_dir/images.before.sql"
echo 'Backups saved. Applying report defaults transaction...'
run_client mysql --batch --database="$database" < "$local_sql" | tee "$backup_dir/initialization.log"
grep -q '^REPORT_IMAGES_INIT_OK' "$backup_dir/initialization.log" || { echo 'Success marker missing: inspect initialization.log' >&2; exit 1; }
printf 'Completed. Private backup and log directory: %s\n' "$backup_dir"
