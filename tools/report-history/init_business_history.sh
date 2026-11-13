#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage:
  bash init_business_history.sh --container MYSQL_CONTAINER [--database carbon_emissions] [--user root] [--backup-dir PATH]
  bash init_business_history.sh --local [--host 127.0.0.1] [--port 3306] [--database carbon_emissions] [--user root] [--backup-dir PATH]

The password is requested interactively and is never accepted on the command line.
The importer backs up all affected tables, inserts only missing rows, and rolls back on conflicts.
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
[[ $db_user =~ ^[a-zA-Z0-9_.@-]+$ ]] || { echo 'Invalid database user' >&2; exit 2; }
[[ $db_port =~ ^[0-9]+$ ]] || { echo 'Invalid port' >&2; exit 2; }
if [[ $mode == docker ]]; then
  [[ $container =~ ^[a-zA-Z0-9_.-]+$ ]] || { echo 'Invalid container name' >&2; exit 2; }
  command -v docker >/dev/null || { echo 'docker is unavailable' >&2; exit 2; }
  [[ $(docker inspect --format '{{.State.Running}}' "$container") == true ]] || { echo 'Database container is not running' >&2; exit 2; }
else
  command -v mysql >/dev/null || { echo 'mysql client is unavailable' >&2; exit 2; }
  command -v mysqldump >/dev/null || { echo 'mysqldump is unavailable' >&2; exit 2; }
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
sql_file="$script_dir/business_history.sql"
checksum_file="$script_dir/business_history.sql.sha256"
[[ -s $sql_file ]] || { echo "Missing $sql_file" >&2; exit 2; }
if command -v sha256sum >/dev/null && [[ -f $checksum_file ]]; then
  (cd "$script_dir" && sha256sum -c "$(basename "$checksum_file")")
fi

work_dir=$(mktemp -d "${TMPDIR:-/tmp}/ruoyi-history.XXXXXXXX")
local_cnf="$work_dir/client.cnf"
remote_cnf="/tmp/ruoyi-history-$(date +%Y%m%d%H%M%S)-$$.cnf"
cleanup() {
  if [[ $mode == docker ]]; then docker exec -u 0 "$container" rm -f "$remote_cnf" >/dev/null 2>&1 || true; fi
  rm -f "$local_cnf"
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

tables=(
  emission_collection_record emission_collection_record_audit
  emission_calculation_template emission_calculation_data_state emission_calculation_node
  emission_collection_node_data emission_calc_node_summary report_task report_emission_source
  report_activity_fuel report_activity_electricity report_activity_heat report_workload
  report_equipment report_monitoring_device report_import_batch report_file report_generation_job
)

run_client mysql --batch --skip-column-names --database="$database" --execute='SELECT VERSION(),DATABASE();'
if [[ -z $backup_dir ]]; then backup_dir="$(pwd)/business-history-backup-$(date +%Y%m%d-%H%M%S)-$$"; fi
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
dump_opts=(--single-transaction --skip-lock-tables --skip-triggers --skip-add-locks --skip-disable-keys --complete-insert --hex-blob --no-tablespaces --set-gtid-purged=OFF)
run_client mysqldump "${dump_opts[@]}" "$database" "${tables[@]}" > "$backup_dir/affected-tables.before.sql"
[[ -s $backup_dir/affected-tables.before.sql ]] || { echo 'Backup is empty; import cancelled' >&2; exit 1; }

echo 'Backup completed. Applying insert-only business history transaction...'
run_client mysql --batch --database="$database" < "$sql_file" | tee "$backup_dir/initialization.log"
grep -q '^BUSINESS_HISTORY_INIT_OK' "$backup_dir/initialization.log" || { echo 'Success marker missing; inspect initialization.log' >&2; exit 1; }
printf 'Completed. Private backup and log directory: %s\n' "$backup_dir"

