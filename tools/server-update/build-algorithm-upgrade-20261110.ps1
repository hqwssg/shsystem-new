$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Name = 'server-update-20261110-algorithm-r2'
$PackageRoot = Join-Path $Root "deploy-package/$Name"
$Archive = Join-Path $Root "deploy-package/$Name.tar.gz"

if (Test-Path -LiteralPath $PackageRoot) { Remove-Item -LiteralPath $PackageRoot -Recurse -Force }
if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
if (Test-Path -LiteralPath "$Archive.sha256") { Remove-Item -LiteralPath "$Archive.sha256" -Force }
New-Item -ItemType Directory -Path $PackageRoot | Out-Null

function Copy-Tree([string]$Source, [string]$Destination) {
    New-Item -ItemType Directory -Path $Destination | Out-Null
    & robocopy (Join-Path $Root $Source) $Destination /E /XD outputs __pycache__ .pytest_cache /XF *.pyc *.pyo | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "Could not copy $Source (robocopy exit $LASTEXITCODE)." }
}

Copy-Tree 'energy_recovery_agent' (Join-Path $PackageRoot 'energy-engine')
Copy-Tree 'single_train_recovery_agent' (Join-Path $PackageRoot 'single-train-engine')
Copy-Tree 'new_function/single_train_energy_optimization-f6d1797' (Join-Path $PackageRoot 'single-train-algorithm')
Copy-Tree 'ruoyi-ui/dist' (Join-Path $PackageRoot 'ui-dist')

Copy-Item (Join-Path $Root 'tools/server-update/deploy-algorithm-upgrade-20261110.sh') $PackageRoot
$DeployScript = Join-Path $PackageRoot 'deploy-algorithm-upgrade-20261110.sh'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($DeployScript, [IO.File]::ReadAllText($DeployScript).Replace("`r`n", "`n"), $Utf8NoBom)

$Readme = @'
# 2026-11-09 algorithm integration update

This is an incremental runtime update for the existing `ruoyi-web` container. It contains the heavy-empty coordination algorithm, single-train adapter, single-train regenerative algorithm, and the rebuilt main UI. Algorithm source includes SQL schema/reference files, but this deployment script does not execute them. The package does not contain database data files, uploaded files, task results, backups, private configuration, JARs, or LibreOffice.

Run on the Docker host after copying this directory and archive to `/opt`:

```sh
cd /opt/server-update-20261110-algorithm-r2
sha256sum -c SHA256SUMS
sh deploy-algorithm-upgrade-20261110.sh --check
sh deploy-algorithm-upgrade-20261110.sh
```

The script stages files inside `ruoyi-web`, validates required paths and Python syntax, then overlays delivered files in `/home/ruoyi/energy-engine`, `/home/ruoyi/single_train_recovery_agent`, `/home/ruoyi/single_train_algorithm`, and `/home/ruoyi/projects/ruoyi-ui`. It creates no server backups and performs no SQL or data reset. Existing runtime outputs and uploaded files are preserved. It invokes the existing `/usr/local/bin/start-ruoyi-web.sh` service launcher, then checks the web page and listening ports 80, 8081, 8082, 8085, 8086, and 8090. These checks do not replace functional acceptance. `ruoyi-db` and `ruoyi-screen` are not changed.

Revision r2 fixes service startup after a Bash-only container restart and corrects the single-train runtime directory names. Do not execute the original package again.

The package is not a standalone installation. The target server must already have the existing MySQL schema, `ruoyi-web` image/runtime, `/opt/carbon-report-venv`, and its normal environment variables.
'@
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $PackageRoot 'README.md'), $Readme, $Utf8NoBom)

$Records = foreach ($File in (Get-ChildItem -LiteralPath $PackageRoot -Recurse -File | Sort-Object FullName)) {
    $Relative = $File.FullName.Substring($PackageRoot.Length + 1).Replace('\', '/')
    "$( (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant() )  $Relative"
}
[IO.File]::WriteAllText((Join-Path $PackageRoot 'SHA256SUMS'), ($Records -join "`n") + "`n", $Utf8NoBom)

& tar.exe -czf $Archive -C (Split-Path $PackageRoot -Parent) $Name
if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
$ArchiveHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$Archive.sha256", "$ArchiveHash  $Name.tar.gz`n", $Utf8NoBom)
Write-Output "PACKAGE=$Archive"
Write-Output "SHA256=$ArchiveHash"
