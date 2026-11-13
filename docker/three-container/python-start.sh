#!/bin/sh
set -eu

mkdir -p /srv/shared/report-work /srv/shared/reports /srv/shared/energy /srv/shared/uploads
python -m uvicorn services.python_service.app:app --host 0.0.0.0 --port "${PYTHON_SERVICE_PORT:-8091}" \
  > /srv/shared/python-service.log 2>&1 &
task_pid=$!
API_PORT="${PREDICTION_API_PORT:-8090}" python railway_carbon_prediction/scripts/run_api.py \
  > /srv/shared/prediction-api.log 2>&1 &
prediction_pid=$!

term() { kill "$task_pid" "$prediction_pid" 2>/dev/null || true; exit 143; }
trap term INT TERM
while kill -0 "$task_pid" 2>/dev/null && kill -0 "$prediction_pid" 2>/dev/null; do
  sleep 1
done
status=0
if ! kill -0 "$task_pid" 2>/dev/null; then
  wait "$task_pid" || status=$?
else
  wait "$prediction_pid" || status=$?
fi
kill "$task_pid" "$prediction_pid" 2>/dev/null || true
wait || true
exit "$status"
