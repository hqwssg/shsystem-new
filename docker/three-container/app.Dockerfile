FROM maven:3.9-eclipse-temurin-17 AS app-build
WORKDIR /src
COPY . .
RUN mvn -B -DskipTests -pl ruoyi-admin -am package

FROM node:22-bookworm AS ui-build
WORKDIR /src
COPY ruoyi-ui/package.json ruoyi-ui/
RUN cd ruoyi-ui && npm install --legacy-peer-deps
COPY ruoyi-ui/ ruoyi-ui/
COPY ruoyi-modules/ruoyi-energy/src/main/resources/energy-report-names.json ruoyi-modules/ruoyi-energy/src/main/resources/energy-report-names.json
RUN cd ruoyi-ui && VUE_APP_GOVIEW_URL=/goview/ npm run build:prod

FROM node:22-bookworm AS goview-ui-build
WORKDIR /src
ARG VITE_PRO_PATH=
COPY goview/go-view-master-fetch/package.json goview/go-view-master-fetch/pnpm-lock.yaml goview/go-view-master-fetch/
RUN npm install -g pnpm@9.15.9 \
    && cd goview/go-view-master-fetch && HUSKY=0 pnpm install --frozen-lockfile
COPY goview/go-view-master-fetch/ goview/go-view-master-fetch/
RUN cd goview/go-view-master-fetch && VITE_PRO_PATH="$VITE_PRO_PATH" pnpm build

FROM node:22-bookworm AS prediction-ui-build
WORKDIR /src
COPY railway_carbon_prediction/railway_carbon_platform/frontend/package.json railway_carbon_prediction/railway_carbon_platform/frontend/package-lock.json ./
RUN npm ci
COPY railway_carbon_prediction/railway_carbon_platform/frontend/ ./
RUN npm run build

FROM node:22-bookworm AS carbon-ui-build
WORKDIR /src
COPY tpfhs-9/frontend/package.json tpfhs-9/frontend/package-lock.json ./
RUN npm ci
COPY tpfhs-9/frontend/ ./
RUN npm run build:server

FROM maven:3.9-eclipse-temurin-8 AS goview-build
WORKDIR /src
COPY goview/go-view-serve-master/ goview/go-view-serve-master/
RUN mvn -B -DskipTests package -f goview/go-view-serve-master/pom.xml \
    && cp goview/go-view-serve-master/target/*.war /tmp/goview.war

FROM maven:3.9-eclipse-temurin-17 AS prediction-app-build
WORKDIR /src
COPY railway_carbon_prediction/railway_carbon_platform/backend/ ./
RUN mvn -B -DskipTests package \
    && cp target/*.jar /tmp/carbon-platform.jar

FROM maven:3.9-eclipse-temurin-17 AS carbon-model-build
WORKDIR /src
COPY tpfhs-9/backend/ tpfhs-9/backend/
COPY sql/ sql/
RUN mvn -B -DskipTests package -f tpfhs-9/backend/pom.xml \
    && cp tpfhs-9/backend/target/*.jar /tmp/carbon-emission-model.jar

FROM maven:3.9-eclipse-temurin-17 AS uncertainty-build
WORKDIR /src
COPY tpfhs-9/uncertainty-app/ ./
RUN mvn -B -DskipTests package \
    && cp target/*.jar /tmp/uncertainty-app.jar

FROM eclipse-temurin:17-jre

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx redis-server libreoffice-writer fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home shsystem \
    && mkdir -p /opt/shsystem /srv/shared /data/redis /var/log/nginx /run/nginx /var/cache/nginx /etc/nginx/conf.d \
    && chown -R 10001:10001 /srv/shared /data/redis /var/log/nginx /run/nginx /var/cache/nginx

COPY --from=app-build /src/ruoyi-admin/target/ruoyi-admin.jar /opt/shsystem/ruoyi-admin.jar
COPY --from=ui-build /src/ruoyi-ui/dist/ /opt/shsystem/static/ruoyi-ui/
COPY --from=goview-ui-build /src/goview/go-view-master-fetch/dist/ /opt/shsystem/static/goview/
COPY --from=goview-build /tmp/goview.war /opt/shsystem/goview/goview.war
COPY --from=prediction-app-build /tmp/carbon-platform.jar /opt/shsystem/carbon-platform.jar
COPY --from=carbon-model-build /tmp/carbon-emission-model.jar /opt/shsystem/carbon-emission-model.jar
COPY --from=uncertainty-build /tmp/uncertainty-app.jar /opt/shsystem/uncertainty-app.jar
COPY --from=prediction-ui-build /src/dist/ /opt/shsystem/static/prediction/
COPY --from=carbon-ui-build /src/dist/ /opt/shsystem/static/carbon-model/
COPY goview/go-view-serve-master/sqllite/goview.db /opt/shsystem/goview/seed.db
COPY goview/upload/ /opt/shsystem/static/goview-upload/
COPY docker/three-container/app-start.sh /opt/shsystem/app-start.sh
COPY docker/three-container/nginx.conf /etc/nginx/nginx.conf

RUN chmod 0755 /opt/shsystem/app-start.sh \
    && chown -R 10001:10001 /opt/shsystem

USER 10001
ENV SERVER_PORT=8081 \
    GOVIEW_SERVER_PORT=8087 \
    CARBON_SERVER_PORT=8082 \
    UNCERTAINTY_SERVER_PORT=8085 \
    PREDICTION_PLATFORM_PORT=8086 \
    PREDICTION_BASE_URL=http://127.0.0.1:8090 \
    GOVIEW_DB_URL=jdbc:sqlite:/srv/shared/goview/goview.db \
    GOVIEW_UPLOAD_PATH=/srv/shared/goview-upload \
    GOVIEW_UPLOAD_MAPPING=file:/srv/shared/goview-upload/ \
    SPRING_DATA_REDIS_HOST=127.0.0.1 \
    SPRING_DATA_REDIS_PORT=6379 \
    CARBON_REPORT_SOFFICE_PATH=/usr/bin/libreoffice \
    CARBON_REPORT_WORK_DIR=/srv/shared/report-work \
    CARBON_REPORT_ARTIFACT_DIR=/srv/shared/reports \
    ENERGY_UPLOAD_DIR=/srv/shared/energy \
    ENERGY_PROJECT_ROOT=/opt/shsystem/energy_recovery_agent \
    SINGLE_TRAIN_WORKSPACE_ROOT=/srv/shared/single-train \
    SINGLE_TRAIN_RESULT_ROOT=/srv/shared/single-train/results \
    FILE_PATH=/srv/shared/uploads \
    FILE_DOMAIN=http://127.0.0.1 \
    GOVIEW_STATIC_ROOT=/opt/shsystem/static/goview
WORKDIR /opt/shsystem
EXPOSE 80 8081 8082 8085 8086 8087
ENTRYPOINT ["/opt/shsystem/app-start.sh"]
