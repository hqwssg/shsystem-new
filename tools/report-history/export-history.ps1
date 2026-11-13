param(
    [string]$Database = "carbon_emissions",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 3306,
    [string]$User = "root",
    [string]$Password = "",
    [string]$OutputDirectory = "$PSScriptRoot/package"
)

$ErrorActionPreference = "Stop"

if (-not $Password) {
    $secure = Read-Host "Database password" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $Password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

$mysql = (Get-Command mysql -ErrorAction Stop).Source
$mysqldump = (Get-Command mysqldump -ErrorAction Stop).Source
$tables = @(
    "emission_collection_record",
    "emission_collection_record_audit",
    "emission_calculation_template",
    "emission_calculation_data_state",
    "emission_calculation_node",
    "emission_collection_node_data",
    "emission_calc_node_summary",
    "report_task",
    "report_emission_source",
    "report_activity_fuel",
    "report_activity_electricity",
    "report_activity_heat",
    "report_workload",
    "report_equipment",
    "report_monitoring_device",
    "report_import_batch",
    "report_file",
    "report_generation_job"
)

$utf8 = [Text.UTF8Encoding]::new($false)
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("ruoyi-history-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

try {
    $preamble = @"
-- Generated business history snapshot. Insert-only and transactional.
SET NAMES utf8mb4;
SET time_zone = '+08:00';
SET sql_mode = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

"@

    foreach ($table in $tables) {
        $preamble += "DROP TEMPORARY TABLE IF EXISTS ``stg_$table``;`n"
        $preamble += "CREATE TEMPORARY TABLE ``stg_$table`` LIKE ``$table``;`n"
    }
    $preamble += "`n"

    $payload = [Text.StringBuilder]::new()
    [void]$payload.Append($preamble.Replace("`r`n", "`n"))
    $counts = [ordered]@{}

    foreach ($table in $tables) {
        $dumpFile = Join-Path $tempRoot "$table.sql"
        $args = @(
            "--host=$HostName", "--port=$Port", "--user=$User", "--password=$Password",
            "--default-character-set=utf8mb4", "--single-transaction", "--skip-lock-tables",
            "--no-create-info", "--skip-triggers", "--skip-add-locks", "--skip-disable-keys",
            "--complete-insert", "--hex-blob", "--no-tablespaces", "--set-gtid-purged=OFF",
            "--result-file=$dumpFile"
        )
        if ($table -eq "report_file") {
            $args += "--where=report_id IS NOT NULL"
        }
        $args += @($Database, $table)
        & $mysqldump @args
        if ($LASTEXITCODE -ne 0) { throw "mysqldump failed for $table" }

        $dump = [IO.File]::ReadAllText($dumpFile, $utf8).Replace("`r`n", "`n")
        $dump = $dump.Replace("INSERT INTO ``$table``", "INSERT INTO ``stg_$table``")
        [void]$payload.Append("`n-- $table`n")
        [void]$payload.Append($dump)

        $where = if ($table -eq "report_file") { " WHERE report_id IS NOT NULL" } else { "" }
        $query = "SELECT COUNT(*) FROM ``$table``$where;"
        $result = & $mysql "--host=$HostName" "--port=$Port" "--user=$User" "--password=$Password" `
            "--default-character-set=utf8mb4" "--batch" "--skip-column-names" "--database=$Database" "--execute=$query"
        if ($LASTEXITCODE -ne 0) { throw "count query failed for $table" }
        $counts[$table] = [int64]($result | Select-Object -Last 1)
    }

    $tailPath = Join-Path $PSScriptRoot "import-tail.sql"
    [void]$payload.Append("`n")
    [void]$payload.Append([IO.File]::ReadAllText($tailPath, $utf8).Replace("`r`n", "`n"))

    $sqlPath = Join-Path $OutputDirectory "business_history.sql"
    [IO.File]::WriteAllText($sqlPath, $payload.ToString(), $utf8)
    $hash = (Get-FileHash $sqlPath -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText((Join-Path $OutputDirectory "business_history.sql.sha256"), "$hash  business_history.sql`n", $utf8)

    $manifest = [ordered]@{
        package = "ruoyi-business-history"
        generated_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        source_database = $Database
        import_policy = "insert-only, preflight conflicts, transaction rollback"
        sql_sha256 = $hash
        counts = $counts
    }
    [IO.File]::WriteAllText(
        (Join-Path $OutputDirectory "manifest.json"),
        (($manifest | ConvertTo-Json -Depth 5) + "`n"),
        $utf8
    )
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "init_business_history.sh") `
        -Destination (Join-Path $OutputDirectory "init_business_history.sh") -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README.md") `
        -Destination (Join-Path $OutputDirectory "README.md") -Force
    Write-Host "Generated $sqlPath"
    Write-Host "SHA256 $hash"
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
    $Password = $null
}

