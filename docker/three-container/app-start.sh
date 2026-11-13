#!/bin/sh
set -eu

mkdir -p /srv/shared/report-work /srv/shared/reports /srv/shared/energy /srv/shared/uploads \
  /srv/shared/goview /srv/shared/goview-upload /srv/shared/single-train \
  /data/redis /run/nginx /var/log/nginx

if [ ! -e /srv/shared/goview/goview.db ]; then
  cp /opt/shsystem/goview/seed.db /srv/shared/goview/goview.db
fi
cp -Rn /opt/shsystem/static/goview-upload/. /srv/shared/goview-upload/

redis-server --daemonize yes --bind 127.0.0.1 --dir /data/redis --appendonly yes
java ${JAVA_OPTS:-} -jar /opt/shsystem/ruoyi-admin.jar > /srv/shared/ruoyi-admin.log 2>&1 &
app_pid=$!
java ${GOVIEW_JAVA_OPTS:-} -Dserver.port="${GOVIEW_SERVER_PORT:-8087}" -jar /opt/shsystem/goview/goview.war \
  > /srv/shared/goview.log 2>&1 &
goview_pid=$!
env CARBON_SERVER_PORT="${CARBON_SERVER_PORT:-8082}" \
  CARBON_DB_URL="${CARBON_DB_URL:-${DATABASE_JDBC_URL:-jdbc:mysql://sh-db:3306/carbon_emissions?useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&characterEncoding=UTF-8}}" \
  CARBON_DB_USERNAME="${CARBON_DB_USERNAME:-${DATABASE_USER:-shsystem_app}}" \
  CARBON_DB_PASSWORD="${CARBON_DB_PASSWORD:-${DATABASE_PASSWORD:-}}" \
  RUOYI_SECURITY_ENDPOINT="${RUOYI_SECURITY_ENDPOINT:-http://127.0.0.1:8081/internal/security/context}" \
  java ${CARBON_JAVA_OPTS:-} -jar /opt/shsystem/carbon-emission-model.jar \
  > /srv/shared/carbon-emission-model.log 2>&1 &
carbon_pid=$!
env UNCERTAINTY_SERVER_PORT="${UNCERTAINTY_SERVER_PORT:-8085}" \
  UNCERTAINTY_DB_URL="${UNCERTAINTY_DB_URL:-${DATABASE_JDBC_URL:-jdbc:mysql://sh-db:3306/carbon_emissions?useSSL=false&serverTimezone=Asia/Shanghai&allowPublicKeyRetrieval=true&characterEncoding=UTF-8}}" \
  UNCERTAINTY_DB_USERNAME="${UNCERTAINTY_DB_USERNAME:-${DATABASE_USER:-shsystem_app}}" \
  UNCERTAINTY_DB_PASSWORD="${UNCERTAINTY_DB_PASSWORD:-${DATABASE_PASSWORD:-}}" \
  java ${UNCERTAINTY_JAVA_OPTS:-} -jar /opt/shsystem/uncertainty-app.jar \
  > /srv/shared/uncertainty-app.log 2>&1 &
uncertainty_pid=$!
java ${PREDICTION_PLATFORM_JAVA_OPTS:-} -jar /opt/shsystem/carbon-platform.jar \
  > /srv/shared/prediction-platform.log 2>&1 &
prediction_platform_pid=$!

term() { kill "$app_pid" "$goview_pid" "$carbon_pid" "$uncertainty_pid" "$prediction_platform_pid" 2>/dev/null || true; exit 143; }
trap term INT TERM

nginx -g 'daemon off;' &
nginx_pid=$!
while kill -0 "$app_pid" 2>/dev/null && kill -0 "$goview_pid" 2>/dev/null \
  && kill -0 "$carbon_pid" 2>/dev/null && kill -0 "$uncertainty_pid" 2>/dev/null \
  && kill -0 "$prediction_platform_pid" 2>/dev/null && kill -0 "$nginx_pid" 2>/dev/null; do
  sleep 1
done
status=0
if ! kill -0 "$app_pid" 2>/dev/null; then
  wait "$app_pid" || status=$?
elif ! kill -0 "$goview_pid" 2>/dev/null; then
  wait "$goview_pid" || status=$?
elif ! kill -0 "$carbon_pid" 2>/dev/null; then
  wait "$carbon_pid" || status=$?
elif ! kill -0 "$uncertainty_pid" 2>/dev/null; then
  wait "$uncertainty_pid" || status=$?
elif ! kill -0 "$prediction_platform_pid" 2>/dev/null; then
  wait "$prediction_platform_pid" || status=$?
else
  wait "$nginx_pid" || status=$?
fi
kill "$app_pid" "$goview_pid" "$carbon_pid" "$uncertainty_pid" "$prediction_platform_pid" "$nginx_pid" 2>/dev/null || true
wait || true
exit "$status"
