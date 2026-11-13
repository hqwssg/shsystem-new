#!/bin/sh
set -eu
. /etc/carbon-integration.env
# This runtime secret is installed on the server, never shipped with a package.
if [ -s /etc/carbon-report/llm-encryption.key ]; then
  persisted_llm_key=$(cat /etc/carbon-report/llm-encryption.key)
  if [ -n "${CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY:-}" ] &&
     [ "$CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY" != "$persisted_llm_key" ]; then
    echo 'ERROR: report AI encryption key differs from the persisted runtime key.' >&2
    exit 1
  fi
  CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY=$persisted_llm_key
fi
export CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY="${CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY:-}"
export CARBON_REPORT_LLM_BASE_URL="${CARBON_REPORT_LLM_BASE_URL:-}"
export CARBON_REPORT_LLM_MODEL="${CARBON_REPORT_LLM_MODEL:-}"
export CARBON_REPORT_LLM_API_KEY="${CARBON_REPORT_LLM_API_KEY:-${OPENAI_API_KEY:-}}"
. /usr/local/lib/carbon-integration/runtime-common.sh
mkdir -p /home/ruoyi/logs /home/ruoyi/uploadPath/reports /home/ruoyi/uploadPath/energy /home/ruoyi/uploadPath/single-train-results /home/ruoyi/report-work /data/redis
if ! pgrep -x redis-server >/dev/null 2>&1; then
  redis-server --daemonize yes --bind 127.0.0.1 --protected-mode yes --appendonly yes --dir /data/redis
fi
stop_java ruoyi-admin.jar
stop_java carbon-emission-model.jar
stop_java uncertainty-app.jar
stop_java prediction-platform.jar
stop_process 'prediction-engine/scripts/run_api.py'
cd /home/ruoyi
export GOVIEW_AUDIT_SECRET
export LANG=${LANG:-C.UTF-8}
export LC_ALL=${LC_ALL:-C.UTF-8}
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
nohup env \
  SERVER_PORT=8081 SPRING_DATA_REDIS_HOST=127.0.0.1 SPRING_DATA_REDIS_PORT=6379 \
  SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_URL="jdbc:mysql://$DB_HOST:3306/carbon_emissions?useUnicode=true&characterEncoding=UTF-8&connectionCollation=utf8mb4_unicode_ci&useSSL=false&serverTimezone=GMT%2B8&allowPublicKeyRetrieval=true" \
  SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_USERNAME="$APP_DB_USERNAME" \
  SPRING_DATASOURCE_DYNAMIC_DATASOURCE_MASTER_PASSWORD="$APP_DB_PASSWORD" \
  FILE_DOMAIN="$WEB_PUBLIC_URL/prod-api" FILE_PATH=/home/ruoyi/uploadPath \
  CARBON_REPORT_PYTHON=/opt/carbon-report-venv/bin/python \
  CARBON_REPORT_RENDERER_ROOT=/home/ruoyi/renderer \
  CARBON_REPORT_WORK_DIR=/home/ruoyi/report-work \
  CARBON_REPORT_ARTIFACT_DIR=/home/ruoyi/uploadPath/reports \
  CARBON_REPORT_SOFFICE_PATH="$REPORT_SOFFICE" \
  ENERGY_PYTHON=/opt/carbon-report-venv/bin/python \
  ENERGY_PROJECT_ROOT=/home/ruoyi/energy-engine \
  ENERGY_UPLOAD_DIR=/home/ruoyi/uploadPath/energy \
  SINGLE_TRAIN_WORKSPACE_ROOT=/home/ruoyi \
  SINGLE_TRAIN_ALGORITHM_ROOT=/home/ruoyi/single_train_algorithm \
  SINGLE_TRAIN_HEAVY_ROOT=/home/ruoyi/energy-engine \
  SINGLE_TRAIN_RESULT_ROOT=/home/ruoyi/uploadPath/single-train-results \
  java -jar /home/ruoyi/ruoyi-admin.jar > /home/ruoyi/logs/ruoyi-admin.log 2>&1 < /dev/null &
nohup env \
  CARBON_SERVER_PORT=8082 \
  CARBON_DB_URL="jdbc:mysql://$DB_HOST:3306/carbon_emissions?useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&characterEncoding=UTF-8&useUnicode=true&connectionCollation=utf8mb4_unicode_ci" \
  CARBON_DB_USERNAME="$APP_DB_USERNAME" CARBON_DB_PASSWORD="$APP_DB_PASSWORD" \
  CARBON_MONTHLY_REPAIR_ENABLED="${CARBON_MONTHLY_REPAIR_ENABLED:-false}" \
  CARBON_MONTHLY_PREDICTION_URL="${CARBON_MONTHLY_PREDICTION_URL:-}" \
  CARBON_MONTHLY_PREDICTION_API_KEY="${CARBON_MONTHLY_PREDICTION_API_KEY:-}" \
  CARBON_MONTHLY_JLG_TRACTION_CATEGORIES="${CARBON_MONTHLY_JLG_TRACTION_CATEGORIES:-}" \
  CARBON_MONTHLY_JLG_AUXILIARY_CATEGORIES="${CARBON_MONTHLY_JLG_AUXILIARY_CATEGORIES:-}" \
  SPRING_SQL_INIT_MODE=never CARBON_SQL_INIT_MODE=never SPRING_PROFILES_ACTIVE=job \
  RUOYI_SECURITY_ENABLED=true RUOYI_SECURITY_ENDPOINT=http://127.0.0.1:8081/internal/security/context \
  RUOYI_AUDIT_ENABLED=true RUOYI_AUDIT_ENDPOINT=http://127.0.0.1:8081/internal/carbon/audit/operation \
  PYTHON_PATH="$REPORT_PYTHON" STEAM_CALCULATOR_SCRIPT=/home/ruoyi/steam_calculator.py \
  java -jar /home/ruoyi/carbon-emission-model.jar > /home/ruoyi/logs/carbon-emission-model.log 2>&1 < /dev/null &
nohup env \
  UNCERTAINTY_SERVER_PORT=8085 \
  UNCERTAINTY_DB_URL="jdbc:mysql://$DB_HOST:3306/carbon_emissions?useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&characterEncoding=UTF-8&useUnicode=true&connectionCollation=utf8mb4_unicode_ci&tinyInt1isBit=false" \
  UNCERTAINTY_DB_USERNAME="$APP_DB_USERNAME" UNCERTAINTY_DB_PASSWORD="$APP_DB_PASSWORD" \
  RUOYI_SECURITY_ENABLED=true RUOYI_SECURITY_ENDPOINT=http://127.0.0.1:8081/internal/security/context \
  java -jar /home/ruoyi/uncertainty-app.jar > /home/ruoyi/logs/uncertainty-app.log 2>&1 < /dev/null &
nohup env \
  DB_HOST="$DB_HOST" DB_PORT=3306 DB_USER="$APP_DB_USERNAME" DB_PASSWORD="$APP_DB_PASSWORD" DB_NAME=carbon_emissions \
  API_HOST=127.0.0.1 API_PORT=8090 API_KEY="$PREDICTION_API_KEY" CORS_ORIGINS=http://127.0.0.1 \
  /opt/carbon-report-venv/bin/python /home/ruoyi/prediction-engine/scripts/run_api.py \
  > /home/ruoyi/logs/prediction-engine.log 2>&1 < /dev/null &
nohup env \
  PREDICTION_PLATFORM_PORT=8086 \
  DB_HOST="$DB_HOST" DB_PORT=3306 DB_USER="$APP_DB_USERNAME" DB_PASSWORD="$APP_DB_PASSWORD" DB_NAME=carbon_emissions \
  PREDICTION_BASE_URL=http://127.0.0.1:8090 PREDICTION_API_KEY="$PREDICTION_API_KEY" \
  RUOYI_SECURITY_ENABLED=true RUOYI_SECURITY_ENDPOINT=http://127.0.0.1:8081/internal/security/context \
  java -jar /home/ruoyi/prediction-platform.jar > /home/ruoyi/logs/prediction-platform.log 2>&1 < /dev/null &
start_nginx
