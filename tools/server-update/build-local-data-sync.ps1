param(
    [string]$DatabasePassword = $env:LOCAL_DB_PASSWORD
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Name = "local-data-sync-$Stamp"
$Destination = Join-Path $Root "deploy-package/$Name"
$DataDirectory = Join-Path $Destination 'data'
$Utf8 = New-Object System.Text.UTF8Encoding($false)

if ([string]::IsNullOrWhiteSpace($DatabasePassword)) {
    $SecurePassword = Read-Host 'Local MySQL root password' -AsSecureString
    $Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
    try {
        $DatabasePassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
    }
}

$MySqlDump = (Get-Command mysqldump.exe).Source
$MySql = (Get-Command mysql.exe).Source
$Sqlite = (Get-Command sqlite3.exe).Source
$SourceDatabase = Join-Path $Root 'goview/go-view-serve-master/sqllite/goview.db'
$SourceUpload = Join-Path $Root 'goview/upload'

New-Item -ItemType Directory -Path $Destination, $DataDirectory | Out-Null
$Dump = Join-Path $DataDirectory 'carbon_emissions.sql'
$DumpArguments = @(
    '--protocol=TCP', '--host=127.0.0.1', '--port=3306', '--user=root',
    "--password=$DatabasePassword", '--default-character-set=utf8mb4',
    '--single-transaction', '--routines', '--triggers', '--events', '--hex-blob',
    '--set-gtid-purged=OFF', '--no-tablespaces', '--add-drop-database',
    '--databases', 'carbon_emissions', "--result-file=$Dump"
)
& $MySqlDump @DumpArguments
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Dump)) {
    throw 'Local MySQL dump failed.'
}

$Sql = [IO.File]::ReadAllText($Dump)
$Sql = $Sql.Replace('utf8mb4_0900_ai_ci', 'utf8mb4_unicode_ci')
$Sql = [regex]::Replace($Sql, '(?s)/\*!8\d{4}.*?\*/;?', '')
$Sql = [regex]::Replace(
    $Sql,
    '(?m)^/\*!40000 DROP DATABASE IF EXISTS `carbon_emissions`\*/;\s*$',
    'DROP DATABASE IF EXISTS `carbon_emissions`;'
)
$Sql = [regex]::Replace(
    $Sql,
    '(?m)^CREATE DATABASE .*$',
    'CREATE DATABASE `carbon_emissions` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'
)
if ($Sql -match 'utf8mb4_0900_ai_ci|/\*!8\d{4}') {
    throw 'MySQL 8-only SQL remains in the MariaDB-compatible dump.'
}
[IO.File]::WriteAllText($Dump, $Sql.Replace("`r`n", "`n"), $Utf8)

$SnapshotDatabase = Join-Path $DataDirectory 'goview.db'
$SqliteTarget = $SnapshotDatabase.Replace('\', '/')
& $Sqlite $SourceDatabase ".backup '$SqliteTarget'"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $SnapshotDatabase)) {
    throw 'GoView SQLite backup failed.'
}
$Integrity = (& $Sqlite $SnapshotDatabase 'PRAGMA integrity_check;').Trim()
if ($LASTEXITCODE -ne 0 -or $Integrity -ne 'ok') {
    throw "GoView SQLite integrity check failed: $Integrity"
}

$SnapshotUpload = Join-Path $DataDirectory 'goview-upload'
New-Item -ItemType Directory -Path $SnapshotUpload | Out-Null
if (Test-Path -LiteralPath $SourceUpload) {
    Copy-Item -Path (Join-Path $SourceUpload '*') -Destination $SnapshotUpload -Recurse -Force
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'apply-local-data-sync.sh') -Destination $Destination

$CountSql = "SELECT CONCAT('tables=',COUNT(*)) FROM information_schema.tables WHERE table_schema='carbon_emissions'; SELECT CONCAT('configs=',COUNT(*)) FROM carbon_emissions.sys_config; SELECT CONCAT('nodes=',COUNT(*)) FROM carbon_emissions.emission_node; SELECT CONCAT('collections=',COUNT(*)) FROM carbon_emissions.emission_collection_record;"
$Counts = & $MySql '--protocol=TCP' '--host=127.0.0.1' '--port=3306' '--user=root' "--password=$DatabasePassword" '--batch' '--skip-column-names' "--execute=$CountSql"
if ($LASTEXITCODE -ne 0) { throw 'Unable to collect local database statistics.' }
$Projects = (& $Sqlite $SnapshotDatabase 'SELECT COUNT(*) FROM t_goview_project;').Trim()
$Files = (& $Sqlite $SnapshotDatabase 'SELECT COUNT(*) FROM t_sys_file;').Trim()
$Info = @(
    "BuiltAt=$(Get-Date -Format o)"
    "GitCommit=$(& git -C $Root rev-parse HEAD)"
    $Counts
    "goview_projects=$Projects"
    "goview_files=$Files"
)
[IO.File]::WriteAllText((Join-Path $Destination 'SNAPSHOT-INFO.txt'), ($Info -join "`n") + "`n", $Utf8)

Get-ChildItem $Destination -File -Recurse | Where-Object { $_.Extension -in @('.sh', '.sql') } | ForEach-Object {
    $Content = [IO.File]::ReadAllText($_.FullName).Replace("`r`n", "`n")
    [IO.File]::WriteAllText($_.FullName, $Content, $Utf8)
}
$FilesToHash = Get-ChildItem $Destination -File -Recurse | Sort-Object FullName
$Checksums = foreach ($File in $FilesToHash) {
    $Relative = $File.FullName.Substring($Destination.Length + 1).Replace('\', '/')
    "$((Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLower())  $Relative"
}
[IO.File]::WriteAllText((Join-Path $Destination 'SHA256SUMS'), ($Checksums -join "`n") + "`n", $Utf8)

$Archive = "$Destination.tar.gz"
& tar.exe -czf $Archive -C (Split-Path $Destination -Parent) $Name
if ($LASTEXITCODE -ne 0) { throw 'Local data sync archive creation failed.' }
$ArchiveHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$Archive.sha256", "$ArchiveHash  $Name.tar.gz`n", $Utf8)

Write-Output "PACKAGE=$Archive"
Write-Output "DIRECTORY=$Destination"
Write-Output "SHA256=$ArchiveHash"
