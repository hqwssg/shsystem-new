param(
    [string]$PackageId = "database_deployment_integration_package_20260911_v4",
    [string]$OutputRoot = "deliverables"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputRootPath = Join-Path $projectRoot $OutputRoot
$packageRoot = Join-Path $outputRootPath $PackageId
$zipPath = Join-Path $outputRootPath ($PackageId + ".zip")

if (Test-Path -LiteralPath $packageRoot) {
    throw "Package directory already exists: $packageRoot"
}
if (Test-Path -LiteralPath $zipPath) {
    throw "Package archive already exists: $zipPath"
}

$files = @(
    "requirements-database.txt",
    "database/__init__.py",
    "database/bootstrap.sql",
    "database/security_roles.sql",
    "database/database.env.example",
    "database/database_contract.json",
    "database/interface_contract_freeze.json",
    "database/io_mapping.json",
    "database/parameters.py",
    "database/solver_budget.py",
    "database/platform_api_contract.json",
    "database/platform_query_examples.sql",
    "database/delivery_package_manifest.json",
    "database/dataset_projection.py",
    "database/result_projection.py",
    "database/postgres.py",
    "database/snapshots.py",
    "database/worker.py",
    "database/cli.py",
    "database/migrations/001_core.sql",
    "database/migrations/002_inputs.sql",
    "database/migrations/003_runs.sql",
    "database/migrations/004_outputs.sql",
    "database/migrations/005_rolling_control.sql",
    "database/migrations/006_run_transaction_idempotency.sql",
    "database/migrations/007_joint_parameter_robustness.sql",
    "database/examples/dispatch_parameters.json",
    "database/examples/timetable_audit_parameters.json",
    "database/examples/timetable_optimization_parameters.json",
    "database/examples/rolling_rescheduling_parameters.json",
    "database/examples/historical_disturbance_replay_parameters.json",
    "database/examples/joint_parameter_robustness_parameters.json",
    "database/examples/five_run_acceptance_manifest.json",
    "data_templates/running_diagram_template.xlsx",
    "data_templates/heavy_empty_od_template.xlsx",
    "data_templates/historical_disturbance_replay_template.json",
    "data_templates/joint_parameter_ranges_template.json",
    "tools/deploy_database.ps1",
    "tools/database_healthcheck.py",
    "tools/verify_target_database_access.py",
    "tools/run_database_worker_loop.py",
    "tools/run_database_five_run_acceptance.py",
    "tools/verify_database_five_run_e2e.py",
    "tools/platform_task_stress_fault.py",
    "tools/verify_platform_task_stress_results.py",
    "tools/verify_database_delivery_package.py",
    "tools/safe_zip.py",
    "tools/verify_interface_contract_freeze.py",
    "tools/local_postgres_test_instance.ps1",
    "docs/database_delivery_package_guide.md",
    "docs/interface_contract_freeze.md",
    "docs/prototype_backend_contract.json",
    "docs/database_platform_integration_handoff.md",
    "docs/database_platform_integration_checklist.md",
    "docs/database_integration_guide.md",
    "docs/database_runtime_transaction_idempotency.md",
    "docs/solver_resource_budget_and_degradation.md",
    "docs/historical_disturbance_replay_interface.md",
    "docs/database_storage_device_algorithm_binding.md",
    "docs/platform_task_stress_fault.md",
    "docs/optimization_attribution_and_bottleneck_report.md",
    "outputs/target_platform_predeployment/local_healthcheck.json",
    "outputs/target_platform_predeployment/local_four_account_access.json",
    "outputs/database_postgres_segregated_e2e_acceptance_v4/DATABASE_FIVE_RUN_E2E_REPORT.md",
    "outputs/database_postgres_segregated_e2e_acceptance_v4/database_five_run_e2e_summary.json",
    "outputs/database_postgres_segregated_e2e_acceptance_v4/segregated_account_acceptance_summary.json",
    "outputs/platform_task_stress_fault_current/PLATFORM_TASK_STRESS_FAULT_REPORT.md",
    "outputs/platform_task_stress_fault_current/platform_task_stress_fault_summary.json",
    "outputs/platform_task_stress_fault_scale_matrix/PLATFORM_TASK_STRESS_SCALE_REPORT.md",
    "outputs/platform_task_stress_fault_scale_matrix/platform_task_stress_scale_summary.json"
)

New-Item -ItemType Directory -Path $packageRoot | Out-Null
foreach ($relativePath in $files) {
    $sourcePath = Join-Path $projectRoot $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Required package file is missing: $relativePath"
    }
    $destinationPath = Join-Path $packageRoot $relativePath
    $destinationDirectory = Split-Path -Parent $destinationPath
    New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
}

$checksumLines = Get-ChildItem -LiteralPath $packageRoot -File -Recurse |
    Sort-Object FullName |
    ForEach-Object {
        $relativePath = $_.FullName.Substring($packageRoot.Length + 1).Replace("\", "/")
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $relativePath"
    }
$checksumPath = Join-Path $packageRoot "CHECKSUMS.sha256"
[System.IO.File]::WriteAllLines($checksumPath, $checksumLines, (New-Object System.Text.UTF8Encoding($false)))

Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal

Write-Output "package_root=$packageRoot"
Write-Output "zip_path=$zipPath"
Write-Output "file_count=$($files.Count + 1)"
