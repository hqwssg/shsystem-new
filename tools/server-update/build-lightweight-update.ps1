param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Name = "server-light-update-$Stamp"
$Destination = Join-Path $Root "deploy-package/$Name"
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

if (-not $SkipBuild) {
    $Maven = Get-Command mvnd.exe -ErrorAction SilentlyContinue
    if (-not $Maven) { $Maven = Get-Command mvn.cmd -ErrorAction Stop }
    $Npm = Get-Command npm.cmd -ErrorAction Stop
    & $Maven.Source -pl ruoyi-admin -am install -DskipTests
    if ($LASTEXITCODE -ne 0) { throw 'Backend build failed.' }
    Push-Location (Join-Path $Root 'ruoyi-ui')
    & $Npm.Source run build:prod
    $Code = $LASTEXITCODE
    Pop-Location
    if ($Code -ne 0) { throw 'Frontend build failed.' }
}

function Copy-Payload($Source, $Target) {
    $SourcePath = Join-Path $Root $Source
    $TargetPath = Join-Path $Destination $Target
    if (-not (Test-Path -LiteralPath $SourcePath)) { throw "Missing artifact: $SourcePath" }
    New-Item -ItemType Directory -Force -Path (Split-Path $TargetPath -Parent) | Out-Null
    Copy-Item -LiteralPath $SourcePath -Destination $TargetPath -Recurse -Force
}

Copy-Payload 'ruoyi-admin/target/ruoyi-admin.jar' 'web-main/jar/ruoyi-admin.jar'
Copy-Payload 'ruoyi-ui/dist' 'web-main/html/dist'
Copy-Payload 'energy_recovery_agent' 'web-main/energy-engine'
Copy-Payload 'carbon_report_agent' 'web-main/renderer/carbon_report_agent'
Copy-Payload 'single_train_recovery_agent' 'web-main/single-train-engine'
Copy-Payload 'new_function/single_train_energy_optimization-f6d1797' 'web-main/single-train-algorithm'
Copy-Payload 'docker/web-main/requirements-cli.txt' 'web-main/requirements-cli.txt'
Copy-Payload 'sql/carbon-energy/V11__storage_planning.sql' 'mysql/migrations/48e_storage_planning.sql'
Copy-Payload 'sql/carbon-report/V15__report_file_content.sql' 'mysql/migrations/44_report_file_content.sql'
Copy-Payload 'sql/carbon-report/V16__default_report_images.sql' 'mysql/migrations/44a_default_report_images.sql'
Copy-Payload 'sql/carbon-report/V17__report_subject_mapping_repair.sql' 'mysql/migrations/44b_report_subject_mapping_repair.sql'
Copy-Payload 'tpfhs-9/backend/src/main/resources/schema-update-20261013-meter-model-seed.sql' 'mysql/migrations/61_meter_model_seed.sql'
Copy-Payload 'sql/carbon-single-train/V1__tables.sql' 'mysql/migrations/63_single_train_tables.sql'
Copy-Payload 'sql/carbon-single-train/V2__menus.sql' 'mysql/migrations/64_single_train_menus.sql'
Copy-Payload 'tools/server-update/lightweight-apply.sh' 'lightweight-apply.sh'
Copy-Payload 'tools/server-update/start-web.sh' 'scripts/start-web.sh'

# The light package must still repair the known missing PyYAML dependency on
# an existing server. Only this small wheel is included; the other dependencies
# are already installed by the full deployment package.
$Python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $Python) { $Python = Get-Command python -ErrorAction Stop }
$Wheelhouse = Join-Path $Destination 'web-main/wheels'
New-Item -ItemType Directory -Force -Path $Wheelhouse | Out-Null
foreach ($PythonVersion in @('310', '311', '312')) {
    & $Python.Source -m pip download --disable-pip-version-check --only-binary=:all: `
      --platform manylinux2014_x86_64 --implementation cp --python-version $PythonVersion `
      --abi "cp$PythonVersion" --dest $Wheelhouse 'PyYAML>=6.0,<7'
    if ($LASTEXITCODE -ne 0) { throw "PyYAML wheel download failed for CPython $PythonVersion." }
}

Get-ChildItem $Destination -File -Recurse | Where-Object { $_.Extension -in @('.sh', '.sql') } | ForEach-Object {
    $Content = [IO.File]::ReadAllText($_.FullName).Replace("`r`n", "`n")
    [IO.File]::WriteAllText($_.FullName, $Content, (New-Object System.Text.UTF8Encoding($false)))
}
# Never ship local Python bytecode or cache directories in an update package.
Get-ChildItem -LiteralPath $Destination -File -Recurse |
    Where-Object { $_.Extension -eq '.pyc' -or $_.FullName -match '[\\/]__pycache__[\\/]' } |
    Remove-Item -Force
Get-ChildItem -LiteralPath $Destination -Directory -Recurse |
    Where-Object { $_.Name -eq '__pycache__' } |
    Sort-Object FullName -Descending |
    Remove-Item -Force -Recurse

$Files = Get-ChildItem $Destination -File -Recurse | Sort-Object FullName
$Records = foreach ($File in $Files) {
    $Relative = $File.FullName.Substring($Destination.Length + 1).Replace('\', '/')
    "$( (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLower() )  $Relative"
}
[IO.File]::WriteAllText((Join-Path $Destination 'SHA256SUMS'), ($Records -join "`n") + "`n", (New-Object System.Text.UTF8Encoding($false)))
$Archive = "$Destination.tar.gz"
& tar.exe -czf $Archive -C (Split-Path $Destination -Parent) $Name
if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
$Hash = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$Archive.sha256", "$Hash  $Name.tar.gz`n", (New-Object System.Text.UTF8Encoding($false)))
Write-Host "PACKAGE=$Archive"
Write-Host "SHA256=$Hash"
