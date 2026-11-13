#!/bin/bash
set -Eeuo pipefail
PACKAGE_ROOT=$(cd -- "$(dirname -- "$0")" && pwd)
DB_CONTAINER=${DB_CONTAINER:-ruoyi-db}
WEB_CONTAINER=${WEB_CONTAINER:-ruoyi-web}
SCREEN_CONTAINER=${SCREEN_CONTAINER:-ruoyi-screen}
INTERNAL_NETWORK=${INTERNAL_NETWORK:-ruoyi-internal}
WEB_HOST_PORT=${WEB_HOST_PORT:-53221}
SCREEN_HOST_PORT=${SCREEN_HOST_PORT:-53231}
APPLY_PERMISSION_RESET=${APPLY_PERMISSION_RESET:-false}
RESUME_FROM_MIGRATION=
UPDATE_ID=$(date +%Y%m%d-%H%M%S)
STAGING=/opt/carbon-update/$UPDATE_ID
TEMP_DIR=$(mktemp -d)
PAUSED_SCREEN=false
WEB_STOPPED=false
SCREEN_STOPPED=false
cleanup() {
  if [ "$PAUSED_SCREEN" = true ]; then docker unpause "$SCREEN_CONTAINER" >/dev/null || true; fi
  rm -rf -- "$TEMP_DIR"
}
recover_on_error() {
  local code=$?
  trap - ERR
  echo "ERROR: update failed at line $LINENO. No server backup was created; preserve this terminal log. Do not reinitialize the database." >&2
  if [ "$WEB_STOPPED" = true ]; then
    echo 'Attempting to restart management and model services...' >&2
    docker exec "$WEB_CONTAINER" sh -c 'test -x /usr/local/bin/start-ruoyi-web.sh && sh /usr/local/bin/start-ruoyi-web.sh' \
      || echo 'WARNING: management service restart failed; inspect the container logs.' >&2
  fi
  if [ "$SCREEN_STOPPED" = true ]; then
    echo 'Attempting to restart GoView service...' >&2
    docker exec "$SCREEN_CONTAINER" sh -c 'test -x /usr/local/bin/start-ruoyi-screen.sh && sh /usr/local/bin/start-ruoyi-screen.sh' \
      || echo 'WARNING: GoView service restart failed; inspect the container logs.' >&2
  fi
  exit "$code"
}
trap cleanup EXIT
trap recover_on_error ERR

if [ -z "${MYSQL_ROOT_PASSWORD:-}" ]; then
  read -rsp 'MySQL/MariaDB root password: ' MYSQL_ROOT_PASSWORD
  echo
fi
case "${1:-}" in
  ''|--check)
    if [ "$#" -gt 1 ]; then echo 'Usage: bash deploy-update.sh [--check | --resume-from MIGRATION_FILE]' >&2; exit 1; fi
    ;;
  --resume-from)
    if [ "$#" -ne 2 ] || [[ "$2" == */* ]] || [[ "$2" == *..* ]] ||
       [ ! -f "$PACKAGE_ROOT/mysql/migrations/$2" ]; then
      echo 'Usage: bash deploy-update.sh --resume-from MIGRATION_FILE' >&2
      exit 1
    fi
    RESUME_FROM_MIGRATION=$2
    ;;
  *) echo 'Usage: bash deploy-update.sh [--check | --resume-from MIGRATION_FILE]' >&2; exit 1 ;;
esac
echo "Verifying package: $PACKAGE_ROOT"
(cd "$PACKAGE_ROOT" && sha256sum -c SHA256SUMS > "$TEMP_DIR/checksums.log")
for container in "$DB_CONTAINER" "$WEB_CONTAINER" "$SCREEN_CONTAINER"; do
  test "$(docker inspect -f '{{.State.Running}}' "$container")" = true
done
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

# User-defined networks provide Docker DNS by container name. The default
# bridge network does not, which causes ruoyi-db lookups to fail.
docker network inspect "$INTERNAL_NETWORK" >/dev/null 2>&1 || docker network create "$INTERNAL_NETWORK" >/dev/null
for container in "$DB_CONTAINER" "$WEB_CONTAINER" "$SCREEN_CONTAINER"; do
  docker network connect "$INTERNAL_NETWORK" "$container" >/dev/null 2>&1 || true
done

mysql_query() {
  docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" \
    mysql --protocol=TCP -h127.0.0.1 -P3306 -uroot --default-character-set=utf8mb4 -N -B carbon_emissions -e "$1"
}
mysql_query 'SELECT VERSION(); SELECT COUNT(*) FROM sys_user; SELECT COUNT(*) FROM emission_template;'
# Use stable Docker DNS names by default. Container IPs can change whenever a
# service is recreated; persisting an inspected IP in carbon-integration.env
# causes later restarts to fail with MySQL "Connection refused".
DB_HOST=${DB_HOST:-$DB_CONTAINER}
WEB_INTERNAL_HOST=${WEB_INTERNAL_HOST:-$WEB_CONTAINER}
test -n "$DB_HOST"
test -n "$WEB_INTERNAL_HOST"
echo "Database internal address: $DB_HOST:3306"
echo "Management internal address: $WEB_INTERNAL_HOST:8081"

if [ "$APPLY_PERMISSION_RESET" = true ]; then
  # Never turn unrelated real accounts into fixed-ID sample accounts.
  collisions=$(mysql_query "SELECT COUNT(*) FROM sys_user WHERE user_id BETWEEN 2 AND 9 AND NOT ((user_id=2 AND user_name IN ('ry','yuanping_admin')) OR (user_id=3 AND user_name='suning_admin') OR (user_id=4 AND user_name='locomotive_admin') OR (user_id=5 AND user_name='carbon_accountant') OR (user_id=6 AND user_name='data_entry') OR (user_id=7 AND user_name='data_reviewer') OR (user_id=8 AND user_name='carbon_auditor') OR (user_id=9 AND user_name='screen_operator'));")
  role_collisions=$(mysql_query "SELECT COUNT(*) FROM sys_role WHERE role_id BETWEEN 1 AND 8 AND role_key NOT IN ('admin','common','company_admin','region_admin','department_admin','carbon_accountant','carbon_data_entry','carbon_reviewer','carbon_auditor','screen_operator');")
  department_users=$(mysql_query 'SELECT COUNT(*) FROM sys_user WHERE user_id > 9 AND dept_id BETWEEN 100 AND 109;')
  post_collisions=$(mysql_query "SELECT COUNT(*) FROM sys_post WHERE post_id BETWEEN 1 AND 8 AND post_code NOT IN ('ceo','se','hr','user','company_manager','region_manager','department_manager','carbon_accounting','data_entry','data_review','carbon_audit','screen_ops');")
  notice_collisions=$(mysql_query "SELECT COUNT(*) FROM sys_notice WHERE notice_id IN (1,2,3) AND notice_title NOT LIKE '%若依%' AND notice_content NOT LIKE '%ruoyi.vip%' AND notice_title <> '碳排放管理系统使用通知';")
  if [ "$collisions" != 0 ] || [ "$role_collisions" != 0 ] || [ "$department_users" != 0 ] || [ "$post_collisions" != 0 ] || [ "$notice_collisions" != 0 ]; then
    echo 'ERROR: permission reset would overwrite real users/roles or remove a used department.' >&2
    echo 'Stop here and remap the optional SQL to unused IDs; do not bypass this check.' >&2
    exit 1
  fi
fi
docker exec "$WEB_CONTAINER" sh -c 'java -version; command -v nginx; command -v redis-server; command -v pgrep'
docker exec "$SCREEN_CONTAINER" sh -c 'java -version; command -v nginx; command -v pgrep; test -f /home/goview/sqllite/goview.db'
CHECK_REPORT_PYTHON=${REPORT_PYTHON:-python3}
docker exec -e REPORT_PYTHON="$CHECK_REPORT_PYTHON" "$WEB_CONTAINER" sh -c \
  '"$REPORT_PYTHON" -c "import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 12)"'
docker exec -i "$WEB_CONTAINER" sh -s < "$PACKAGE_ROOT/scripts/verify-libreoffice.sh"
if [ "${1:-}" = --check ]; then
  echo 'Preflight passed. No application or database updates have been performed.'
  echo 'For Python, use REPORT_PYTHON=python3.11 if the container default is older than 3.10.'
  exit 0
fi
: "${WEB_PUBLIC_URL:?Set WEB_PUBLIC_URL to the browser-visible management URL}"
: "${SCREEN_PUBLIC_URL:?Set SCREEN_PUBLIC_URL to the browser-visible screen URL}"
WEB_PUBLIC_URL=${WEB_PUBLIC_URL%/}
SCREEN_PUBLIC_URL=${SCREEN_PUBLIC_URL%/}
APP_DB_USERNAME=${APP_DB_USERNAME:-root}
APP_DB_PASSWORD=${APP_DB_PASSWORD:-$MYSQL_ROOT_PASSWORD}
REPORT_PYTHON=${REPORT_PYTHON:-python3}
if [ -z "${GOVIEW_AUDIT_SECRET:-}" ]; then
  GOVIEW_AUDIT_SECRET=$(openssl rand -hex 32)
fi
if [ -z "${PREDICTION_API_KEY:-}" ]; then
  PREDICTION_API_KEY=$(openssl rand -hex 32)
fi
export GOVIEW_AUDIT_SECRET
export PREDICTION_API_KEY

echo 'Preparing runtimes before applying database migrations...'
for container in "$WEB_CONTAINER" "$SCREEN_CONTAINER"; do
  docker exec "$container" mkdir -p "$STAGING/scripts"
  docker cp "$PACKAGE_ROOT/scripts/." "$container:$STAGING/scripts/"
done
docker exec "$WEB_CONTAINER" mkdir -p "$STAGING/web-main"
docker cp "$PACKAGE_ROOT/web-main/." "$WEB_CONTAINER:$STAGING/web-main/"
docker exec "$WEB_CONTAINER" mkdir -p "$STAGING/energy-data"
docker cp "$PACKAGE_ROOT/energy-data/." "$WEB_CONTAINER:$STAGING/energy-data/"
docker exec "$WEB_CONTAINER" mkdir -p "$STAGING/verification"
docker cp "$PACKAGE_ROOT/verification/." "$WEB_CONTAINER:$STAGING/verification/"
docker exec "$SCREEN_CONTAINER" mkdir -p "$STAGING/web-screen"
docker cp "$PACKAGE_ROOT/web-screen/." "$SCREEN_CONTAINER:$STAGING/web-screen/"
docker exec -e REPORT_PYTHON="$REPORT_PYTHON" "$WEB_CONTAINER" sh "$STAGING/scripts/container-update.sh" web prepare "$STAGING"
docker exec "$SCREEN_CONTAINER" sh "$STAGING/scripts/container-update.sh" screen prepare "$STAGING"
docker exec -e DB_HOST="$DB_HOST" "$WEB_CONTAINER" /opt/carbon-report-venv/bin/python -c \
  'import os,socket; s=socket.create_connection((os.environ["DB_HOST"],3306),10); s.close()'
docker exec "$SCREEN_CONTAINER" curl -sS --connect-timeout 10 -o /dev/null "http://$WEB_INTERNAL_HOST/"
REPORT_SOFFICE=$(docker exec "$WEB_CONTAINER" sh -c 'command -v libreoffice || command -v soffice')

# Preserve the protected prediction endpoint settings when the integration env file is regenerated.
if docker exec "$WEB_CONTAINER" test -f /etc/carbon-integration.env; then
  CARBON_MONTHLY_REPAIR_ENABLED=$(docker exec "$WEB_CONTAINER" sh -c '. /etc/carbon-integration.env; printf "%s" "${CARBON_MONTHLY_REPAIR_ENABLED:-false}"')
  CARBON_MONTHLY_PREDICTION_URL=$(docker exec "$WEB_CONTAINER" sh -c '. /etc/carbon-integration.env; printf "%s" "${CARBON_MONTHLY_PREDICTION_URL:-}"')
  CARBON_MONTHLY_PREDICTION_API_KEY=$(docker exec "$WEB_CONTAINER" sh -c '. /etc/carbon-integration.env; printf "%s" "${CARBON_MONTHLY_PREDICTION_API_KEY:-}"')
  CARBON_MONTHLY_JLG_TRACTION_CATEGORIES=$(docker exec "$WEB_CONTAINER" sh -c '. /etc/carbon-integration.env; printf "%s" "${CARBON_MONTHLY_JLG_TRACTION_CATEGORIES:-}"')
  CARBON_MONTHLY_JLG_AUXILIARY_CATEGORIES=$(docker exec "$WEB_CONTAINER" sh -c '. /etc/carbon-integration.env; printf "%s" "${CARBON_MONTHLY_JLG_AUXILIARY_CATEGORIES:-}"')
else
  CARBON_MONTHLY_REPAIR_ENABLED=false
  CARBON_MONTHLY_PREDICTION_URL=
  CARBON_MONTHLY_PREDICTION_API_KEY=
  CARBON_MONTHLY_JLG_TRACTION_CATEGORIES=
  CARBON_MONTHLY_JLG_AUXILIARY_CATEGORIES=
fi

# Keep report AI defaults when regenerating the integration environment.
for llm_variable in CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY CARBON_REPORT_LLM_BASE_URL CARBON_REPORT_LLM_MODEL CARBON_REPORT_LLM_API_KEY; do
  if [ -z "${!llm_variable:-}" ]; then
    saved_value=$(docker exec "$WEB_CONTAINER" sh -c 'set -a; if [ -f /etc/carbon-integration.env ]; then . /etc/carbon-integration.env; fi; printenv "$1" || true' sh "$llm_variable")
    printf -v "$llm_variable" '%s' "$saved_value"
  fi
done

echo 'Entering maintenance window: stop business writers before migrations.'
WEB_STOPPED=true
  docker exec "$WEB_CONTAINER" sh -c '. "$1"; stop_java ruoyi-admin.jar; stop_java carbon-emission-model.jar; stop_java uncertainty-app.jar; stop_java prediction-platform.jar; stop_process prediction-engine/scripts/run_api.py' sh "$STAGING/scripts/runtime-common.sh"
SCREEN_STOPPED=true
docker exec "$SCREEN_CONTAINER" sh -c '. "$1"; stop_java goview.war' sh "$STAGING/scripts/runtime-common.sh"

import_file() {
  local file=$1 base
  base=$(basename "$file")
  echo "Applying $base"
  docker cp "$file" "$DB_CONTAINER:/tmp/$base"
  docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$DB_CONTAINER" sh -c \
    'mysql --protocol=TCP -h127.0.0.1 -P3306 -uroot --default-character-set=utf8mb4 carbon_emissions < "$1"' sh "/tmp/$base" \
    > "$TEMP_DIR/$base.log" 2>&1 || { cat "$TEMP_DIR/$base.log" >&2; return 1; }
}
RESUME_REACHED=false
for file in "$PACKAGE_ROOT"/mysql/migrations/*.sql; do
  base=$(basename "$file")
  if [ -n "$RESUME_FROM_MIGRATION" ] && [ "$RESUME_REACHED" = false ]; then
    if [ "$base" = "$RESUME_FROM_MIGRATION" ]; then
      RESUME_REACHED=true
    else
      echo "Skipping $base: before requested resume point $RESUME_FROM_MIGRATION."
      continue
    fi
  fi
  if [ "$base" = "41_local_observation_fixtures.sql" ]; then
    echo 'Skipping 41_local_observation_fixtures.sql: local-only sample data is not a production migration.'
    continue
  fi
  if [ "$(basename "$file")" = "45_energy_tables.sql" ]; then
    energy_tables=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name LIKE 'energy_%';")
    if [ "$energy_tables" -ge 36 ]; then
      echo "Skipping 45_energy_tables.sql: all 36 energy tables already exist."
      continue
    elif [ "$energy_tables" -gt 0 ]; then
      # A previous deployment may have stopped after creating only part of the
      # module. CREATE INDEX statements are not conditionally supported by all
      # MySQL/MariaDB versions, so remove each multi-line index block while
      # allowing CREATE TABLE IF NOT EXISTS to complete the missing tables.
      energy_repair="$TEMP_DIR/45_energy_tables_repair.sql"
      awk 'BEGIN { skip=0 }
        /^CREATE[[:space:]]+(UNIQUE[[:space:]]+)?INDEX[[:space:]]/ { skip=1 }
        skip { if ($0 ~ /;/) skip=0; next }
        { print }' "$file" > "$energy_repair"
      import_file "$energy_repair"
      continue
    fi
  fi
  import_file "$file"
done
if [ -n "$RESUME_FROM_MIGRATION" ] && [ "$RESUME_REACHED" = false ]; then
  echo "ERROR: requested resume migration was not found: $RESUME_FROM_MIGRATION" >&2
  exit 1
fi
calculation_cycle_unique_index=$(mysql_query "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='emission_calculation_template' AND index_name='uk_template_cycle_revision';")
if [ "$calculation_cycle_unique_index" != 0 ]; then
  echo 'ERROR: calculation void migration did not remove uk_template_cycle_revision.' >&2
  exit 1
fi
duplicate_config_keys=$(mysql_query "SELECT COUNT(*) FROM (SELECT config_key FROM sys_config GROUP BY config_key HAVING COUNT(*) > 1) duplicate_keys;")
unique_config_indexes=$(mysql_query "SELECT COUNT(*) FROM (SELECT index_name FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='sys_config' GROUP BY index_name HAVING MAX(non_unique)=0 AND COUNT(*)=1 AND MAX(CASE WHEN column_name='config_key' THEN 1 ELSE 0 END)=1) config_indexes;")
if [ "$duplicate_config_keys" != 0 ] || [ "$unique_config_indexes" = 0 ]; then
  echo "ERROR: sys_config repair verification failed (duplicates=$duplicate_config_keys, unique_indexes=$unique_config_indexes)." >&2
  exit 1
fi
statistics_demo_records=$(mysql_query "SELECT COUNT(*) FROM emission_collection_record WHERE external_record_id LIKE 'STAT-DEMO-%';")
statistics_demo_keys=$(mysql_query "SELECT COUNT(DISTINCT external_record_id) FROM emission_collection_record WHERE external_record_id LIKE 'STAT-DEMO-%';")
if [ "$statistics_demo_records" != 72 ] || [ "$statistics_demo_keys" != 72 ]; then
  echo "ERROR: statistics demo migration is not stable (records=$statistics_demo_records unique_keys=$statistics_demo_keys; expected 72/72)." >&2
  exit 1
fi
manual_review_columns=$(mysql_query "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='emission_collection_record' AND column_name IN ('workflow_status','submitter_id','submitted_at','reviewer_id','reviewed_at','review_comment');")
manual_audit_table=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='emission_collection_record_audit';")
manual_auto_approve_config=$(mysql_query "SELECT COUNT(*) FROM sys_config WHERE config_key='carbon.collection.manual.auto-approve';")
if [ "$manual_review_columns" != 6 ] || [ "$manual_audit_table" != 1 ] || [ "$manual_auto_approve_config" != 1 ]; then
  echo "ERROR: manual review schema/config verification failed (columns=$manual_review_columns audit_table=$manual_audit_table config=$manual_auto_approve_config)." >&2
  exit 1
fi
node_factor_provenance_columns=$(mysql_query "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='emission_node_config' AND column_name IN ('carbon_emission_factor_source','carbon_emission_factor_id','carbon_emission_factor_name','carbon_emission_factor_data_year','carbon_emission_factor_dqi_e1_score','carbon_emission_factor_dqi_e2_score','carbon_emission_factor_dqi_e3_score','carbon_emission_factor_dqi_e4_score','carbon_emission_factor_dqi_e5_score','carbon_emission_factor_dqi_e6_score');")
if [ "$node_factor_provenance_columns" != 10 ]; then
  echo "ERROR: node factor provenance migration is incomplete (columns=$node_factor_provenance_columns/10)." >&2
  exit 1
fi
fossil_factor_units=$(mysql_query "SELECT COUNT(DISTINCT CONCAT(subcategory_code, ':', denominator_unit_code)) FROM emission_factor_unit WHERE numerator_ghg_code='tCO2' AND subcategory_code IN ('FF_B','FF_LB','FF_CK','FF_PC','FF_G','FF_D','FF_C','FF_F','FF_LNG','FF_LPG','FF_NG','FF_BFG','FF_COG','FF_COK') AND denominator_unit_code IN ('t','kg','g','L','m3','wan_m3','Nm3','wan_Nm3');")
if [ "$fossil_factor_units" -lt 52 ]; then
  echo "ERROR: fossil factor unit migration is incomplete (found=$fossil_factor_units expected=52)." >&2
  exit 1
fi
core_users=$(mysql_query "SELECT COUNT(*) FROM sys_user WHERE del_flag='0';")
core_roles=$(mysql_query "SELECT COUNT(*) FROM sys_role WHERE del_flag='0';")
core_menus=$(mysql_query "SELECT COUNT(*) FROM sys_menu WHERE status='0';")
report_tables=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name LIKE 'report_%';")
if [ "$core_users" -lt 1 ] || [ "$core_roles" -lt 1 ] || [ "$core_menus" -lt 20 ] || [ "$report_tables" -lt 13 ]; then
  echo "ERROR: core/report data verification failed (users=$core_users roles=$core_roles menus=$core_menus report_tables=$report_tables)." >&2
  exit 1
fi
energy_menu_permissions=$(mysql_query "SELECT COUNT(*) FROM sys_menu WHERE perms IN ('carbon:energy:list','carbon:energy:query','carbon:energy:version','carbon:energy:run','carbon:energy:cancel','carbon:energy:download','carbon:energy:project','carbon:energy:remove');")
energy_edit_table=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='energy_version_edit_sheet';")
if [ "$energy_menu_permissions" -lt 8 ] || [ "$energy_edit_table" != 1 ]; then
  echo "ERROR: energy migration verification failed (permissions=$energy_menu_permissions/8 edit_table=$energy_edit_table/1)." >&2
  exit 1
fi
report_menu_permissions=$(mysql_query "SELECT COUNT(*) FROM sys_menu WHERE perms IN ('carbon:report:list','carbon:report:query','carbon:report:add','carbon:report:edit','carbon:report:remove','carbon:report:import','carbon:report:validate','carbon:report:generate','carbon:report:download','carbon:report:profile:query','carbon:report:profile:edit');")
if [ "$report_menu_permissions" -lt 11 ]; then
  echo "ERROR: report menu migration produced only $report_menu_permissions of 11 permissions." >&2
  exit 1
fi
uncertainty_menu_permissions=$(mysql_query "SELECT COUNT(*) FROM sys_menu WHERE perms='carbon:uncertainty:view';")
uncertainty_tables=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('uncertainty_ruleset','uncertainty_dimension_rule','uncertainty_source_meta','uncertainty_score','uncertainty_audit','uncertainty_scope_baseline','uncertainty_run','uncertainty_run_scope','uncertainty_param_result');")
uncertainty_flag_types=$(mysql_query "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='uncertainty_dimension_rule' AND column_name IN ('enabled','mark_default_filled') AND data_type='tinyint';")
uncertainty_shared_flag_types=$(mysql_query "SELECT COUNT(*) FROM (SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND ((table_name='emission_calculation_node' AND column_name='include_in_calculation') OR (table_name='emission_collection_node_data' AND column_name='rollover_applied') OR (table_name='uncertainty_run' AND column_name IN ('point_cov_in_ci','raw_le_cov'))) AND data_type='tinyint') flags;")
if [ "$uncertainty_menu_permissions" != 1 ] || [ "$uncertainty_tables" != 9 ] || [ "$uncertainty_flag_types" != 2 ] || [ "$uncertainty_shared_flag_types" != 4 ]; then
  echo "ERROR: uncertainty analysis migration verification failed (permission=$uncertainty_menu_permissions/1 tables=$uncertainty_tables/9 flag_types=$uncertainty_flag_types/2 shared_flag_types=$uncertainty_shared_flag_types/4)." >&2
  exit 1
fi
prediction_tables=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name LIKE 'prediction_%';")
prediction_permissions=$(mysql_query "SELECT COUNT(*) FROM sys_menu WHERE perms IN ('carbon:prediction:view','carbon:prediction:data:edit','carbon:prediction:review','carbon:prediction:model','carbon:prediction:forecast');")
prediction_collations=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name LIKE 'prediction_%' AND table_collation='utf8mb4_0900_ai_ci';")
if [ "$prediction_tables" -lt 22 ] || [ "$prediction_permissions" != 5 ] || [ "$prediction_collations" != 0 ]; then
  echo "ERROR: prediction migration verification failed (tables=$prediction_tables/22 permissions=$prediction_permissions/5 mysql8_collations=$prediction_collations/0)." >&2
  exit 1
fi
prediction_admin_roles=$(mysql_query "SELECT COUNT(*) FROM sys_role WHERE status='0' AND del_flag='0' AND (LOWER(TRIM(role_key)) IN ('admin','company_admin','system_admin','platform_admin','super_admin','sys_admin','systemadministrator','platformadministrator','companyadministrator') OR TRIM(role_name) IN ('系统管理员','超级管理员','平台管理员','公司级系统管理员','公司管理员'));" )
prediction_admin_missing=$(mysql_query "SELECT COUNT(*) FROM sys_role r WHERE r.status='0' AND r.del_flag='0' AND (LOWER(TRIM(r.role_key)) IN ('admin','company_admin','system_admin','platform_admin','super_admin','sys_admin','systemadministrator','platformadministrator','companyadministrator') OR TRIM(r.role_name) IN ('系统管理员','超级管理员','平台管理员','公司级系统管理员','公司管理员')) AND (SELECT COUNT(DISTINCT m.perms) FROM sys_role_menu rm JOIN sys_menu m ON m.menu_id=rm.menu_id WHERE rm.role_id=r.role_id AND m.status='0' AND m.perms IN ('carbon:prediction:view','carbon:prediction:data:edit','carbon:prediction:review','carbon:prediction:model','carbon:prediction:forecast')) < 5;")
if [ "$prediction_admin_roles" -gt 0 ] && [ "$prediction_admin_missing" != 0 ]; then
  echo "ERROR: administrator prediction grants are incomplete (roles=$prediction_admin_roles missing=$prediction_admin_missing)." >&2
  exit 1
fi
monthly_summary_tables=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('emission_calc_node_summary_month','emission_company_energy_summary_month');")
monthly_summary_indexes=$(mysql_query "SELECT COUNT(DISTINCT CONCAT(table_name, ':', index_name)) FROM information_schema.statistics WHERE table_schema=DATABASE() AND ((table_name='emission_calc_node_summary_month' AND index_name IN ('uk_node_month_subcategory','idx_node_month_template_cycle','idx_node_month_status')) OR (table_name='emission_company_energy_summary_month' AND index_name IN ('uk_company_month_energy_subcategory','idx_company_month_cycle','idx_company_month_status')));")
trend_auto_ingest_configs=$(mysql_query "SELECT COUNT(*) FROM sys_config WHERE config_key='carbon.trend-prediction.auto-ingest-company-monthly-data' AND config_type='Y' AND config_value IN ('true','false');")
if [ "$monthly_summary_tables" != 2 ] || [ "$monthly_summary_indexes" != 6 ] || [ "$trend_auto_ingest_configs" != 1 ]; then
  echo "ERROR: node/company monthly publication migration verification failed (tables=$monthly_summary_tables/2 indexes=$monthly_summary_indexes/6 trend_config=$trend_auto_ingest_configs/1)." >&2
  exit 1
fi
prediction_monthly_source_tables=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('prediction_monthly_source_head','prediction_monthly_source_receipt');")
prediction_monthly_source_indexes=$(mysql_query "SELECT COUNT(DISTINCT CONCAT(table_name, ':', index_name)) FROM information_schema.statistics WHERE table_schema=DATABASE() AND ((table_name='prediction_monthly_source_head' AND index_name='PRIMARY') OR (table_name='prediction_monthly_source_receipt' AND index_name IN ('PRIMARY','uk_prediction_source_version')));")
monthly_outbox_tables=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='emission_monthly_prediction_outbox';")
monthly_outbox_indexes=$(mysql_query "SELECT COUNT(DISTINCT index_name) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='emission_monthly_prediction_outbox' AND index_name IN ('PRIMARY','idx_monthly_outbox_version','idx_monthly_outbox_due');")
if [ "$prediction_monthly_source_tables" != 2 ] || [ "$prediction_monthly_source_indexes" != 3 ] || \
   [ "$monthly_outbox_tables" != 1 ] || [ "$monthly_outbox_indexes" != 3 ]; then
  echo "ERROR: monthly prediction migration verification failed (source_tables=$prediction_monthly_source_tables/2 source_indexes=$prediction_monthly_source_indexes/3 outbox_tables=$monthly_outbox_tables/1 outbox_indexes=$monthly_outbox_indexes/3)." >&2
  exit 1
fi
managed_roles=$(mysql_query "SELECT COUNT(DISTINCT role_key) FROM sys_role WHERE status='0' AND del_flag='0' AND role_key IN ('company_admin','region_admin','department_admin','carbon_accountant','carbon_data_entry','carbon_reviewer','carbon_auditor','screen_operator','electricity_collector','energy_operator','single_train_operator','prediction_analyst');")
specialist_roles=$(mysql_query "SELECT COUNT(DISTINCT role_key) FROM sys_role WHERE status='0' AND del_flag='0' AND role_key IN ('energy_operator','single_train_operator','prediction_analyst');")
ungranted_managed_roles=$(mysql_query "SELECT COUNT(*) FROM sys_role r WHERE r.status='0' AND r.del_flag='0' AND r.role_key IN ('company_admin','region_admin','department_admin','carbon_accountant','carbon_data_entry','carbon_reviewer','carbon_auditor','screen_operator','electricity_collector','energy_operator','single_train_operator','prediction_analyst') AND NOT EXISTS (SELECT 1 FROM sys_role_menu rm JOIN sys_menu m ON m.menu_id=rm.menu_id WHERE rm.role_id=r.role_id AND (m.perms LIKE 'carbon:%' OR m.perms LIKE 'goview:%'));")
module_permission_count=$(mysql_query "SELECT COUNT(DISTINCT perms) FROM sys_menu WHERE status='0' AND (perms LIKE 'carbon:%' OR perms LIKE 'goview:%');")
company_admin_permission_count=$(mysql_query "SELECT COUNT(DISTINCT m.perms) FROM sys_role r JOIN sys_role_menu rm ON rm.role_id=r.role_id JOIN sys_menu m ON m.menu_id=rm.menu_id WHERE r.role_key='company_admin' AND r.status='0' AND r.del_flag='0' AND m.status='0' AND (m.perms LIKE 'carbon:%' OR m.perms LIKE 'goview:%');")
if [ "$managed_roles" != 12 ] || [ "$specialist_roles" != 3 ] || [ "$ungranted_managed_roles" != 0 ] || [ "$module_permission_count" != "$company_admin_permission_count" ]; then
  echo "ERROR: complete role matrix verification failed (roles=$managed_roles/12 specialist=$specialist_roles/3 ungranted=$ungranted_managed_roles company_coverage=$company_admin_permission_count/$module_permission_count)." >&2
  exit 1
fi
meter_model_count=$(mysql_query "SELECT COUNT(*) FROM emission_meter_model;")
if [ "$meter_model_count" -lt 22 ]; then
  echo "ERROR: meter model seed migration is incomplete (found=$meter_model_count expected>=22)." >&2
  exit 1
fi
energy_attribution_tables=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='emission_energy_attribution_station';")
energy_attribution_columns=$(mysql_query "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND column_name IN ('energy_attribution_station_id','energy_attribution_dept_id') AND table_name IN ('emission_meter_info','emission_fossil_fuel_meter_info','emission_purchased_heat_meter_info');")
energy_attribution_defaults=$(mysql_query "SELECT COUNT(*) FROM emission_energy_attribution_station WHERE created_by IS NULL;")
if [ "$energy_attribution_tables" != 1 ] || [ "$energy_attribution_columns" != 6 ] || [ "$energy_attribution_defaults" -lt 52 ]; then
  echo "ERROR: energy attribution migration is incomplete (table=$energy_attribution_tables columns=$energy_attribution_columns/6 defaults=$energy_attribution_defaults/52)." >&2
  exit 1
fi
calculation_company_columns=$(mysql_query "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='emission_calculation_template' AND column_name='company_dept_id';")
if [ "$calculation_company_columns" != 1 ]; then
  echo 'ERROR: calculation company migration is incomplete.' >&2
  exit 1
fi
single_train_tables=$(mysql_query "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('single_dept_project','single_version','single_run','single_case','single_artifact');")
if [ "$single_train_tables" != 5 ]; then
  echo "ERROR: single-train schema migration is incomplete (tables=$single_train_tables/5)." >&2
  exit 1
fi
single_train_permissions=$(mysql_query "SELECT COUNT(*) FROM sys_menu WHERE perms IN ('carbon:singleTrain:list','carbon:singleTrain:query','carbon:singleTrain:version','carbon:singleTrain:run','carbon:singleTrain:cancel','carbon:singleTrain:download');")
if [ "$single_train_permissions" != 6 ]; then
  echo "ERROR: single-train permissions migration is incomplete (permissions=$single_train_permissions/6)." >&2
  exit 1
fi
default_report_images=$(mysql_query "SELECT COUNT(*) FROM report_file WHERE kind='default' AND role IN ('cover_logo','org_chart','office_location') AND content IS NOT NULL;")
report_suning_profile=$(mysql_query "SELECT COUNT(*) FROM report_dept_profile WHERE entity_code='suning';")
if [ "$report_suning_profile" -gt 0 ] && [ "$default_report_images" -lt 3 ]; then
  echo "ERROR: default report images are missing for the configured suning profile (found=$default_report_images expected>=3)." >&2
  exit 1
elif [ "$report_suning_profile" = 0 ]; then
  echo 'WARNING: no report_dept_profile entity_code=suning; default report images were not attached.' >&2
fi
analysis_menu_permissions=$(mysql_query "SELECT COUNT(*) FROM sys_menu WHERE perms='carbon:analysis:view';")
analysis_templates=$(mysql_query "SELECT COUNT(*) FROM emission_calculation_template WHERE template_id=502;")
if [ "$analysis_menu_permissions" -lt 1 ] || [ "$analysis_templates" -lt 24 ]; then
  echo "ERROR: energy analysis migration verification failed (permissions=$analysis_menu_permissions templates=$analysis_templates/24)." >&2
  exit 1
fi
energy_version_id=$(mysql_query "SELECT v.version_id FROM energy_project_version v JOIN energy_project p ON p.project_id=v.project_id WHERE p.project_code='shuohuang_demo' AND v.version_code='v1' LIMIT 1;")
test -n "$energy_version_id"
energy_dataset_files=$(mysql_query "SELECT COUNT(*) FROM energy_dataset_file WHERE version_id='$energy_version_id';")
energy_stations=$(mysql_query "SELECT COUNT(*) FROM energy_station WHERE version_id='$energy_version_id';")
energy_segments=$(mysql_query "SELECT COUNT(*) FROM energy_route_segment WHERE version_id='$energy_version_id';")
energy_power_arms=$(mysql_query "SELECT COUNT(*) FROM energy_power_arm WHERE version_id='$energy_version_id';")
energy_train_types=$(mysql_query "SELECT COUNT(*) FROM energy_train_type_parameter WHERE version_id='$energy_version_id';")
energy_storage_devices=$(mysql_query "SELECT COUNT(*) FROM energy_storage_device WHERE version_id='$energy_version_id';")
energy_timetable_trains=$(mysql_query "SELECT COUNT(*) FROM energy_timetable_train t JOIN energy_timetable tt ON tt.timetable_id=t.timetable_id WHERE tt.version_id='$energy_version_id' AND tt.timetable_code='TT-2026-DEMO';")
if [ "$energy_dataset_files" != 28 ] || [ "$energy_stations" != 33 ] || [ "$energy_segments" != 1390 ] || \
   [ "$energy_power_arms" != 76 ] || [ "$energy_train_types" != 2 ] || [ "$energy_storage_devices" != 2 ] || \
   [ "$energy_timetable_trains" != 2 ]; then
  echo "ERROR: complete Shuohuang dataset verification failed (files=$energy_dataset_files stations=$energy_stations segments=$energy_segments power_arms=$energy_power_arms train_types=$energy_train_types storage=$energy_storage_devices timetable_trains=$energy_timetable_trains)." >&2
  exit 1
fi
compatibility_runs=$(mysql_query "SELECT COUNT(*) FROM energy_run WHERE worker_id IN ('fixture-worker','builtin-compatibility') OR code_version='builtin-compatibility';")
if [ "$compatibility_runs" != 0 ]; then
  echo "ERROR: retired compatibility runs remain (count=$compatibility_runs)." >&2
  exit 1
fi
if [ "$APPLY_PERMISSION_RESET" = true ]; then
  import_file "$PACKAGE_ROOT/mysql/optional/60_cleanup_and_test_users.sql"
else
  echo 'WARNING: fixed role renumbering, legacy sample cleanup and test users were skipped.'
fi

write_variable() {
  printf '%s=' "$1"
  printf "'%s'\n" "$(printf '%s' "$2" | sed "s/'/'\"'\"'/g")"
}
for mode in web screen; do
  env_file="$TEMP_DIR/$mode.env"
  {
    write_variable GOVIEW_AUDIT_SECRET "$GOVIEW_AUDIT_SECRET"
    if [ "$mode" = web ]; then
      write_variable DB_HOST "$DB_HOST"
      write_variable APP_DB_USERNAME "$APP_DB_USERNAME"
      write_variable APP_DB_PASSWORD "$APP_DB_PASSWORD"
      write_variable WEB_PUBLIC_URL "$WEB_PUBLIC_URL"
      write_variable REPORT_PYTHON "$REPORT_PYTHON"
      write_variable REPORT_SOFFICE "$REPORT_SOFFICE"
      write_variable PREDICTION_API_KEY "$PREDICTION_API_KEY"
      write_variable CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY "$CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY"
      write_variable CARBON_REPORT_LLM_BASE_URL "$CARBON_REPORT_LLM_BASE_URL"
      write_variable CARBON_REPORT_LLM_MODEL "$CARBON_REPORT_LLM_MODEL"
      write_variable CARBON_REPORT_LLM_API_KEY "$CARBON_REPORT_LLM_API_KEY"
      write_variable CARBON_MONTHLY_REPAIR_ENABLED "${CARBON_MONTHLY_REPAIR_ENABLED:-false}"
      write_variable CARBON_MONTHLY_PREDICTION_URL "$CARBON_MONTHLY_PREDICTION_URL"
      write_variable CARBON_MONTHLY_PREDICTION_API_KEY "$CARBON_MONTHLY_PREDICTION_API_KEY"
      write_variable CARBON_MONTHLY_JLG_TRACTION_CATEGORIES "$CARBON_MONTHLY_JLG_TRACTION_CATEGORIES"
      write_variable CARBON_MONTHLY_JLG_AUXILIARY_CATEGORIES "$CARBON_MONTHLY_JLG_AUXILIARY_CATEGORIES"
    else
      write_variable SCREEN_PUBLIC_URL "$SCREEN_PUBLIC_URL"
      write_variable WEB_INTERNAL_HOST "$WEB_INTERNAL_HOST"
    fi
  } > "$env_file"
  if [ "$mode" = web ]; then container=$WEB_CONTAINER; else container=$SCREEN_CONTAINER; fi
  docker cp "$env_file" "$container:/etc/carbon-integration.env"
  docker exec "$container" chmod 600 /etc/carbon-integration.env
  docker exec -e UPDATE_ID="$UPDATE_ID" "$container" sh "$STAGING/scripts/container-update.sh" "$mode" apply "$STAGING"
  if [ "$mode" = web ]; then WEB_STOPPED=false; else SCREEN_STOPPED=false; fi
done

wait_http() {
  local url=$1 codes=$2 code round
  for round in $(seq 1 180); do
    code=$(curl -sS --connect-timeout 3 -m 5 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)
    case ",$codes," in *",$code,"*) echo "PASS $url -> $code"; return 0 ;; esac
    sleep 1
  done
  echo "FAIL $url -> ${code:-connection-error}. Check application logs." >&2
  case "$url" in
    *'/uncertainty/'*)
      echo '--- uncertainty-app diagnostics ---' >&2
      docker exec "$WEB_CONTAINER" sh -c \
        'pgrep -af uncertainty-app.jar || true; tail -n 160 /home/ruoyi/logs/uncertainty-app.log 2>/dev/null || true' >&2
      ;;
  esac
  return 1
}
wait_http "http://127.0.0.1:$WEB_HOST_PORT/" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/prod-api/code" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/carbon-model/" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/api/template/list" 200,401,403
wait_http "http://127.0.0.1:$WEB_HOST_PORT/uncertainty/uncertainty-wizard.html" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/api/uncertainty/calculation-tasks" 200,401,403
wait_http "http://127.0.0.1:$WEB_HOST_PORT/prediction/" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/prediction-api/platform/health" 200
wait_http "http://127.0.0.1:$WEB_HOST_PORT/prediction-api/platform/orgs" 401,403
docker exec "$WEB_CONTAINER" sh -c \
  "curl -fsS --connect-timeout 5 http://127.0.0.1:8090/health | grep -q '\"code\":0'; pgrep -af prediction-platform.jar; pgrep -af prediction-engine/scripts/run_api.py"
wait_http "http://127.0.0.1:$SCREEN_HOST_PORT/" 200
wait_http "http://127.0.0.1:$SCREEN_HOST_PORT/api/goview/sys/getOssInfo" 200,401,403
docker exec "$SCREEN_CONTAINER" curl -fsS --connect-timeout 10 -o /dev/null "http://$WEB_INTERNAL_HOST:8081/code"
asset=$(curl -sS "http://127.0.0.1:$WEB_HOST_PORT/carbon-model/" | sed -n 's/.*src="\([^"]*\.js\)".*/\1/p' | head -1)
test -n "$asset"
asset_type=$(curl -fsS "http://127.0.0.1:$WEB_HOST_PORT$asset" -o /dev/null -w '%{content_type}')
case "$asset_type" in *javascript*) ;; *) echo "ERROR: model asset returned $asset_type, not JavaScript" >&2; exit 1 ;; esac
docker exec "$WEB_CONTAINER" sh "$STAGING/scripts/verify-report-render.sh" \
  "$STAGING/verification/carbon-render-smoke.json" /tmp
docker exec "$WEB_CONTAINER" sh -c 'pgrep -x java; nginx -t'
docker exec "$SCREEN_CONTAINER" sh -c 'pgrep -x java; nginx -t'
mysql_query 'SELECT role_id,role_name,role_key FROM sys_role ORDER BY role_id; SELECT COUNT(*) AS operation_logs FROM sys_oper_log;'
echo 'Update, HTTP health checks, and synthetic DOCX/PDF report rendering completed. Authentication/authorization must also be checked in the browser.'
echo "Management: $WEB_PUBLIC_URL"
echo "Screen:     $SCREEN_PUBLIC_URL"
echo 'Server-side backups: disabled by design.'
