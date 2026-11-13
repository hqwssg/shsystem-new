#!/bin/sh
set -eu

mkdir -p /run/nginx /home/ruoyi/uploadPath/reports /home/ruoyi/uploadPath/energy /home/ruoyi/report-work /home/ruoyi/logs /home/ruoyi/uncertainty /data /var/log/nginx
redis-server --daemonize yes --dir /data --appendonly yes
prediction_rows=$(env DB_HOST="${DB_HOST:-ruoyi-db}" DB_PORT="${DB_PORT:-3306}" DB_USER="${CARBON_DB_USERNAME:-root}" \
  DB_PASSWORD="${CARBON_DB_PASSWORD:-}" DB_NAME=carbon_emissions \
  /opt/carbon-report-venv/bin/python -c \
  'import os,pymysql; c=pymysql.connect(host=os.environ["DB_HOST"],port=int(os.environ["DB_PORT"]),user=os.environ["DB_USER"],password=os.environ["DB_PASSWORD"],database=os.environ["DB_NAME"]); q=c.cursor(); q.execute("SELECT COUNT(*) FROM prediction_activity_monthly"); print(q.fetchone()[0]); c.close()')
if [ "$prediction_rows" = 0 ]; then
  (cd /home/ruoyi/prediction-engine && env DB_HOST="${DB_HOST:-ruoyi-db}" DB_PORT="${DB_PORT:-3306}" \
    DB_USER="${CARBON_DB_USERNAME:-root}" DB_PASSWORD="${CARBON_DB_PASSWORD:-}" DB_NAME=carbon_emissions \
    /opt/carbon-report-venv/bin/python scripts/import_history.py) \
    > /home/ruoyi/logs/prediction-history-import.log 2>&1
fi
java ${JAVA_OPTS:-} -jar /home/ruoyi/ruoyi-admin.jar > /home/ruoyi/logs/ruoyi-admin.log 2>&1 &
env \
  CARBON_SERVER_PORT="${CARBON_SERVER_PORT:-8082}" \
  SPRING_SQL_INIT_MODE=never CARBON_SQL_INIT_MODE=never \
  RUOYI_SECURITY_ENDPOINT="${RUOYI_SECURITY_ENDPOINT:-http://127.0.0.1:8081/internal/security/context}" \
  RUOYI_AUDIT_ENDPOINT="${RUOYI_AUDIT_ENDPOINT:-http://127.0.0.1:8081/internal/carbon/audit/operation}" \
  PYTHON_PATH="${PYTHON_PATH:-/opt/carbon-report-venv/bin/python}" \
  STEAM_CALCULATOR_SCRIPT="${STEAM_CALCULATOR_SCRIPT:-/home/ruoyi/steam_calculator.py}" \
  java ${MODEL_JAVA_OPTS:-} -jar /home/ruoyi/carbon-emission-model.jar \
  > /home/ruoyi/logs/carbon-emission-model.log 2>&1 &
env \
  UNCERTAINTY_SERVER_PORT="${UNCERTAINTY_SERVER_PORT:-8085}" \
  UNCERTAINTY_DB_URL="${UNCERTAINTY_DB_URL:-jdbc:mysql://127.0.0.1:3306/carbon_emissions?useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&characterEncoding=UTF-8&useUnicode=true&connectionCollation=utf8mb4_unicode_ci&tinyInt1isBit=false}" \
  UNCERTAINTY_DB_USERNAME="${UNCERTAINTY_DB_USERNAME:-root}" \
  UNCERTAINTY_DB_PASSWORD="${UNCERTAINTY_DB_PASSWORD:-}" \
  RUOYI_SECURITY_ENABLED="${RUOYI_SECURITY_ENABLED:-true}" \
  RUOYI_SECURITY_ENDPOINT="${RUOYI_SECURITY_ENDPOINT:-http://127.0.0.1:8081/internal/security/context}" \
  java ${UNCERTAINTY_JAVA_OPTS:-} -jar /home/ruoyi/uncertainty-app.jar \
  > /home/ruoyi/logs/uncertainty-app.log 2>&1 &
env \
  DB_HOST="${DB_HOST:-ruoyi-db}" DB_PORT="${DB_PORT:-3306}" DB_USER="${CARBON_DB_USERNAME:-root}" \
  DB_PASSWORD="${CARBON_DB_PASSWORD:-}" DB_NAME=carbon_emissions \
  API_HOST=127.0.0.1 API_PORT=8090 API_KEY="${PREDICTION_API_KEY:-change-me-prediction-internal-key}" \
  /opt/carbon-report-venv/bin/python /home/ruoyi/prediction-engine/scripts/run_api.py \
  > /home/ruoyi/logs/prediction-engine.log 2>&1 &
env \
  PREDICTION_PLATFORM_PORT=8086 \
  DB_HOST="${DB_HOST:-ruoyi-db}" DB_PORT="${DB_PORT:-3306}" DB_USER="${CARBON_DB_USERNAME:-root}" \
  DB_PASSWORD="${CARBON_DB_PASSWORD:-}" DB_NAME=carbon_emissions \
  PREDICTION_BASE_URL=http://127.0.0.1:8090 PREDICTION_API_KEY="${PREDICTION_API_KEY:-change-me-prediction-internal-key}" \
  RUOYI_SECURITY_ENABLED="${RUOYI_SECURITY_ENABLED:-true}" \
  RUOYI_SECURITY_ENDPOINT="${RUOYI_SECURITY_ENDPOINT:-http://127.0.0.1:8081/internal/security/context}" \
  java ${PREDICTION_JAVA_OPTS:-} -jar /home/ruoyi/prediction-platform.jar \
  > /home/ruoyi/logs/prediction-platform.log 2>&1 &
exec nginx -g "daemon off;"
