#!/bin/sh
set -eu
mode=$1
phase=$2
payload=$3

if [ "$phase" = prepare ]; then
  command -v java >/dev/null
  command -v nginx >/dev/null
  command -v pgrep >/dev/null
  command -v curl >/dev/null || {
    echo 'ERROR: curl is required in the image. Install it before the offline update.' >&2
    exit 1
  }
  if [ "$mode" = web ]; then
    java -version 2>&1 | grep -Eq 'version "(17|18|19|[2-9][0-9])\.' || {
      echo 'ERROR: main/model backend requires Java 17 or newer.' >&2; exit 1;
    }
    command -v redis-server >/dev/null
    REPORT_PYTHON=${REPORT_PYTHON:-python3}
    "$REPORT_PYTHON" -c 'import sys; assert sys.version_info >= (3,10), "Python >= 3.10 required"'
    if [ ! -x /opt/carbon-report-venv/bin/python ]; then
      "$REPORT_PYTHON" -m venv /opt/carbon-report-venv
    fi
    /opt/carbon-report-venv/bin/python -c 'import sys; assert sys.version_info >= (3,10)'
    test -d "$payload/web-main/wheels"
    /opt/carbon-report-venv/bin/python -m pip install --no-index \
      --find-links "$payload/web-main/wheels" -r "$payload/web-main/requirements-cli.txt"
    /opt/carbon-report-venv/bin/python -c 'import pydantic, docx, PIL, matplotlib, jinja2, httpx, pymysql, numpy, scipy, openpyxl, psutil, pandas, sklearn, statsmodels, torch, fastapi, uvicorn, joblib'
    /opt/carbon-report-venv/bin/python -c 'import pydantic; assert int(pydantic.__version__.split(".")[0]) >= 2'
    sh "$payload/scripts/verify-libreoffice.sh"
    if command -v fc-list >/dev/null && ! fc-list :lang=zh | grep -q .; then
      echo 'WARNING: no Chinese font was detected; PDF Chinese text may be blank.' >&2
    fi
  else
    test -f /home/goview/sqllite/goview.db || {
      echo 'ERROR: existing GoView database is missing; this is an update-only package.' >&2; exit 1;
    }
  fi
  exit 0
fi

test "$phase" = apply
. "$payload/scripts/runtime-common.sh"
mkdir -p /usr/local/lib/carbon-integration
cp "$payload/scripts/runtime-common.sh" /usr/local/lib/carbon-integration/runtime-common.sh
if [ "$mode" = web ]; then
  stop_java ruoyi-admin.jar
  stop_java carbon-emission-model.jar
  stop_java uncertainty-app.jar
  stop_java prediction-platform.jar
  stop_process 'prediction-engine/scripts/run_api.py'
  mkdir -p /home/ruoyi/projects /home/ruoyi/renderer /home/ruoyi/logs /home/ruoyi/uploadPath/energy /home/ruoyi/uncertainty
  rm -rf /home/ruoyi/energy-data
  mkdir -p /home/ruoyi/energy-data
  cp -r "$payload/energy-data/zhongkong_data" /home/ruoyi/energy-data/
  # Replace only application-owned directories; leave uploaded/production data alone.
  for entry in ruoyi-ui carbon-model prediction; do
    target=/home/ruoyi/projects/$entry
    rm -rf "$target"
  done
  rm -rf /home/ruoyi/renderer/carbon_report_agent
  cp -r "$payload/web-main/html/dist" /home/ruoyi/projects/ruoyi-ui
  cp -r "$payload/web-main/html/carbon-model" /home/ruoyi/projects/carbon-model
  cp -r "$payload/web-main/html/prediction" /home/ruoyi/projects/prediction
  cp -r "$payload/web-main/renderer/carbon_report_agent" /home/ruoyi/renderer/
  rm -rf /home/ruoyi/energy-engine
  cp -r "$payload/web-main/energy-engine" /home/ruoyi/energy-engine
  rm -rf /home/ruoyi/single_train_recovery_agent /home/ruoyi/single_train_algorithm
  cp -r "$payload/web-main/single-train-engine" /home/ruoyi/single_train_recovery_agent
  cp -r "$payload/web-main/single-train-algorithm" /home/ruoyi/single_train_algorithm
  rm -rf /home/ruoyi/prediction-engine
  cp -r "$payload/web-main/prediction-engine" /home/ruoyi/prediction-engine
  cp "$payload/web-main/jar/ruoyi-admin.jar" /home/ruoyi/ruoyi-admin.jar
  cp "$payload/web-main/jar/carbon-emission-model.jar" /home/ruoyi/carbon-emission-model.jar
  cp "$payload/web-main/jar/uncertainty-app.jar" /home/ruoyi/uncertainty-app.jar
  cp "$payload/web-main/jar/prediction-platform.jar" /home/ruoyi/prediction-platform.jar
  cp "$payload/web-main/python/steam_calculator.py" /home/ruoyi/steam_calculator.py
  cp "$payload/web-main/conf/nginx.conf" /etc/nginx/nginx.conf
  cp "$payload/scripts/start-web.sh" /usr/local/bin/start-ruoyi-web.sh
  chmod 755 /home /home/ruoyi /home/ruoyi/projects
  chmod -R a+rX /home/ruoyi/projects/ruoyi-ui /home/ruoyi/projects/carbon-model /home/ruoyi/projects/prediction
  chmod -R a+rX /home/ruoyi/energy-data /home/ruoyi/energy-engine
  chmod -R a+rX /home/ruoyi/single_train_recovery_agent /home/ruoyi/single_train_algorithm
  chmod -R a+rX /home/ruoyi/prediction-engine
  # Export the integration settings so Python subprocesses can read DB_HOST
  # and the application credentials through os.environ.
  set -a
  . /etc/carbon-integration.env
  set +a
  prediction_counts() {
    /opt/carbon-report-venv/bin/python -c \
      'import os,pymysql; c=pymysql.connect(host=os.environ["DB_HOST"],port=3306,user=os.environ["APP_DB_USERNAME"],password=os.environ["APP_DB_PASSWORD"],database="carbon_emissions"); q=c.cursor(); tables=("prediction_activity_monthly","prediction_emission_monthly"); values=[]; [(q.execute("SELECT COUNT(*),SUM(LEFT(batch_id,5)=CHAR(72,73,83,84,45)) FROM "+table),values.extend([int(x or 0) for x in q.fetchone()])) for table in tables]; print(*values); c.close()'
  }
  set -- $(prediction_counts)
  prediction_activity_rows=$1
  prediction_hist_activity_rows=$2
  prediction_emission_rows=$3
  prediction_hist_emission_rows=$4
  prediction_import=false
  if [ "$prediction_activity_rows" = 0 ] && [ "$prediction_emission_rows" = 0 ]; then
    echo 'Prediction history is empty; importing the delivered 2019-2025 baseline once.'
    prediction_import=true
  elif { [ "$prediction_hist_activity_rows" -gt 0 ] || [ "$prediction_hist_emission_rows" -gt 0 ]; } && \
       [ "$prediction_hist_activity_rows" = "$prediction_activity_rows" ] && \
       [ "$prediction_hist_emission_rows" = "$prediction_emission_rows" ] && \
       { [ "$prediction_hist_activity_rows" -lt 1932 ] || [ "$prediction_hist_emission_rows" -lt 252 ]; }; then
    echo 'A previous baseline import is incomplete; idempotently completing it.'
    prediction_import=true
  elif [ "$prediction_activity_rows" = 0 ] || [ "$prediction_emission_rows" = 0 ]; then
    echo "ERROR: prediction tables are inconsistent (activity=$prediction_activity_rows emission=$prediction_emission_rows). Non-baseline data will not be overwritten." >&2
    exit 1
  fi
  if [ "$prediction_import" = true ]; then
    (cd /home/ruoyi/prediction-engine && env DB_HOST="$DB_HOST" DB_PORT=3306 DB_USER="$APP_DB_USERNAME" \
      DB_PASSWORD="$APP_DB_PASSWORD" DB_NAME=carbon_emissions \
      /opt/carbon-report-venv/bin/python scripts/import_history.py) \
      > /home/ruoyi/logs/prediction-history-import.log 2>&1
    set -- $(prediction_counts)
    if [ "$2" -lt 1932 ] || [ "$4" -lt 252 ]; then
      echo "ERROR: prediction baseline import is incomplete (activity=$2/1932 emission=$4/252). See /home/ruoyi/logs/prediction-history-import.log." >&2
      exit 1
    fi
  else
    echo "Prediction history already contains $prediction_activity_rows activity and $prediction_emission_rows emission rows; preserving existing data."
  fi
  chmod 700 /usr/local/bin/start-ruoyi-web.sh
  sh /usr/local/bin/start-ruoyi-web.sh
else
  stop_java goview.war
  mkdir -p /home/goview/projects /home/goview/logs
  rm -rf /home/goview/projects/goview
  cp -r "$payload/web-screen/html/dist" /home/goview/projects/goview
  cp "$payload/web-screen/jar/goview.war" /home/goview/goview.war
  cp "$payload/web-screen/conf/nginx.conf" /etc/nginx/nginx.conf
  cp "$payload/scripts/start-screen.sh" /usr/local/bin/start-ruoyi-screen.sh
  chmod 755 /home /home/goview /home/goview/projects
  chmod -R a+rX /home/goview/projects/goview
  chmod 700 /usr/local/bin/start-ruoyi-screen.sh
  sh /usr/local/bin/start-ruoyi-screen.sh
fi
