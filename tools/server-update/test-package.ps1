# Keep the UTF-8 BOM so Windows PowerShell 5.1 parses the Chinese validation messages correctly.
param(
    [Parameter(Mandatory=$true)][string]$Directory,
    [switch]$Lightweight,
    [switch]$ModelLightweight
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath $Directory).Path
if ([IO.File]::ReadAllText("$Root/SHA256SUMS").Contains("`r")) { throw 'SHA256SUMS must use Linux LF line endings.' }
$Expected = [IO.File]::ReadAllLines("$Root/SHA256SUMS")
$Files = Get-ChildItem -LiteralPath $Root -File -Recurse | Where-Object { $_.Name -notin @('SHA256SUMS', 'MANIFEST.txt') }
if ($Expected.Count -ne $Files.Count) { throw 'Checksum coverage does not match payload file count.' }
foreach ($Line in $Expected) {
    if ($Line -notmatch '^([0-9a-f]{64})  (.+)$') { throw 'Invalid SHA256 record.' }
    $Hash = $Matches[1]
    $Path = [IO.Path]::GetFullPath((Join-Path $Root $Matches[2]))
    if (-not $Path.StartsWith($Root + [IO.Path]::DirectorySeparatorChar)) { throw 'Unsafe manifest path.' }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() -ne $Hash) { throw "Hash mismatch: $Path" }
}
if ($Lightweight) {
    foreach ($Required in @(
        'lightweight-apply.sh',
        'scripts/start-web.sh',
        'web-main/jar/ruoyi-admin.jar',
        'web-main/html/dist/index.html',
        'web-main/energy-engine/database/cli.py',
        'web-main/requirements-cli.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $Required) -PathType Leaf)) {
            throw "Missing lightweight payload: $Required"
        }
    }
    $Wheels = Get-ChildItem -LiteralPath "$Root/web-main/wheels" -Filter 'pyyaml-*.whl' -File
    foreach ($Abi in @('cp310', 'cp311', 'cp312')) {
        if (-not ($Wheels.Name -match $Abi)) { throw "PyYAML wheelhouse does not cover $Abi." }
    }
    $Apply = [IO.File]::ReadAllText((Join-Path $Root 'lightweight-apply.sh'))
    if ($Apply -notmatch 'pip install --no-index' -or $Apply -notmatch 'start-web.sh') {
        throw 'Lightweight apply script does not install offline dependencies and UTF-8 runtime.'
    }
    Write-Host "PASS: lightweight payload hashes, JAR, frontend, UTF-8 runtime, and PyYAML wheels."
    exit 0
}
if ($ModelLightweight) {
    foreach ($Required in @(
        'model-lightweight-apply.sh',
        'SERVER-UPDATE.md',
        'web-main/jar/carbon-emission-model.jar',
        'web-main/html/carbon-model/index.html')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $Required) -PathType Leaf)) {
            throw "Missing model lightweight payload: $Required"
        }
    }
    if (Get-ChildItem -LiteralPath $Root -Filter '*.sql' -File -Recurse) {
        throw 'Model lightweight package must not contain SQL.'
    }
    $Apply = [IO.File]::ReadAllText((Join-Path $Root 'model-lightweight-apply.sh'))
    if ($Apply -notmatch 'model-before\.tgz' -or
        $Apply -notmatch 'stop_java carbon-emission-model\.jar' -or
        $Apply -match 'ruoyi-admin\.jar|goview\.war|/home/goview|mysql/migrations') {
        throw 'Model lightweight apply script has an unsafe or incomplete update scope.'
    }
    $ModelRoot = Join-Path $Root 'web-main/html/carbon-model'
    $ModelHtml = [IO.File]::ReadAllText((Join-Path $ModelRoot 'index.html'))
    if ($ModelHtml -notmatch '/carbon-model/assets/') {
        throw 'Model frontend has an incorrect production base path.'
    }
    foreach ($Match in [regex]::Matches($ModelHtml, '(?:src|href)="([^"]+\.(?:js|css))(?:\?[^\"]*)?"')) {
        $AssetPath = $Match.Groups[1].Value
        if ($AssetPath.StartsWith('/carbon-model/')) {
            $AssetPath = $AssetPath.Substring('/carbon-model/'.Length)
        }
        if (-not (Test-Path -LiteralPath (Join-Path $ModelRoot $AssetPath) -PathType Leaf)) {
            throw "Missing model frontend asset: $AssetPath"
        }
    }
    Write-Host 'PASS: model lightweight payload hashes, JAR, frontend assets, update scope, and no SQL.'
    exit 0
}
if (-not (Test-Path -LiteralPath "$Root/initial-data/goview/goview.db" -PathType Leaf)) {
    throw 'Initial GoView database is missing from the deployment package.'
}
if (-not (Test-Path -LiteralPath "$Root/ROLE-PERMISSION-MATRIX.md" -PathType Leaf)) {
    throw 'Role permission matrix is missing from the deployment package.'
}
if (-not (Test-Path -LiteralPath "$Root/web-main/jar/uncertainty-app.jar" -PathType Leaf)) {
    throw 'Uncertainty analysis backend JAR is missing from the deployment package.'
}
foreach ($Required in @(
    'web-main/jar/prediction-platform.jar',
    'web-main/html/prediction/index.html',
    'web-main/prediction-engine/src/carbon_prediction/api.py',
    'web-main/prediction-engine/scripts/run_api.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $Root $Required) -PathType Leaf)) {
        throw "Prediction module payload is missing: $Required"
    }
}
$ReportDefaultsInitializer = "$Root/report-defaults/init_report_defaults.sh"
if (-not (Test-Path -LiteralPath $ReportDefaultsInitializer -PathType Leaf)) {
    throw 'Self-contained report defaults initializer is missing from the deployment package.'
}
$ReportDefaultsInitializerText = [IO.File]::ReadAllText($ReportDefaultsInitializer)
if ($ReportDefaultsInitializerText.Contains("`r") -or
    $ReportDefaultsInitializerText -notmatch 'REPORT_DEFAULTS_INIT_OK' -or
    $ReportDefaultsInitializerText -notmatch '--container' -or
    $ReportDefaultsInitializerText -notmatch '__CARBON_REPORT_DEFAULTS_SQL__') {
    throw 'Report defaults initializer is incomplete or does not use Linux LF line endings.'
}
$MaterialInitializers = @(
    @{
        Directory = 'report-equipment'
        Script = 'init_report_equipment.sh'
        Sql = 'init_report_equipment.sql'
        Check = 'check_equipment.sql'
        Marker = 'REPORT_EQUIPMENT_INIT_OK'
        HereDoc = '__CARBON_REPORT_DEFAULTS_SQL__'
    },
    @{
        Directory = 'report-images'
        Script = 'init_report_images.sh'
        Sql = 'init_report_images.sql'
        Check = 'check_images.sql'
        Marker = 'REPORT_IMAGES_INIT_OK'
        HereDoc = '__CARBON_REPORT_DEFAULTS_SQL__'
    }
)
foreach ($Initializer in $MaterialInitializers) {
    $Directory = Join-Path $Root $Initializer.Directory
    foreach ($Required in @($Initializer.Script, $Initializer.Sql, $Initializer.Check, 'manifest.json', 'README.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Directory $Required) -PathType Leaf)) {
            throw "Report material package is incomplete: $($Initializer.Directory)/$Required"
        }
    }
    $ScriptText = [IO.File]::ReadAllText((Join-Path $Directory $Initializer.Script))
    $SqlText = [IO.File]::ReadAllText((Join-Path $Directory $Initializer.Sql))
    if ($ScriptText.Contains("`r") -or $SqlText.Contains("`r") -or
        $ScriptText -notmatch [regex]::Escape($Initializer.Marker) -or
        $ScriptText -notmatch '--container' -or
        $ScriptText -match '__EMBEDDED_SQL__|__BACKUP_WHERE__' -or
        $ScriptText -notmatch 'mysqldump' -or
        $SqlText -match '(?im)^\s*DELETE\s+FROM\s+') {
        throw "Report material initializer is unsafe or incomplete: $($Initializer.Directory)"
    }
    $EmbeddedMatch = [regex]::Match(
        $ScriptText,
        "(?s)<<'$([regex]::Escape($Initializer.HereDoc))'\n(.*?)\n$([regex]::Escape($Initializer.HereDoc))"
    )
    if (-not $EmbeddedMatch.Success -or $EmbeddedMatch.Groups[1].Value -ne $SqlText) {
        throw "Embedded SQL differs from the standalone SQL: $($Initializer.Directory)"
    }
}
$EquipmentManifest = Get-Content -Raw -LiteralPath "$Root/report-equipment/manifest.json" | ConvertFrom-Json
$EquipmentRows = $EquipmentManifest.suning.rows + $EquipmentManifest.yuanping.rows + $EquipmentManifest.jiliang.rows
$MissingQuantities = $EquipmentManifest.suning.missing_quantity + $EquipmentManifest.yuanping.missing_quantity + $EquipmentManifest.jiliang.missing_quantity
if ($EquipmentRows -ne 70 -or $MissingQuantities -ne 7) {
    throw "Report equipment defaults are incomplete: rows=$EquipmentRows missing_quantities=$MissingQuantities"
}
$ImageManifest = Get-Content -Raw -LiteralPath "$Root/report-images/manifest.json" | ConvertFrom-Json
$ImageCount = @($ImageManifest.companies | ForEach-Object { $_.images }).Count
if (@($ImageManifest.companies).Count -ne 3 -or $ImageCount -ne 9) {
    throw "Report image defaults are incomplete: companies=$(@($ImageManifest.companies).Count) images=$ImageCount"
}
$HistoryInitializer = "$Root/report-history/init_business_history.sh"
$HistorySql = "$Root/report-history/business_history.sql"
$HistoryChecksum = "$Root/report-history/business_history.sql.sha256"
foreach ($Required in @($HistoryInitializer, $HistorySql, $HistoryChecksum, "$Root/report-history/manifest.json")) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "Business history package is incomplete: $Required"
    }
}
$HistoryInitializerText = [IO.File]::ReadAllText($HistoryInitializer)
$HistorySqlText = [IO.File]::ReadAllText($HistorySql)
if ($HistoryInitializerText.Contains("`r") -or $HistorySqlText.Contains("`r") -or
    $HistoryInitializerText -notmatch 'BUSINESS_HISTORY_INIT_OK' -or
    $HistorySqlText -notmatch 'BUSINESS_HISTORY_INIT_OK' -or
    $HistorySqlText -notmatch 'START TRANSACTION' -or
    $HistorySqlText -notmatch 'ROLLBACK') {
    throw 'Business history importer is incomplete or does not use Linux LF line endings.'
}
$HistoryHashLine = [IO.File]::ReadAllText($HistoryChecksum).Trim()
if ($HistoryHashLine -notmatch '^([0-9a-f]{64})  business_history\.sql$' -or
    (Get-FileHash -LiteralPath $HistorySql -Algorithm SHA256).Hash.ToLower() -ne $Matches[1]) {
    throw 'Business history SQL checksum mismatch.'
}
if (-not (Test-Path -LiteralPath "$Root/web-main/energy-engine/database/cli.py" -PathType Leaf) -or
    -not (Test-Path -LiteralPath "$Root/web-main/energy-engine/database/mysql.py" -PathType Leaf)) {
    throw 'Energy recovery Python engine is missing from the deployment package.'
}
if (-not (Test-Path -LiteralPath "$Root/web-main/single-train-engine/cli.py" -PathType Leaf) -or
    -not (Test-Path -LiteralPath "$Root/web-main/single-train-algorithm/regenerative_braking" -PathType Container)) {
    throw 'Single-train recovery engine or algorithm is missing from the deployment package.'
}
$Wheels = Get-ChildItem -LiteralPath "$Root/web-main/wheels" -Filter '*.whl' -File
foreach ($Abi in @('cp310', 'cp311', 'cp312')) {
    if (-not ($Wheels.Name -match $Abi)) {
        throw "Offline Linux wheelhouse does not cover $Abi."
    }
    if (-not ($Wheels.Name -match "torch-2\.6\.0\+cpu-$Abi")) {
        throw "CPU-only PyTorch wheelhouse does not cover $Abi."
    }
}
if (-not (Get-ChildItem -LiteralPath "$Root/web-main/wheels" -Filter 'mistune-*.whl' -File)) {
    throw 'Offline wheelhouse is missing the Mistune wheel required by requirements-cli.txt.'
}
$ZhongkongFiles = Get-ChildItem -LiteralPath "$Root/energy-data/zhongkong_data/data" -File -Recurse
$ZhongkongInitializer = Get-ChildItem -LiteralPath "$Root/energy-data/zhongkong_data" -File | Where-Object { $_.Extension -eq '.py' }
if ($ZhongkongFiles.Count -ne 28 -or
    $ZhongkongInitializer.Count -ne 1) {
    throw "Zhongkong dataset is incomplete: expected 28 data files and initializer, found $($ZhongkongFiles.Count)."
}
$Forbidden = $Files | Where-Object {
    (($_.Name -eq 'goview.db') -and $_.FullName -notmatch '[\\/]initial-data[\\/]') -or $_.Extension -eq '.pyc' -or
    $_.FullName -match '__pycache__|report-work|carbon_emissions.sql|schema_1.sql|[\\/]\.env$'
}
if ($Forbidden) { throw 'Production state or generated cache leaked into package.' }
$CheckedAssets = 0
$AssetPattern = @'
(?:src|href)\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))
'@
foreach ($Page in @(
    @('web-main/html/dist', ''),
    @('web-main/html/carbon-model', '/carbon-model/'),
    @('web-main/html/prediction', '/prediction/'),
    @('web-screen/html/dist', '')
)) {
    $PageRoot = Join-Path $Root $Page[0]
    $Html = [IO.File]::ReadAllText("$PageRoot/index.html")
    foreach ($Match in [regex]::Matches($Html, $AssetPattern.Trim())) {
        $Url = ($Match.Groups | Select-Object -Skip 1 | Where-Object Success | Select-Object -First 1).Value
        if ($Url -match '^(https?:|//|data:)' -or $Url -notmatch '\.(js|css|ico|png|jpg)(\?|$)') { continue }
        $Url = ($Url -split '\?')[0]
        if ($Page[1] -and $Url.StartsWith($Page[1])) { $Url = $Url.Substring($Page[1].Length) }
        $Asset = Join-Path $PageRoot $Url.TrimStart('/')
        if (-not (Test-Path -LiteralPath $Asset -PathType Leaf)) { throw "Missing HTML asset: $Asset" }
        $CheckedAssets++
    }
}
if ([IO.File]::ReadAllText("$Root/mysql/migrations/40_report_integration.sql") -match 'CAST\(.+ AS JSON\)') {
    throw 'MariaDB-incompatible JSON cast remains.'
}
$ObservationFixtureMigration = "$Root/mysql/migrations/41_local_observation_fixtures.sql"
$ObservationFixtures = [IO.File]::ReadAllText("$Root/mysql/optional/41_local_observation_fixtures.sql")
if (Test-Path -LiteralPath $ObservationFixtureMigration) {
    throw 'Local observation fixtures must not be included among production migrations.'
}
if ($ObservationFixtures -match '(?i)source_id\s*=\s*CAST\(' -or
    $ObservationFixtures -notmatch '(?i)BINARY\s+source_id\s*=\s*BINARY\s+CAST\(') {
    throw 'Report observation fixture still has a collation-sensitive source_id comparison.'
}
$ModelSchema = "$Root/mysql/migrations/15_model_schema.sql"
if (-not (Test-Path -LiteralPath $ModelSchema -PathType Leaf)) {
    throw 'Missing model schema completeness migration.'
}
$ModelSchemaSql = [IO.File]::ReadAllText($ModelSchema)
if ($ModelSchemaSql -notmatch '(?i)CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+emission_default_factor') {
    throw 'Model schema completeness migration does not create emission_default_factor.'
}
$ModelTableCount = [regex]::Matches($ModelSchemaSql, '(?im)^\s*CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+').Count
if ($ModelTableCount -lt 37) {
    throw "Model schema completeness migration has only $ModelTableCount CREATE TABLE statements."
}
if ($ModelSchemaSql -match '(?im)^\s*(DROP|TRUNCATE|ALTER|INSERT|UPDATE|DELETE)\s+') {
    throw 'Non-create statement found in model schema completeness migration.'
}
foreach ($Migration in @(
    '15e_node_factor_snapshot.sql',
    '16_charset_repair.sql',
    '53_validation_idempotency.sql',
    '54_collection_rollover.sql',
    '54a_manual_review.sql',
    '55_data_linkage.sql',
    '65_calculation_void.sql',
    '66_uncertainty_tables.sql',
    '67_dqi_collection_points.sql',
    '68_dqi_factor_results.sql',
    '69_node_factor_provenance.sql',
    '70_collection_point_monthly_data.sql',
    '71_uncertainty_menus.sql',
    '72_uncertainty_bit_compatibility.sql',
    '73_prediction_schema.sql',
    '74_prediction_seed.sql',
    '75_prediction_factor_snapshot.sql',
    '76_prediction_non_jlg_traction_fix.sql',
    '77_prediction_ingest_guard.sql',
    '78_prediction_permissions.sql',
    '79_node_company_monthly_data.sql',
    '80_trend_prediction_auto_ingest.sql',
    '81_complete_module_roles.sql',
    '83_prediction_monthly_source_snapshot.sql',
    '84_monthly_prediction_outbox.sql')) {
    if (-not (Test-Path -LiteralPath "$Root/mysql/migrations/$Migration" -PathType Leaf)) {
        throw "Missing model compatibility migration: $Migration"
    }
}
$NodeFactorMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/15e_node_factor_snapshot.sql")
if ($NodeFactorMigration -notmatch 'incomplete_factor_snapshot_count' -or
    $NodeFactorMigration -notmatch 'carbon_emission_factor_description\s*=\s*NULL') {
    throw 'Node factor snapshot migration is missing or incomplete.'
}
$CharsetMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/16_charset_repair.sql")
if ($CharsetMigration -notmatch '(?i)SET\s+NAMES\s+utf8mb4' -or
    $CharsetMigration -notmatch '(?i)CONVERT\(.+USING\s+latin1\).+USING\s+utf8mb4') {
    throw 'Charset repair migration is missing or incomplete.'
}
$ValidationMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/53_validation_idempotency.sql")
if ($ValidationMigration -match '迁移停止：历史核算任务存在重复模板周期' -or
    $ValidationMigration -notmatch 'index_exists\s*=\s*0\s+AND\s+duplicate_cycles\s*=\s*0') {
    throw 'Validation migration still rejects duplicate historical calculation cycles.'
}
$DataLinkageMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/55_data_linkage.sql")
if ($DataLinkageMigration -notmatch 'SET\s+ct\.data_revision\s*=\s*-ct\.id' -or
    $DataLinkageMigration -match '(?i)ADD\s+UNIQUE\s+(KEY|INDEX)\s+uk_template_cycle_revision') {
    throw 'Data linkage migration must preserve duplicate historical cycles without recreating the removed global unique index.'
}
$CalculationVoidMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/65_calculation_void.sql")
if ($CalculationVoidMigration -notmatch '(?i)DROP\s+INDEX\s+uk_template_cycle_revision') {
    throw 'Calculation void migration does not remove the unique cycle reservation index.'
}
$UncertaintyMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/66_uncertainty_tables.sql")
if ([regex]::Matches($UncertaintyMigration, '(?i)uncertainty_[a-z_]+').Value |
        Sort-Object -Unique | Where-Object { $_ } | Measure-Object | Select-Object -ExpandProperty Count | Where-Object { $_ -lt 9 }) {
    throw 'Uncertainty migration does not contain all nine DQI/MCS tables.'
}
$DqiCollectionMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/67_dqi_collection_points.sql")
$DqiFactorMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/68_dqi_factor_results.sql")
$NodeFactorProvenanceMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/69_node_factor_provenance.sql")
if ($DqiCollectionMigration -match '(?im)^\s*UPDATE\s+emission_' -or
    $DqiFactorMigration -match '(?im)^\s*UPDATE\s+emission_') {
    throw 'DQI migrations must not overwrite existing production scores with test data.'
}
if ($NodeFactorProvenanceMigration -notmatch 'carbon_emission_factor_source' -or
    $NodeFactorProvenanceMigration -notmatch 'carbon_emission_factor_id' -or
    $NodeFactorProvenanceMigration -notmatch 'carbon_emission_factor_dqi_e6_score' -or
    $NodeFactorProvenanceMigration -match '(?im)^\s*(UPDATE|DELETE|TRUNCATE)\s+') {
    throw 'Node factor provenance migration is missing required fields or rewrites historical data.'
}
$MonthlyDataMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/70_collection_point_monthly_data.sql")
if ($MonthlyDataMigration -notmatch 'emission_collection_node_data_month' -or
    $MonthlyDataMigration -notmatch 'uk_collection_point_year_month' -or
    $MonthlyDataMigration -notmatch 'idx_month_year_month' -or
    $MonthlyDataMigration -notmatch 'idx_month_data_status' -or
    $MonthlyDataMigration -match '(?im)^\s*(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\s+') {
    throw 'Monthly collection data migration is missing the required idempotent table/index definitions or rewrites data.'
}
$UncertaintyMenuMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/71_uncertainty_menus.sql")
if ($UncertaintyMenuMigration -notmatch 'carbon:uncertainty:view' -or
    $UncertaintyMenuMigration -match '(?m)INSERT\s+INTO\s+sys_menu\s+VALUES') {
    throw 'Uncertainty analysis menu migration is missing or uses fixed IDs.'
}
$UncertaintyCompatibilityMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/72_uncertainty_bit_compatibility.sql")
if ($UncertaintyCompatibilityMigration -notmatch 'uncertainty_dimension_rule' -or
    $UncertaintyCompatibilityMigration -notmatch 'MODIFY\s+enabled\s+TINYINT' -or
    $UncertaintyCompatibilityMigration -notmatch 'MODIFY\s+mark_default_filled\s+TINYINT' -or
    $UncertaintyCompatibilityMigration -match '(?im)^\s*(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\s+') {
    throw 'Uncertainty compatibility migration is missing safe BIT-to-TINYINT repairs.'
}
$PredictionSchema = [IO.File]::ReadAllText("$Root/mysql/migrations/73_prediction_schema.sql")
$PredictionPermissions = [IO.File]::ReadAllText("$Root/mysql/migrations/78_prediction_permissions.sql")
if ([regex]::Matches($PredictionSchema, '(?i)CREATE TABLE IF NOT EXISTS\s+`?prediction_').Count -lt 22 -or
    $PredictionSchema -match 'utf8mb4_0900_ai_ci') {
    throw 'Prediction schema is incomplete or incompatible with MySQL 5.7.'
}
foreach ($Permission in @('carbon:prediction:view','carbon:prediction:data:edit','carbon:prediction:review','carbon:prediction:model','carbon:prediction:forecast')) {
    if ($PredictionPermissions -notmatch [regex]::Escape($Permission)) {
        throw "Prediction permission migration is missing: $Permission"
    }
}
$MonthlySummaryMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/79_node_company_monthly_data.sql")
$TrendConfigMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/80_trend_prediction_auto_ingest.sql")
if ($MonthlySummaryMigration -notmatch 'emission_calc_node_summary_month' -or
    $MonthlySummaryMigration -notmatch 'emission_company_energy_summary_month' -or
    [regex]::Matches($MonthlySummaryMigration, '(?i)(UNIQUE|CREATE)\s+(?:KEY|INDEX)|ADD\s+CONSTRAINT').Count -lt 6) {
    throw 'Node/company monthly summary migration is incomplete.'
}
if ($TrendConfigMigration -notmatch 'carbon\.trend-prediction\.auto-ingest-company-monthly-data' -or
    $TrendConfigMigration -notmatch '(?i)WHERE\s+NOT\s+EXISTS' -or
    $TrendConfigMigration -match '(?i)ON\s+DUPLICATE\s+KEY\s+UPDATE') {
    throw 'Trend prediction auto-ingest configuration migration is not idempotent.'
}
$MonthlySourceMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/83_prediction_monthly_source_snapshot.sql")
if ($MonthlySourceMigration -notmatch 'prediction_monthly_source_head' -or
    $MonthlySourceMigration -notmatch 'prediction_monthly_source_receipt' -or
    $MonthlySourceMigration -notmatch 'uk_prediction_source_version' -or
    $MonthlySourceMigration -match '(?im)^\s*(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\s+') {
    throw 'Prediction monthly source snapshot migration is missing safe idempotent definitions.'
}
$MonthlyOutboxMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/84_monthly_prediction_outbox.sql")
if ($MonthlyOutboxMigration -notmatch 'emission_monthly_prediction_outbox' -or
    $MonthlyOutboxMigration -notmatch 'idx_monthly_outbox_version' -or
    $MonthlyOutboxMigration -notmatch 'idx_monthly_outbox_due' -or
    $MonthlyOutboxMigration -match '(?im)^\s*(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\s+') {
    throw 'Monthly prediction outbox migration is missing safe idempotent definitions.'
}
$CompleteRoleMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/81_complete_module_roles.sql")
foreach ($RoleKey in @(
    'company_admin','region_admin','department_admin','carbon_accountant',
    'carbon_data_entry','carbon_reviewer','carbon_auditor','screen_operator',
    'electricity_collector','energy_operator','single_train_operator','prediction_analyst')) {
    if ($CompleteRoleMigration -notmatch "'$([regex]::Escape($RoleKey))'") {
        throw "Complete role migration is missing role: $RoleKey"
    }
}
if ($CompleteRoleMigration -match '(?i)INSERT\s+INTO\s+sys_user|INSERT\s+INTO\s+sys_user_role|password\s*=' -or
    $CompleteRoleMigration -notmatch 'carbon:prediction:forecast' -or
    $CompleteRoleMigration -notmatch 'carbon:energy:version' -or
    $CompleteRoleMigration -notmatch 'carbon:singleTrain:version' -or
    $CompleteRoleMigration -notmatch 'goview:%') {
    throw 'Complete role migration is unsafe or does not cover all new modules.'
}
foreach ($RequiredField in @('ad_metering_tier', 'dqi_a1_score', 'ef_source_authority', 'dqi_e6_score')) {
    if (($DqiCollectionMigration + $DqiFactorMigration) -notmatch [regex]::Escape($RequiredField)) {
        throw "DQI migration is missing required field: $RequiredField"
    }
}
foreach ($Migration in @(
    '42_report_subject_alignment.sql',
    '59_carbon_analysis_menus.sql',
    '60_carbon_analysis_display_seed.sql',
    '61_meter_model_seed.sql',
    '62_single_train_preflight.sql',
    '63_single_train_tables.sql',
    '64_single_train_menus.sql',
    '44a_default_report_images.sql',
    '44b_report_subject_mapping_repair.sql')) {
    if (-not (Test-Path -LiteralPath "$Root/mysql/migrations/$Migration" -PathType Leaf)) {
        throw "Missing module integration migration: $Migration"
    }
}
$SingleTrainTables = [IO.File]::ReadAllText("$Root/mysql/migrations/63_single_train_tables.sql")
if ($SingleTrainTables -notmatch 'single_version' -or $SingleTrainTables -notmatch 'single_run' -or
    $SingleTrainTables -notmatch 'single_artifact') {
    throw 'Single-train database migration is incomplete.'
}
$ReportImages = [IO.File]::ReadAllText("$Root/mysql/migrations/44a_default_report_images.sql")
if ($ReportImages -notmatch 'report_file' -or $ReportImages -notmatch 'UNHEX') {
    throw 'Default report image migration is missing binary content.'
}
$SubjectRepair = [IO.File]::ReadAllText("$Root/mysql/migrations/44b_report_subject_mapping_repair.sql")
if ($SubjectRepair -notmatch 'fallback_subject_node_id' -or
    $SubjectRepair -notmatch 'parent_id = 0' -or
    $SubjectRepair -notmatch 'subject_node_id IS NULL') {
    throw 'Report subject mapping repair migration is incomplete.'
}
$TelemetryMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/48a_energy_telemetry.sql")
$PortableEnergyMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/48b_energy_portable_compatibility.sql")
if ($TelemetryMigration -match '(?i)FOREIGN\s+KEY' -or $PortableEnergyMigration -match '(?i)FOREIGN\s+KEY') {
    throw 'Telemetry compatibility migrations must not add collation-sensitive string foreign keys.'
}
$RunDeleteMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/48c_energy_run_delete_fix.sql")
if ($RunDeleteMigration -notmatch '(?i)candidate_fk_compatible' -or
    $RunDeleteMigration -notmatch '(?i)CHARACTER_SET_NAME' -or
    $RunDeleteMigration -notmatch '(?i)COLLATION_NAME') {
    throw 'Energy run-delete migration lacks mixed-collation foreign-key compatibility handling.'
}
$ManualReviewMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/54a_manual_review.sql")
if ($ManualReviewMigration -notmatch 'emission_collection_record_audit' -or
    $ManualReviewMigration -notmatch 'carbon.collection.manual.auto-approve') {
    throw 'Manual collection review migration is incomplete.'
}
$SystemConfigMigration = [IO.File]::ReadAllText("$Root/mysql/migrations/57_system_config_unique.sql")
if ($SystemConfigMigration -notmatch 'uk_sys_config_config_key' -or
    $SystemConfigMigration -notmatch 'DELETE duplicate_config') {
    throw 'Missing system configuration deduplication or unique index migration.'
}
$StatisticsDemo = [IO.File]::ReadAllText("$Root/mysql/migrations/58_carbon_statistics_demo.sql")
if ($StatisticsDemo -notmatch 'STAT-DEMO-' -or
    $StatisticsDemo -notmatch 'STAT-ELECTRICITY' -or
    $StatisticsDemo -notmatch 'STATISTICS_DEMO' -or
    $StatisticsDemo -notmatch '@statistics_window_start' -or
    $StatisticsDemo -notmatch 'collection_time\s*<\s*@statistics_window_start' -or
    $StatisticsDemo -match "CONCAT\('STAT-DEMO-',p\.point_type,'-',p\.point_id") {
    throw 'Statistics and GoView demonstration dataset is missing.'
}
$EnergyDatasetMigration = "$Root/mysql/migrations/47_energy_full_dataset.sql"
if (-not (Test-Path -LiteralPath $EnergyDatasetMigration -PathType Leaf)) {
    throw 'Complete Shuohuang dataset migration is missing.'
}
$EnergyDatasetSql = [IO.File]::ReadAllText($EnergyDatasetMigration)
if ($EnergyDatasetSql -match '(?i)existing_content_sha256\s+IN\s*\(' -or
    $EnergyDatasetSql -notmatch '(?i)BINARY\s+@existing_content_sha256\s*=\s*BINARY\s+@legacy_content_sha256' -or
    $EnergyDatasetSql -notmatch '(?i)BINARY\s+@existing_content_sha256\s*=\s*BINARY\s+@full_content_sha256') {
    throw 'Shuohuang dataset version guard still has a collation-sensitive hash comparison.'
}
foreach ($KeyColumn in @('project_code', 'version_code', 'station_code', 'timetable_code', 'train_type_code', 'station_name', 'train_no')) {
    if ($EnergyDatasetSql -match "(?i)(?<!BINARY\s)$KeyColumn\s*=\s*CONVERT\(") {
        throw "Shuohuang dataset key comparison is still collation-sensitive: $KeyColumn"
    }
}
if ([regex]::Matches($EnergyDatasetSql, 'INSERT INTO `energy_dataset_file`').Count -ne 28 -or
    $EnergyDatasetSql -notmatch 'route_segments' -or
    $EnergyDatasetSql -notmatch '1390') {
    throw 'Complete Shuohuang dataset migration does not contain the expected 28 source files and relational projection.'
}
$EnergyMenus = [IO.File]::ReadAllText("$Root/mysql/migrations/46_energy_menus.sql")
if ($EnergyMenus -match '(?m)SELECT\s+209[0-7]\s*,|INSERT\s+INTO\s+sys_menu\s+VALUES') {
    throw 'Energy menu migration still contains fixed menu IDs.'
}
foreach ($Permission in @(
    'carbon:energy:list','carbon:energy:query','carbon:energy:version','carbon:energy:run',
    'carbon:energy:cancel','carbon:energy:download','carbon:energy:project','carbon:energy:remove')) {
    if ($EnergyMenus -notmatch [regex]::Escape($Permission)) { throw "Energy permission missing: $Permission" }
}
$GoviewMenus = [IO.File]::ReadAllText("$Root/mysql/migrations/25_goview_menus.sql")
if ($GoviewMenus -match '(?m)insert\s+into\s+sys_menu\s+values\s*\(' -or
    $GoviewMenus -notmatch 'carbon-permissions' -or
    $GoviewMenus -notmatch 'goview:project:view') {
    throw 'GoView menu migration is missing or still uses fixed IDs.'
}
$ReportMenus = [IO.File]::ReadAllText("$Root/mysql/migrations/32_report_menus.sql")
if ($ReportMenus -match '(?m)SELECT\s+207[0-9]\s*,|INSERT\s+INTO\s+sys_menu\s+VALUES' -or
    $ReportMenus -notmatch 'carbon:report:list') {
    throw 'Report menu migration is missing or still uses fixed IDs.'
}
$MainNginx = [IO.File]::ReadAllText("$Root/web-main/conf/nginx.conf")
if ($MainNginx -notmatch 'X-Frame-Options\s+"SAMEORIGIN"' -or
    $MainNginx -notmatch "frame-ancestors 'self'" -or
    $MainNginx -notmatch 'location /uncertainty/' -or
    $MainNginx -notmatch '127\.0\.0\.1:8085' -or
    $MainNginx -notmatch 'location /prediction/' -or
    $MainNginx -notmatch 'location /prediction-api/' -or
    $MainNginx -notmatch '127\.0\.0\.1:8086') {
    throw 'Carbon model iframe response headers are missing.'
}
$DeployScript = [IO.File]::ReadAllText("$Root/deploy-update.sh")
$ContainerUpdateScript = [IO.File]::ReadAllText("$Root/scripts/container-update.sh")
if ($DeployScript -match '(?i)mysqldump|BACKUP_DIR|/opt/ruoyi-backups|backup_application' -or
    $ContainerUpdateScript -match '(?i)\.before-\$UPDATE_ID|BACKUP_DIR|/opt/ruoyi-backups|mysqldump') {
    throw 'Automatic update scripts must not create server-side backups.'
}
if ($ContainerUpdateScript -notmatch '(?s)set -a\s+\. /etc/carbon-integration\.env\s+set \+a') {
    throw 'Container update does not export DB_HOST and application database credentials.'
}
if ($ContainerUpdateScript -notmatch 'prediction_hist_activity_rows' -or
    $ContainerUpdateScript -notmatch 'prediction_hist_emission_rows' -or
    $ContainerUpdateScript -notmatch 'prediction baseline import is incomplete') {
    throw 'Container update does not detect and repair an interrupted prediction baseline import.'
}
if ($DeployScript -notmatch 'getOssInfo" 200,401,403') {
    throw 'GoView authenticated health check does not accept authorization responses.'
}
if ($DeployScript -notmatch 'Skipping 41_local_observation_fixtures\.sql' -or
    $DeployScript -notmatch '--resume-from' -or
    $DeployScript -notmatch 'before requested resume point') {
    throw 'Production update does not skip local fixtures or resume from an explicit migration.'
}
if ($DeployScript -notmatch 'sys_config repair verification failed') {
    throw 'System configuration repair is not verified after migration.'
}
if ($DeployScript -notmatch 'statistics demo migration is not stable') {
    throw 'Statistics demonstration records are not verified after migration.'
}
if ($DeployScript -notmatch 'manual review schema/config verification failed' -or
    $DeployScript -notmatch 'retired compatibility runs remain' -or
    $DeployScript -notmatch 'energy analysis migration verification failed') {
    throw 'Post-migration workflow or compatibility cleanup verification is missing.'
}
if ($DeployScript -notmatch 'complete Shuohuang dataset verification failed') {
    throw 'Complete Shuohuang dataset is not verified after migration.'
}
if ([IO.File]::ReadAllText("$Root/scripts/start-web.sh") -match 'characterEncoding=utf8(?:&|$)' -or
    [IO.File]::ReadAllText("$Root/scripts/start-web.sh") -notmatch 'characterEncoding=UTF-8' -or
    [IO.File]::ReadAllText("$Root/scripts/start-web.sh") -notmatch 'connectionCollation=utf8mb4_unicode_ci') {
    throw 'Packaged JDBC startup script does not use UTF-8 with the required MySQL collation.'
}
if ($DeployScript -notmatch 'all 36 energy tables already exist' -or
    $DeployScript -notmatch '45_energy_tables_repair.sql') {
    throw 'Partial energy-table repair path is missing.'
}
if ($DeployScript -notmatch 'STAGING/energy-data' -or
    [IO.File]::ReadAllText("$Root/scripts/container-update.sh") -notmatch 'energy-data/zhongkong_data') {
    throw 'Zhongkong dataset is not copied into the web runtime.'
}
$ScreenNginx = [IO.File]::ReadAllText("$Root/web-screen/conf/nginx.conf")
if ($ScreenNginx -notmatch 'location /carbon/' -or
    $ScreenNginx -notmatch '127\.0\.0\.1:8083') {
    throw 'GoView carbon statistics proxy is missing.'
}
if ($ScreenNginx -notmatch 'location /carbon-screen/' -or
    $ScreenNginx -notmatch 'proxy_pass http://ruoyi-web:8081/;') {
    throw 'GoView dashboard aggregation proxy is missing.'
}
$DashboardSwitcherAsset = Get-ChildItem -LiteralPath "$Root/web-screen/html/dist/static/js" -Filter '*.js' -File |
    Where-Object { Select-String -LiteralPath $_.FullName -SimpleMatch '切换大屏' -Quiet } |
    Select-Object -First 1
if (-not $DashboardSwitcherAsset) {
    throw 'GoView preview dashboard switcher is missing from the production assets.'
}
$Archive = "$Root.tar.gz"
$Sidecar = [IO.File]::ReadAllText("$Archive.sha256").Split(' ')[0]
if ((Get-FileHash $Archive -Algorithm SHA256).Hash.ToLower() -ne $Sidecar) { throw 'Archive checksum mismatch.' }
$Entries = & tar.exe -tzf $Archive
if ($LASTEXITCODE -ne 0 -or -not $Entries) { throw 'Archive is unreadable.' }
$Prefix = (Split-Path $Root -Leaf) + '/'
if ($Entries | Where-Object { -not $_.StartsWith($Prefix) -or $_ -match '(^|/)\.\.(/|$)' }) { throw 'Unsafe archive structure.' }
"PASS: $($Files.Count) payload hashes, $CheckedAssets HTML assets, archive structure/hash, no local state, MariaDB JSON compatibility."
