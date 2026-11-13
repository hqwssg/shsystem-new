FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer fonts-noto-cjk gcc \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home shsystem

WORKDIR /opt/shsystem
COPY railway_carbon_prediction/requirements.txt /tmp/prediction-requirements.txt
COPY energy_recovery_agent/requirements.txt /tmp/energy-requirements.txt
COPY single_train_recovery_agent/requirements.txt /tmp/single-train-requirements.txt
COPY tpfreport/docker/web-main/requirements-cli.txt /tmp/report-requirements.txt
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir --index-url "$TORCH_INDEX_URL" 'torch>=2.0' \
    && python -m pip install --no-cache-dir -r /tmp/prediction-requirements.txt \
    && python -m pip install --no-cache-dir -r /tmp/energy-requirements.txt \
    && python -m pip install --no-cache-dir -r /tmp/single-train-requirements.txt \
    && python -m pip install --no-cache-dir -r /tmp/report-requirements.txt \
    && python -m pip install --no-cache-dir fastapi uvicorn[standard] pydantic PyMySQL psycopg[binary] \
    && mkdir -p /srv/shared

COPY services/python_service /opt/shsystem/services/python_service
COPY carbon_report_agent /opt/shsystem/carbon_report_agent
COPY energy_recovery_agent /opt/shsystem/energy_recovery_agent
COPY single_train_recovery_agent /opt/shsystem/single_train_recovery_agent
COPY new_function/single_train_energy_optimization-f6d1797 /opt/shsystem/single_train_algorithm
COPY railway_carbon_prediction /opt/shsystem/railway_carbon_prediction
COPY docker/web-main/python/steam_calculator.py /opt/shsystem/steam_calculator.py
COPY docker/three-container/python-start.sh /opt/shsystem/python-start.sh
RUN chmod 0755 /opt/shsystem/python-start.sh \
    && chown -R 10001:10001 /opt/shsystem /srv/shared

USER 10001
ENV PYTHONUNBUFFERED=1 \
    PYTHON_CODE_ROOT=/opt/shsystem \
    SHARED_ROOT=/srv/shared \
    SINGLE_TRAIN_RESULT_ROOT=/srv/shared/single-train/results \
    PREDICTION_ARTIFACT_DIR=/srv/shared/prediction/artifacts \
    API_HOST=0.0.0.0 \
    API_PORT=8090 \
    PYTHON_SERVICE_PORT=8091 \
    CERDB_DRIVER=postgresql
EXPOSE 8090 8091
ENTRYPOINT ["/opt/shsystem/python-start.sh"]
