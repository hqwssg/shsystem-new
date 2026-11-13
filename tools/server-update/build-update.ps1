param(
    [switch]$SkipBuild,
    [string]$OfflineWheelhouse
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Name = "server-update-$Stamp"
$Destination = Join-Path $Root "deploy-package/$Name"
$LogDir = Join-Path $Root "deploy-package/build-logs-$Stamp"
New-Item -ItemType Directory -Path $Destination, $LogDir | Out-Null

function Invoke-Build($Label, $Directory, $Executable, $Arguments) {
    Write-Host "Building $Label ..."
    Push-Location $Directory
    $Previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Executable @Arguments *> (Join-Path $LogDir "$Label.log")
        $Code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $Previous
        Pop-Location
    }
    if ($Code -ne 0) { throw "$Label failed ($Code). See $LogDir/$Label.log" }
}

if (-not $SkipBuild) {
    $MavenCommand = Get-Command mvnd.exe -ErrorAction SilentlyContinue
    if (-not $MavenCommand) {
        $MavenCommand = Get-Command mvn.cmd -ErrorAction SilentlyContinue
    }
    if (-not $MavenCommand) {
        throw 'Maven or Maven Daemon is required to build the update package.'
    }
    $Maven = $MavenCommand.Source
    $Npm = (Get-Command npm.cmd).Source
    Invoke-Build 'main-backend' $Root $Maven @('-pl', 'ruoyi-admin', '-am', 'package')
    Invoke-Build 'model-backend' "$Root/tpfhs-9/backend" $Maven @('package')
    Invoke-Build 'uncertainty-backend' "$Root/tpfhs-9/uncertainty-app" $Maven @('package')
    Invoke-Build 'prediction-backend' "$Root/railway_carbon_prediction/railway_carbon_platform/backend" $Maven @('package')
    Invoke-Build 'goview-backend' "$Root/goview/go-view-serve-master" $Maven @('package')
    foreach ($Frontend in @('ruoyi-ui', 'tpfhs-9/frontend', 'goview/go-view-master-fetch', 'railway_carbon_prediction/railway_carbon_platform/frontend')) {
        if (-not (Test-Path "$Root/$Frontend/node_modules")) {
            throw "Missing node_modules: $Frontend. Install dependencies before building."
        }
    }
    Invoke-Build 'main-frontend' "$Root/ruoyi-ui" $Npm @('run', 'build:prod')
    Invoke-Build 'model-frontend' "$Root/tpfhs-9/frontend" $Npm @('run', 'build:server')
    Invoke-Build 'prediction-frontend' "$Root/railway_carbon_prediction/railway_carbon_platform/frontend" $Npm @('run', 'build')
    $Previous = $env:VITE_PRO_PATH
    try {
        $env:VITE_PRO_PATH = ''
        Invoke-Build 'goview-frontend' "$Root/goview/go-view-master-fetch" $Npm @('run', 'build')
    } finally { $env:VITE_PRO_PATH = $Previous }
}

$Python = (Get-Command python.exe -ErrorAction SilentlyContinue)
if (-not $Python) { $Python = Get-Command python -ErrorAction Stop }
if (-not (Test-Path -LiteralPath (Join-Path $Root 'sql/carbon-energy/V5__shuohuang_full_dataset.sql'))) {
    throw 'Reviewed Shuohuang dataset migration is missing.'
}

function Copy-Payload($Source, $Target) {
    $SourcePath = Join-Path $Root $Source
    $TargetPath = Join-Path $Destination $Target
    if (-not (Test-Path -LiteralPath $SourcePath)) { throw "Missing artifact: $SourcePath" }
    New-Item -ItemType Directory -Force -Path (Split-Path $TargetPath -Parent) | Out-Null
    Copy-Item -LiteralPath $SourcePath -Destination $TargetPath -Recurse
}

Copy-Payload 'ruoyi-admin/target/ruoyi-admin.jar' 'web-main/jar/ruoyi-admin.jar'
Copy-Payload 'tpfhs-9/backend/target/carbon-emission-model-1.0.0.jar' 'web-main/jar/carbon-emission-model.jar'
Copy-Payload 'tpfhs-9/uncertainty-app/target/uncertainty-app-1.0.0.jar' 'web-main/jar/uncertainty-app.jar'
Copy-Payload 'railway_carbon_prediction/railway_carbon_platform/backend/target/carbon-platform-1.0.0.jar' 'web-main/jar/prediction-platform.jar'
Copy-Payload 'goview/go-view-serve-master/target/goview_admin-0.0.1-SNAPSHOT.war' 'web-screen/jar/goview.war'
Copy-Payload 'ruoyi-ui/dist' 'web-main/html/dist'
Copy-Payload 'tpfhs-9/frontend/dist' 'web-main/html/carbon-model'
Copy-Payload 'railway_carbon_prediction/railway_carbon_platform/frontend/dist' 'web-main/html/prediction'
Copy-Payload 'goview/go-view-master-fetch/dist' 'web-screen/html/dist'
# Keep a baseline GoView database/assets for first-time deployments. The
# update script never copies this directory into a running production volume.
Copy-Payload 'goview/go-view-serve-master/sqllite/goview.db' 'initial-data/goview/goview.db'
if (Test-Path -LiteralPath (Join-Path $Root 'goview/upload')) {
    Copy-Payload 'goview/upload' 'initial-data/goview/upload'
}
# The Zhongkong/Shuohuang planning-placeholder dataset is consumed by the
# energy CLI import flow. Keep the original Chinese relative paths intact.
Copy-Payload 'zhongkong_data' 'energy-data/zhongkong_data'
Copy-Payload 'docker/web-main/conf/nginx.conf' 'web-main/conf/nginx.conf'
Copy-Payload 'docker/web-screen/conf/nginx.conf' 'web-screen/conf/nginx.conf'
Copy-Payload 'docker/web-main/python/steam_calculator.py' 'web-main/python/steam_calculator.py'
Copy-Payload 'docker/web-main/requirements-cli.txt' 'web-main/requirements-cli.txt'
Copy-Payload 'single_train_recovery_agent' 'web-main/single-train-engine'
Copy-Payload 'new_function/single_train_energy_optimization-f6d1797' 'web-main/single-train-algorithm'

# Prediction runtime source, trained artifacts and source datasets. Build caches
# and the two platform source trees are deliberately not shipped to production.
foreach ($PredictionEntry in @('src', 'scripts', 'config', 'data', 'artifacts', 'sql', 'requirements.txt')) {
    Copy-Payload "railway_carbon_prediction/$PredictionEntry" "web-main/prediction-engine/$PredictionEntry"
}

# Build an offline Linux x86_64 wheelhouse. The update target does not need
# PyPI access; pip selects the compatible wheel for its Python runtime.
$Wheelhouse = Join-Path $Destination 'web-main/wheels'
New-Item -ItemType Directory -Force -Path $Wheelhouse | Out-Null
if ($OfflineWheelhouse) {
    $OfflineWheelhousePath = (Resolve-Path -LiteralPath $OfflineWheelhouse).Path
    $OfflineWheels = Get-ChildItem -LiteralPath $OfflineWheelhousePath -Filter '*.whl' -File
    if ($OfflineWheels.Count -lt 20) {
        throw "Offline wheelhouse is incomplete: $OfflineWheelhousePath"
    }
    if (-not (Get-ChildItem -LiteralPath $OfflineWheelhousePath -Filter 'mistune-*.whl' -File)) {
        throw "Offline wheelhouse is missing the Mistune wheel required by requirements-cli.txt: $OfflineWheelhousePath"
    }
    Write-Host "Reusing verified offline Linux wheels from $OfflineWheelhousePath ..."
    Copy-Item -LiteralPath $OfflineWheels.FullName -Destination $Wheelhouse
} else {
    $BaseRequirements = Join-Path $LogDir 'requirements-without-torch.txt'
    $BaseRequirementLines = Get-Content -LiteralPath (Join-Path $Root 'docker/web-main/requirements-cli.txt') |
        Where-Object { $_ -notmatch '^\s*torch\s*[=<>!~]' }
    [IO.File]::WriteAllLines($BaseRequirements, $BaseRequirementLines, (New-Object System.Text.UTF8Encoding($false)))
    foreach ($PythonVersion in @('310', '311', '312')) {
        Write-Host "Downloading Linux wheels for CPython $PythonVersion ..."
        & $Python.Source -m pip download `
            --disable-pip-version-check `
            --only-binary=:all: `
            --platform manylinux2014_x86_64 `
            --implementation cp `
            --python-version $PythonVersion `
            --abi "cp$PythonVersion" `
            --dest $Wheelhouse `
            --requirement $BaseRequirements
        if ($LASTEXITCODE -ne 0) { throw "Linux wheel download failed for CPython $PythonVersion." }
        Write-Host "Downloading CPU-only PyTorch wheel for CPython $PythonVersion ..."
        & $Python.Source -m pip download `
            --disable-pip-version-check `
            --no-deps `
            --only-binary=:all: `
            --index-url https://download.pytorch.org/whl/cpu `
            --platform linux_x86_64 `
            --implementation cp `
            --python-version $PythonVersion `
            --abi "cp$PythonVersion" `
            --dest $Wheelhouse `
            'torch==2.6.0+cpu'
        if ($LASTEXITCODE -ne 0) { throw "CPU PyTorch wheel download failed for CPython $PythonVersion." }
    }
}

# The Java service invokes the delivered solver through database.cli. Package
# source and reproducible fixtures, but omit generated outputs and caches.
$EnergyEngineRoot = Join-Path $Root 'energy_recovery_agent'
Get-ChildItem -LiteralPath $EnergyEngineRoot -File -Recurse | Where-Object {
    $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
    $_.FullName -notmatch '[\\/]\.pytest_cache[\\/]' -and
    $_.FullName -notmatch '[\\/]outputs[\\/]' -and
    $_.Extension -ne '.pyc'
} | ForEach-Object {
    $Relative = $_.FullName.Substring($EnergyEngineRoot.Length + 1)
    Copy-Payload "energy_recovery_agent/$Relative" "web-main/energy-engine/$Relative"
}

# Copy only renderer source/assets, never local generated outputs or Python caches.
$RendererRoot = Join-Path $Root 'carbon_report_agent'
Get-ChildItem -LiteralPath $RendererRoot -File -Recurse | Where-Object {
    $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc'
} | ForEach-Object {
    $Relative = $_.FullName.Substring($RendererRoot.Length + 1)
    Copy-Payload "carbon_report_agent/$Relative" "web-main/renderer/carbon_report_agent/$Relative"
}

Copy-Payload 'sql/logging_migration.sql' 'mysql/migrations/10_logging.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema.sql' 'mysql/migrations/15_model_schema.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261009-fossil-factor-units.sql' 'mysql/migrations/15a_fossil_factor_units.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261010-collection-cycle.sql' 'mysql/migrations/15b_collection_record_cycle.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261015-source-node.sql' 'mysql/migrations/15c_source_node.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261015-energy-attribution.sql' 'mysql/migrations/15c1_energy_attribution.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261018-calculation-company.sql' 'mysql/migrations/15d_calculation_company.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261019-node-factor-snapshot.sql' 'mysql/migrations/15e_node_factor_snapshot.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20260916-charset-repair.sql' 'mysql/migrations/16_charset_repair.sql'
Copy-Payload 'sql/carbon-report/V1__report_tables.sql' 'mysql/migrations/20_report_tables.sql'
Copy-Payload 'sql/carbon_permission_model.sql' 'mysql/migrations/30_permissions.sql'
Copy-Payload 'sql/carbon_module_permissions.sql' 'mysql/migrations/31_module_permissions.sql'
Copy-Payload 'sql/goview_permissions_migration.sql' 'mysql/migrations/25_goview_menus.sql'
Copy-Payload 'sql/carbon-report/V3__menus.sql' 'mysql/migrations/32_report_menus.sql'
Copy-Payload 'sql/carbon-report/V11__shuohuang_project_integration.sql' 'mysql/migrations/40_report_integration.sql'
Copy-Payload 'sql/carbon-report/V12__local_observation_fixtures.sql' 'mysql/optional/41_local_observation_fixtures.sql'
Copy-Payload 'sql/carbon-report/V13__report_subject_alignment.sql' 'mysql/migrations/42_report_subject_alignment.sql'
Copy-Payload 'sql/carbon-report/V14__calculation_factor_compatibility.sql' 'mysql/migrations/43_calculation_factor_compatibility.sql'
Copy-Payload 'sql/carbon-report/V15__report_file_content.sql' 'mysql/migrations/44_report_file_content.sql'
Copy-Payload 'sql/carbon-report/V16__default_report_images.sql' 'mysql/migrations/44a_default_report_images.sql'
Copy-Payload 'sql/carbon-report/V17__report_subject_mapping_repair.sql' 'mysql/migrations/44b_report_subject_mapping_repair.sql'
Copy-Payload 'sql/carbon-energy/V1__energy_tables.sql' 'mysql/migrations/45_energy_tables.sql'
Copy-Payload 'sql/carbon-energy/V2__menus.sql' 'mysql/migrations/46_energy_menus.sql'
Copy-Payload 'sql/carbon-energy/V5__shuohuang_full_dataset.sql' 'mysql/migrations/47_energy_full_dataset.sql'
Copy-Payload 'sql/carbon-energy/V6__train_telemetry_segment_energy.sql' 'mysql/migrations/48a_energy_telemetry.sql'
Copy-Payload 'sql/carbon-energy/V7__portable_energy_compatibility.sql' 'mysql/migrations/48b_energy_portable_compatibility.sql'
Copy-Payload 'sql/carbon-energy/V8__fix_energy_run_delete.sql' 'mysql/migrations/48c_energy_run_delete_fix.sql'
Copy-Payload 'sql/carbon-energy/V10__remove_compatibility_fixtures.sql' 'mysql/migrations/48d_remove_compatibility_fixtures.sql'
Copy-Payload 'sql/carbon-energy/V11__storage_planning.sql' 'mysql/migrations/48e_storage_planning.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20260912.sql' 'mysql/migrations/50_factor_precision.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20260921-collection-status.sql' 'mysql/migrations/52_collection_status.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20260921-validation-idempotency-exclusion.sql' 'mysql/migrations/53_validation_idempotency.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20260923-collection-rollover.sql' 'mysql/migrations/54_collection_rollover.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20260924-manual-review.sql' 'mysql/migrations/54a_manual_review.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20260930-data-linkage.sql' 'mysql/migrations/55_data_linkage.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261021-calculation-void.sql' 'mysql/migrations/65_calculation_void.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261016-uncertainty.sql' 'mysql/migrations/66_uncertainty_tables.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261020-dqi-collection-points.sql' 'mysql/migrations/67_dqi_collection_points.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261021-dqi-factor-results.sql' 'mysql/migrations/68_dqi_factor_results.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261026-node-factor-provenance.sql' 'mysql/migrations/69_node_factor_provenance.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261028-collection-point-monthly-data.sql' 'mysql/migrations/70_collection_point_monthly_data.sql'
Copy-Payload 'sql/carbon-uncertainty/V1__menus.sql' 'mysql/migrations/71_uncertainty_menus.sql'
Copy-Payload 'sql/carbon-uncertainty/V2__bit_compatibility.sql' 'mysql/migrations/72_uncertainty_bit_compatibility.sql'
Copy-Payload 'railway_carbon_prediction/sql/001_schema.sql' 'mysql/migrations/73_prediction_schema.sql'
Copy-Payload 'railway_carbon_prediction/sql/002_seed.sql' 'mysql/migrations/74_prediction_seed.sql'
Copy-Payload 'railway_carbon_prediction/sql/003_factor_snapshot.sql' 'mysql/migrations/75_prediction_factor_snapshot.sql'
Copy-Payload 'railway_carbon_prediction/sql/004_fix_non_jlg_traction.sql' 'mysql/migrations/76_prediction_non_jlg_traction_fix.sql'
Copy-Payload 'railway_carbon_prediction/sql/005_ingest_guard_audit.sql' 'mysql/migrations/77_prediction_ingest_guard.sql'
Copy-Payload 'sql/carbon-prediction/V1__prediction_permissions.sql' 'mysql/migrations/78_prediction_permissions.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261103-node-company-monthly-data.sql' 'mysql/migrations/79_node_company_monthly_data.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261103-trend-prediction-auto-ingest.sql' 'mysql/migrations/80_trend_prediction_auto_ingest.sql'
Copy-Payload 'sql/carbon-role/V1__complete_module_roles.sql' 'mysql/migrations/81_complete_module_roles.sql'
Copy-Payload 'tools/server-update/mysql/migrations/82_prediction_admin_grants.sql' 'mysql/migrations/82_prediction_admin_grants.sql'
Copy-Payload 'railway_carbon_prediction/sql/006_monthly_source_snapshot.sql' 'mysql/migrations/83_prediction_monthly_source_snapshot.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261106-monthly-prediction-outbox.sql' 'mysql/migrations/84_monthly_prediction_outbox.sql'
Copy-Payload 'sql/carbon_collection_scope_permissions.sql' 'mysql/migrations/55_collection_scopes.sql'
Copy-Payload 'sql/carbon_auto_collection_manual_permission.sql' 'mysql/migrations/56_auto_collection_manual_permission.sql'
Copy-Payload 'sql/system_config_unique.sql' 'mysql/migrations/57_system_config_unique.sql'
Copy-Payload 'sql/carbon_statistics_demo.sql' 'mysql/migrations/58_carbon_statistics_demo.sql'
Copy-Payload 'sql/carbon-analysis/V1__menus.sql' 'mysql/migrations/59_carbon_analysis_menus.sql'
Copy-Payload 'sql/carbon-analysis/V2__display_seed.sql' 'mysql/migrations/60_carbon_analysis_display_seed.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261013-meter-model-seed.sql' 'mysql/migrations/61_meter_model_seed.sql'
Copy-Payload 'sql/carbon-single-train/V0__preflight.sql' 'mysql/migrations/62_single_train_preflight.sql'
Copy-Payload 'sql/carbon-single-train/V1__tables.sql' 'mysql/migrations/63_single_train_tables.sql'
Copy-Payload 'sql/carbon-single-train/V2__menus.sql' 'mysql/migrations/64_single_train_menus.sql'
Copy-Payload 'sql/carbon_node_observation_fixtures.sql' 'mysql/optional/65_node_observation_fixtures.sql'
Copy-Payload 'sql/carbon_node_chinese_fixtures.sql' 'mysql/optional/66_chinese_node_fixtures.sql'
Copy-Payload 'sql/carbon_project_cleanup_and_test_users.sql' 'mysql/optional/60_cleanup_and_test_users.sql'
Copy-Payload 'tools/server-update/deploy-update.sh' 'deploy-update.sh'
Copy-Payload 'tools/server-update/container-update.sh' 'scripts/container-update.sh'
Copy-Payload 'tools/server-update/runtime-common.sh' 'scripts/runtime-common.sh'
Copy-Payload 'tools/server-update/start-web.sh' 'scripts/start-web.sh'
Copy-Payload 'tools/server-update/start-screen.sh' 'scripts/start-screen.sh'
Copy-Payload 'tools/server-update/verify-libreoffice.sh' 'scripts/verify-libreoffice.sh'
Copy-Payload 'tools/server-update/verify-report-render.sh' 'scripts/verify-report-render.sh'
Copy-Payload 'tools/server-update/verification/carbon-render-smoke.json' 'verification/carbon-render-smoke.json'
Copy-Payload 'tools/report-defaults' 'report-defaults'
Copy-Payload 'tools/report-history/package' 'report-history'
Copy-Payload 'docs/server-update-instructions.md' 'SERVER-UPDATE.md'
Copy-Payload 'docs/role-permission-matrix.md' 'ROLE-PERMISSION-MATRIX.md'
# Dashboard templates and the credential-safe importer are delivered separately
# from the GoView database. The importer only creates a new draft and never
# overwrites or publishes an existing production project.
Copy-Payload 'tools/dashboard/import-dashboard.mjs' 'dashboard/import-dashboard.mjs'
Copy-Payload 'tools/dashboard/repair-panorama.mjs' 'dashboard/repair-panorama.mjs'
Copy-Payload 'goview/go-view-master-fetch/public/templates/shuohuang-management-dashboard.json' 'dashboard/templates/shuohuang-management-dashboard.json'
Copy-Payload 'goview/go-view-master-fetch/public/templates/shuohuang-carbon-dashboard.json' 'dashboard/templates/shuohuang-carbon-dashboard.json'

# Generate the two opt-in report material initializers from the reviewed source
# data on every build. They preserve non-empty production data and must be run
# separately after the application update; deploy-update.sh never invokes them.
Write-Host 'Generating report equipment and image initializers ...'
& $Python.Source (Join-Path $Root 'scripts/report-compat/equipment/build_initializer.py') `
    --output (Join-Path $Destination 'report-equipment')
if ($LASTEXITCODE -ne 0) { throw 'Report equipment initializer generation failed.' }
& $Python.Source (Join-Path $Root 'scripts/report-compat/image-defaults/build_initializer.py') `
    --output (Join-Path $Destination 'report-images')
if ($LASTEXITCODE -ne 0) { throw 'Report image initializer generation failed.' }
Copy-Payload 'scripts/report-compat/equipment/README.txt' 'report-equipment/README.txt'
Copy-Payload 'scripts/report-compat/equipment/check_equipment.sql' 'report-equipment/check_equipment.sql'
Copy-Payload 'scripts/report-compat/image-defaults/README.txt' 'report-images/README.txt'
Copy-Payload 'scripts/report-compat/image-defaults/check_images.sql' 'report-images/check_images.sql'

# Directory copies can contain local Python bytecode generated during tests or
# development. Never ship it: it is platform-specific and may be stale. Run
# this after every Python-backed payload, including report-defaults, is copied.
Get-ChildItem -LiteralPath $Destination -File -Recurse |
    Where-Object { $_.Extension -eq '.pyc' -or $_.FullName -match '[\\/]__pycache__[\\/]' } |
    Remove-Item -Force
Get-ChildItem -LiteralPath $Destination -Directory -Recurse |
    Where-Object { $_.Name -eq '__pycache__' } |
    Sort-Object FullName -Descending |
    Remove-Item -Force -Recurse

$Utf8 = New-Object System.Text.UTF8Encoding($false)
$Readme = Join-Path $Destination 'SERVER-UPDATE.md'
$Instructions = [IO.File]::ReadAllText($Readme).Replace('server-update-TIMESTAMP', $Name).Replace('build-logs-TIMESTAMP', "build-logs-$Stamp")
[IO.File]::WriteAllText($Readme, $Instructions, $Utf8)
$Integration = Join-Path $Destination 'mysql/migrations/40_report_integration.sql'
$Sql = [IO.File]::ReadAllText($Integration)
# JSON columns accept a JSON string literal on both MySQL and MariaDB.
$Sql = [regex]::Replace($Sql, "CAST\(('(?:[^']|'')*') AS JSON\)", '$1')
[IO.File]::WriteAllText($Integration, $Sql, $Utf8)
$ModelSchema = Join-Path $Destination 'mysql/migrations/15_model_schema.sql'
$ModelSchemaSql = [IO.File]::ReadAllText($ModelSchema)
$CreateTableBlocks = [regex]::Matches(
    $ModelSchemaSql,
    '(?ms)^\s*CREATE TABLE IF NOT EXISTS\s+[^\r\n]+.*?^\s*\)[^;]*;\s*'
)
if ($CreateTableBlocks.Count -lt 37) {
    throw "Expected at least 37 model CREATE TABLE blocks, found $($CreateTableBlocks.Count)."
}
$ModelSchemaSql = "SET NAMES utf8mb4;`nUSE carbon_emissions;`n`n" +
    (($CreateTableBlocks | ForEach-Object { $_.Value.Trim() }) -join "`n`n") + "`n"
[IO.File]::WriteAllText($ModelSchema, $ModelSchemaSql, $Utf8)
Get-ChildItem $Destination -File -Recurse | Where-Object { $_.Extension -in @('.sh', '.sql') } | ForEach-Object {
    $Content = [IO.File]::ReadAllText($_.FullName).Replace("`r`n", "`n")
    [IO.File]::WriteAllText($_.FullName, $Content, $Utf8)
}

$ModelHtml = [IO.File]::ReadAllText("$Destination/web-main/html/carbon-model/index.html")
if ($ModelHtml -notmatch '/carbon-model/assets/') { throw 'Model frontend has an incorrect production base path.' }
$PredictionHtml = [IO.File]::ReadAllText("$Destination/web-main/html/prediction/index.html")
if ($PredictionHtml -notmatch '/prediction/assets/') { throw 'Prediction frontend has an incorrect production base path.' }
$Files = Get-ChildItem $Destination -File -Recurse | Sort-Object FullName
$Manifest = @(
    ('BuiltAt=' + (Get-Date -Format 'o'))
    ('GitCommit=' + (& git -C $Root rev-parse HEAD))
    'IncludesUncommittedWorktree=true'
)
foreach ($File in $Files) {
    $Relative = $File.FullName.Substring($Destination.Length + 1).Replace('\', '/')
    $Manifest += "$( (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLower() )  $Relative"
}
[IO.File]::WriteAllText("$Destination/MANIFEST.txt", ($Manifest -join "`n") + "`n", $Utf8)
$Checksums = $Manifest | Select-Object -Skip 3
[IO.File]::WriteAllText("$Destination/SHA256SUMS", ($Checksums -join "`n") + "`n", $Utf8)
$Archive = "$Destination.tar.gz"
& tar.exe -czf $Archive -C (Split-Path $Destination -Parent) $Name
if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
$Hash = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$Archive.sha256", "$Hash  $Name.tar.gz`n", $Utf8)
Write-Host "PACKAGE=$Archive"
Write-Host "DIRECTORY=$Destination"
Write-Host "LOGS=$LogDir"
Write-Host "SHA256=$Hash"
