param(
    [string]$Database = 'carbon_emissions',
    [string]$HostName = '127.0.0.1',
    [int]$Port = 3306,
    [string]$User = 'root',
    [string]$MysqlPath,
    [string]$SqlitePath,
    [string]$SnapshotPath,
    [string]$CompareSnapshot
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

if (-not $MysqlPath) {
    $mysqlCommand = Get-Command mysql.exe -ErrorAction SilentlyContinue
    if ($mysqlCommand) {
        $MysqlPath = $mysqlCommand.Source
    } else {
        $MysqlPath = 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe'
    }
}
if (-not (Test-Path -LiteralPath $MysqlPath -PathType Leaf)) {
    throw "mysql.exe not found: $MysqlPath"
}

function Invoke-Scalar([string]$Sql) {
    $output = & $MysqlPath --default-character-set=utf8mb4 --batch --skip-column-names `
        -h $HostName -P $Port -u $User -D $Database -e $Sql 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ($output -join [Environment]::NewLine)
    }
    return [string]($output | Select-Object -Last 1)
}

function Invoke-Rows([string]$Sql) {
    $output = & $MysqlPath --default-character-set=utf8mb4 --batch --skip-column-names `
        -h $HostName -P $Port -u $User -D $Database -e $Sql 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ($output -join [Environment]::NewLine)
    }
    return @($output)
}

function Assert-Equal([string]$Name, [long]$Actual, [long]$Expected) {
    if ($Actual -ne $Expected) {
        throw "$Name failed: expected $Expected, actual $Actual"
    }
    Write-Output ("PASS {0}: {1}" -f $Name, $Actual)
}

function Assert-Minimum([string]$Name, [long]$Actual, [long]$Minimum) {
    if ($Actual -lt $Minimum) {
        throw "$Name failed: expected at least $Minimum, actual $Actual"
    }
    Write-Output ("PASS {0}: {1}" -f $Name, $Actual)
}

Assert-Minimum 'database tables' ([long](Invoke-Scalar "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE();")) 120
Assert-Minimum 'active users' ([long](Invoke-Scalar "SELECT COUNT(*) FROM sys_user WHERE del_flag='0';")) 1
Assert-Minimum 'active roles' ([long](Invoke-Scalar "SELECT COUNT(*) FROM sys_role WHERE del_flag='0';")) 1
Assert-Minimum 'active menus' ([long](Invoke-Scalar "SELECT COUNT(*) FROM sys_menu WHERE status='0';")) 20
Assert-Equal 'duplicate system configuration keys' ([long](Invoke-Scalar "SELECT COUNT(*) FROM (SELECT config_key FROM sys_config GROUP BY config_key HAVING COUNT(*)>1) duplicated;")) 0
Assert-Equal 'system configuration unique index' ([long](Invoke-Scalar "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='sys_config' AND index_name='uk_sys_config_config_key' AND non_unique=0;")) 1
Assert-Equal 'manual review columns' ([long](Invoke-Scalar "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='emission_collection_record' AND column_name IN ('workflow_status','submitter_id','submitted_at','reviewer_id','reviewed_at','review_comment');")) 6
Assert-Equal 'manual review audit table' ([long](Invoke-Scalar "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='emission_collection_record_audit';")) 1
Assert-Equal 'manual auto-approval parameter' ([long](Invoke-Scalar "SELECT COUNT(*) FROM sys_config WHERE config_key='carbon.collection.manual.auto-approve';")) 1
Assert-Minimum 'report tables' ([long](Invoke-Scalar "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name LIKE 'report_%';")) 13
Assert-Minimum 'energy tables' ([long](Invoke-Scalar "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name LIKE 'energy_%';")) 36
Assert-Equal 'energy online edit table' ([long](Invoke-Scalar "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='energy_version_edit_sheet';")) 1
Assert-Equal 'statistics demo records' ([long](Invoke-Scalar "SELECT COUNT(*) FROM emission_collection_record WHERE external_record_id LIKE 'STAT-DEMO-%';")) 72
Assert-Equal 'statistics demo unique keys' ([long](Invoke-Scalar "SELECT COUNT(DISTINCT external_record_id) FROM emission_collection_record WHERE external_record_id LIKE 'STAT-DEMO-%';")) 72
Assert-Equal 'energy source files' ([long](Invoke-Scalar "SELECT COUNT(*) FROM energy_dataset_file f JOIN energy_project_version v ON v.version_id=f.version_id JOIN energy_project p ON p.project_id=v.project_id WHERE p.project_code='shuohuang_demo' AND v.version_code='v1';")) 28
Assert-Equal 'energy stations' ([long](Invoke-Scalar "SELECT COUNT(*) FROM energy_station s JOIN energy_project_version v ON v.version_id=s.version_id JOIN energy_project p ON p.project_id=v.project_id WHERE p.project_code='shuohuang_demo' AND v.version_code='v1';")) 33
Assert-Equal 'energy route segments' ([long](Invoke-Scalar "SELECT COUNT(*) FROM energy_route_segment s JOIN energy_project_version v ON v.version_id=s.version_id JOIN energy_project p ON p.project_id=v.project_id WHERE p.project_code='shuohuang_demo' AND v.version_code='v1';")) 1390
Assert-Equal 'energy example run types' ([long](Invoke-Scalar "SELECT COUNT(DISTINCT run_type) FROM energy_run WHERE run_type IN ('timetable_audit','timetable_optimization','dispatch','rolling_rescheduling','joint_parameter_robustness');")) 5

if (-not $SqlitePath) {
    $SqlitePath = Join-Path $root 'goview/go-view-serve-master/sqllite/goview.db'
}
if (-not (Test-Path -LiteralPath $SqlitePath -PathType Leaf)) {
    throw "GoView database not found: $SqlitePath"
}
$sqliteCommand = Get-Command sqlite3.exe -ErrorAction SilentlyContinue
$goviewTableCounts = [ordered]@{}
if ($sqliteCommand) {
    $integrity = & $sqliteCommand.Source $SqlitePath 'PRAGMA integrity_check;'
    if ($LASTEXITCODE -ne 0 -or ($integrity | Select-Object -Last 1) -ne 'ok') {
        throw 'GoView SQLite integrity check failed.'
    }
    $projects = [long](& $sqliteCommand.Source $SqlitePath 'SELECT COUNT(*) FROM t_goview_project WHERE COALESCE(is_delete,0)=0;')
    Assert-Minimum 'GoView projects' $projects 1
    foreach ($table in @('t_sys_user','t_goview_project','t_goview_project_data','t_sys_file')) {
        $goviewTableCounts[$table] = [long](& $sqliteCommand.Source $SqlitePath "SELECT COUNT(*) FROM $table;")
    }
} else {
    Write-Warning 'sqlite3.exe is unavailable; skipped GoView content and integrity checks.'
}

$tableCounts = [ordered]@{}
foreach ($table in (Invoke-Rows 'SHOW TABLES;')) {
    if ($table -notmatch '^[A-Za-z0-9_]+$') {
        throw "Unexpected table name: $table"
    }
    $tableCounts[$table] = [long](Invoke-Scalar "SELECT COUNT(*) FROM ``$table``;")
}
$snapshot = [ordered]@{
    database = $Database
    tableCounts = $tableCounts
    goviewTableCounts = $goviewTableCounts
}

if ($CompareSnapshot) {
    $baseline = Get-Content -Raw -Encoding utf8 -LiteralPath $CompareSnapshot | ConvertFrom-Json
    foreach ($property in $baseline.tableCounts.PSObject.Properties) {
        if (-not $tableCounts.Contains($property.Name)) {
            throw "Table disappeared after restart: $($property.Name)"
        }
        if ([long]$tableCounts[$property.Name] -lt [long]$property.Value) {
            throw "Rows decreased after restart: $($property.Name) ($($property.Value) -> $($tableCounts[$property.Name]))"
        }
    }
    foreach ($property in $baseline.goviewTableCounts.PSObject.Properties) {
        if (-not $goviewTableCounts.Contains($property.Name) -or
            [long]$goviewTableCounts[$property.Name] -lt [long]$property.Value) {
            throw "GoView rows decreased after restart: $($property.Name)"
        }
    }
    Write-Output 'PASS: no table or row count decreased after restart.'
}

if ($SnapshotPath) {
    $snapshotDirectory = Split-Path -Parent $SnapshotPath
    if ($snapshotDirectory) {
        New-Item -ItemType Directory -Path $snapshotDirectory -Force | Out-Null
    }
    $snapshot | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $SnapshotPath -Encoding utf8
    Write-Output "Snapshot: $SnapshotPath"
}

Write-Output 'PASS: persistent data and required schemas are complete.'
