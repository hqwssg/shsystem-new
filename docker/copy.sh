#!/bin/sh
set -eu

usage() {
	echo "Usage: sh copy.sh"
	exit 1
}

echo "begin copy sql"
PYTHON_BIN=${PYTHON_BIN:-python3}
"$PYTHON_BIN" ../tools/zhongkong/generate_dataset_sql.py
mkdir -p ./mysql/db
cp ../sql/carbon_emissions.sql ./mysql/db
cp ../sql/logging_migration.sql ./mysql/db/logging_migration.sql
cp ../tpfhs-9/backend/src/main/resources/schema.sql ./mysql/db/schema_1.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20260916-charset-repair.sql ./mysql/db/zz00_charset_repair.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20261015-source-node.sql ./mysql/db/zz00b_source_node.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20261015-energy-attribution.sql ./mysql/db/zz00c_energy_attribution.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20261018-calculation-company.sql ./mysql/db/zz00c_calculation_company.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20261019-node-factor-snapshot.sql ./mysql/db/zz00d_node_factor_snapshot.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20261010-collection-cycle.sql ./mysql/db/zz00a_collection_record_cycle.sql
cp ../sql/carbon-report/V1__report_tables.sql ./mysql/db/zz01_report_tables.sql
cp ../sql/carbon-report/V11__shuohuang_project_integration.sql ./mysql/db/zz02_report_project_integration.sql
cp ../sql/carbon-report/V13__report_subject_alignment.sql ./mysql/db/zz02a_report_subject_alignment.sql
cp ../sql/carbon-report/V12__local_observation_fixtures.sql ./mysql/db/zz02b_local_observation_fixtures.sql
cp ../sql/carbon-report/V14__calculation_factor_compatibility.sql ./mysql/db/zz02c_calculation_factor_compatibility.sql
cp ../sql/carbon-report/V16__default_report_images.sql ./mysql/db/zz02d_default_report_images.sql
cp ../sql/carbon-report/V17__report_subject_mapping_repair.sql ./mysql/db/zz02e_report_subject_mapping_repair.sql
cp ../sql/carbon_permission_model.sql ./mysql/db/zz03_carbon_permission_model.sql
cp ../sql/carbon_module_permissions.sql ./mysql/db/zz03a_carbon_module_permissions.sql
cp ../sql/goview_permissions_migration.sql ./mysql/db/zz03b_goview_menus.sql
cp ../sql/carbon-report/V3__menus.sql ./mysql/db/zz03c_report_menus.sql
cp ../sql/carbon_collection_scope_permissions.sql ./mysql/db/zz04_carbon_collection_scope_permissions.sql
cp ../sql/carbon_auto_collection_manual_permission.sql ./mysql/db/zz04a_auto_collection_manual_permission.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20260912.sql ./mysql/db/zz04b_factor_precision.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20260921-collection-status.sql ./mysql/db/zz04c_collection_status.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20260921-validation-idempotency-exclusion.sql ./mysql/db/zz04d_validation_idempotency.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20260923-collection-rollover.sql ./mysql/db/zz04e_collection_rollover.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20260924-manual-review.sql ./mysql/db/zz04f_manual_review.sql
cp ../sql/system_config_unique.sql ./mysql/db/zz04g_system_config_unique.sql
cp ../sql/carbon-energy/V1__energy_tables.sql ./mysql/db/zz05_energy_tables.sql
cp ../sql/carbon-energy/V2__menus.sql ./mysql/db/zz06_energy_menus.sql
cp ../sql/carbon-energy/V5__shuohuang_full_dataset.sql ./mysql/db/zz06a_energy_full_dataset.sql
cp ../sql/carbon-energy/V6__train_telemetry_segment_energy.sql ./mysql/db/zz06c_energy_telemetry.sql
cp ../sql/carbon-energy/V7__portable_energy_compatibility.sql ./mysql/db/zz06d_energy_portable_compatibility.sql
cp ../sql/carbon-energy/V8__fix_energy_run_delete.sql ./mysql/db/zz06e_energy_run_delete_fix.sql
cp ../sql/carbon-energy/V10__remove_compatibility_fixtures.sql ./mysql/db/zz06f_remove_compatibility_fixtures.sql
cp ../sql/carbon_statistics_demo.sql ./mysql/db/zz07_carbon_statistics_demo.sql
cp ../sql/carbon-analysis/V1__menus.sql ./mysql/db/zz08_carbon_analysis_menus.sql
cp ../sql/carbon-analysis/V2__display_seed.sql ./mysql/db/zz09_carbon_analysis_display_seed.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20261013-meter-model-seed.sql ./mysql/db/zz10_meter_model_seed.sql
cp ../sql/carbon-single-train/V1__tables.sql ./mysql/db/zz11_single_train_tables.sql
cp ../sql/carbon-single-train/V2__menus.sql ./mysql/db/zz12_single_train_menus.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20261016-uncertainty.sql ./mysql/db/zz13_uncertainty_tables.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20261020-dqi-collection-points.sql ./mysql/db/zz14_dqi_collection_points.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20261021-dqi-factor-results.sql ./mysql/db/zz15_dqi_factor_results.sql
cp ../sql/carbon-uncertainty/V1__menus.sql ./mysql/db/zz16_uncertainty_menus.sql
cp ../railway_carbon_prediction/sql/001_schema.sql ./mysql/db/zz17_prediction_schema.sql
cp ../railway_carbon_prediction/sql/002_seed.sql ./mysql/db/zz18_prediction_seed.sql
cp ../railway_carbon_prediction/sql/003_factor_snapshot.sql ./mysql/db/zz19_prediction_factor_snapshot.sql
cp ../railway_carbon_prediction/sql/004_fix_non_jlg_traction.sql ./mysql/db/zz20_prediction_traction_fix.sql
cp ../railway_carbon_prediction/sql/005_ingest_guard_audit.sql ./mysql/db/zz21_prediction_ingest_guard.sql
cp ../sql/carbon-prediction/V1__prediction_permissions.sql ./mysql/db/zz22_prediction_permissions.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20261103-node-company-monthly-data.sql ./mysql/db/zz23_node_company_monthly_data.sql
cp ../tpfhs-9/backend/src/main/resources/schema-update-20261103-trend-prediction-auto-ingest.sql ./mysql/db/zz24_trend_prediction_auto_ingest.sql

if [ "${1:-}" = "--sql-only" ]; then
    exit 0
fi

echo "begin copy ruoyi-admin"
mkdir -p ./web-main/jar ./web-main/html/dist ./web-main/html/carbon-model ./web-main/python
cp ../ruoyi-admin/target/ruoyi-admin.jar ./web-main/jar/ruoyi-admin.jar
cp "../tpfhs-9/uncertainty-app/target/uncertainty-app-1.0.0.jar" ./web-main/jar/uncertainty-app.jar
cp "../railway_carbon_prediction/railway_carbon_platform/backend/target/carbon-platform-1.0.0.jar" ./web-main/jar/prediction-platform.jar
cp -r ../ruoyi-ui/dist/. ./web-main/html/dist/
cp "../tpfhs-9/backend/target/carbon-emission-model-1.0.0.jar" ./web-main/jar/carbon-emission-model.jar
cp -r "../tpfhs-9/frontend/dist/." ./web-main/html/carbon-model/
mkdir -p ./web-main/html/prediction
cp -r "../railway_carbon_prediction/railway_carbon_platform/frontend/dist/." ./web-main/html/prediction/
cp ../docker/web-main/python/steam_calculator.py ./web-main/python/steam_calculator.py
mkdir -p ./web-main/renderer
rm -rf ./web-main/renderer/carbon_report_agent
cp -r ../carbon_report_agent ./web-main/renderer/carbon_report_agent
rm -rf ./web-main/energy-engine
cp -r ../energy_recovery_agent ./web-main/energy-engine
rm -rf ./web-main/prediction-engine
mkdir -p ./web-main/prediction-engine
cp -r ../railway_carbon_prediction/src ../railway_carbon_prediction/scripts ../railway_carbon_prediction/config \
  ../railway_carbon_prediction/data ../railway_carbon_prediction/artifacts ../railway_carbon_prediction/sql \
  ../railway_carbon_prediction/requirements.txt \
  ./web-main/prediction-engine/
rm -rf ./web-main/single-train-engine ./web-main/single-train-algorithm
cp -r ../single_train_recovery_agent ./web-main/single-train-engine
cp -r ../new_function/single_train_energy_optimization-f6d1797 ./web-main/single-train-algorithm

echo "begin copy goview"
mkdir -p ./web-screen/jar ./web-screen/html/dist ./web-screen/sqllite ./web-screen/upload
cp ../goview/go-view-serve-master/target/goview_admin-0.0.1-SNAPSHOT.war ./web-screen/jar/goview.war
cp -r ../goview/go-view-master-fetch/dist/. ./web-screen/html/dist/
cp ../goview/go-view-serve-master/sqllite/goview.db ./web-screen/sqllite/goview.db
if [ -d ../goview/upload ]; then
	cp -r ../goview/upload/. ./web-screen/upload/
fi
find ./web-screen/html/dist -type f -name "*.js" -exec sed -i \
	-e 's#http://127.0.0.1:8083/api/goview#/api/goview#g' \
	-e 's#http://localhost:8083/api/goview#/api/goview#g' {} \;
