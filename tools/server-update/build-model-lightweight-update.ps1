param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Name = "server-model-light-update-$Stamp"
$Destination = Join-Path $Root "deploy-package/$Name"
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

if (-not $SkipBuild) {
    $Maven = Get-Command mvnd.exe -ErrorAction SilentlyContinue
    if (-not $Maven) { $Maven = Get-Command mvn.cmd -ErrorAction Stop }
    & $Maven.Source -f (Join-Path $Root 'tpfhs-9/backend/pom.xml') package
    if ($LASTEXITCODE -ne 0) { throw 'Carbon model backend build failed.' }
    $Npm = Get-Command npm.cmd -ErrorAction Stop
    Push-Location (Join-Path $Root 'tpfhs-9/frontend')
    try { & $Npm.Source run build:server } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw 'Carbon model frontend build failed.' }
}

function Copy-Payload($Source, $Target) {
    $SourcePath = Join-Path $Root $Source
    $TargetPath = Join-Path $Destination $Target
    if (-not (Test-Path -LiteralPath $SourcePath)) { throw "Missing artifact: $SourcePath" }
    New-Item -ItemType Directory -Force -Path (Split-Path $TargetPath -Parent) | Out-Null
    Copy-Item -LiteralPath $SourcePath -Destination $TargetPath -Recurse -Force
}

Copy-Payload 'tpfhs-9/backend/target/carbon-emission-model-1.0.0.jar' 'web-main/jar/carbon-emission-model.jar'
Copy-Payload 'tpfhs-9/frontend/dist' 'web-main/html/carbon-model'
Copy-Payload 'tools/server-update/model-lightweight-apply.sh' 'model-lightweight-apply.sh'

$Utf8 = New-Object System.Text.UTF8Encoding($false)
$Readme = @(
    "Carbon model lightweight update package: $Name",
    '',
    'Scope: replace only carbon-emission-model.jar and the carbon-model frontend.',
    'No SQL is executed. The main JAR, main frontend, GoView, Redis, uploads, and database data are untouched.',
    '',
    'Server steps:',
    "1. Upload this directory to /opt/$Name/.",
    "2. cd /opt/$Name",
    '3. sha256sum -c SHA256SUMS',
    '4. WEB_CONTAINER=ruoyi-web bash model-lightweight-apply.sh',
    '',
    'The script backs up the model JAR, model frontend, and model log under /opt/ruoyi-backups/model-light-TIMESTAMP/.',
    ''
) -join "`n"
[IO.File]::WriteAllText((Join-Path $Destination 'SERVER-UPDATE.md'), $Readme, $Utf8)

$Files = Get-ChildItem -LiteralPath $Destination -File -Recurse | Sort-Object FullName
$Records = foreach ($File in $Files) {
    $Relative = $File.FullName.Substring($Destination.Length + 1).Replace('\', '/')
    "$( (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLower() )  $Relative"
}
[IO.File]::WriteAllText((Join-Path $Destination 'SHA256SUMS'), ($Records -join "`n") + "`n", $Utf8)

$Archive = "$Destination.tar.gz"
& tar.exe -czf $Archive -C (Split-Path $Destination -Parent) $Name
if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
$Hash = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$Archive.sha256", "$Hash  $Name.tar.gz`n", $Utf8)
Write-Host "PACKAGE=$Archive"
Write-Host "DIRECTORY=$Destination"
Write-Host "SHA256=$Hash"
