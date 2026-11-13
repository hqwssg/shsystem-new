param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Name = "report-subject-light-update-$Stamp"
$Destination = Join-Path $Root "deploy-package/$Name"
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

if (-not $SkipBuild) {
    $Maven = Get-Command mvnd.exe -ErrorAction SilentlyContinue
    if (-not $Maven) { $Maven = Get-Command mvn.cmd -ErrorAction Stop }
    $Npm = Get-Command npm.cmd -ErrorAction Stop
    & $Maven.Source -pl ruoyi-admin -am package -DskipTests
    if ($LASTEXITCODE -ne 0) { throw 'Main backend build failed.' }
    Push-Location (Join-Path $Root 'ruoyi-ui')
    & $Npm.Source run build:prod
    $Code = $LASTEXITCODE
    Pop-Location
    if ($Code -ne 0) { throw 'Main frontend build failed.' }
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
Copy-Payload 'tools/server-update/report-subject-lightweight-apply.sh' 'report-subject-lightweight-apply.sh'

$Readme = @"
# Report subject authorization lightweight update

This package replaces only the main ruoyi-admin.jar and the production ruoyi-ui files.
It does not execute SQL or change the database. It does not update the carbon model,
energy recovery, single-train, GoView, Redis, uploads, or renderer services.

Run on the server from the extracted directory:

```sh
cd /opt
sha256sum -c $Name.tar.gz.sha256
rm -rf /opt/$Name
tar -xzf $Name.tar.gz
cd /opt/$Name
sha256sum -c SHA256SUMS
WEB_CONTAINER=ruoyi-web sh report-subject-lightweight-apply.sh
```

Upload the `.tar.gz` and `.tar.gz.sha256` files in binary mode. Do not upload
or merge the extracted directory manually. The outer checksum must pass before
extraction; the inner checksum must pass before the update script changes any
running file.

The script checks SHA256SUMS, backs up the old JAR, frontend, and main log under
/opt/ruoyi-backups, stops only ruoyi-admin.jar, replaces files atomically, starts
the main backend, and reloads nginx. It does not stop the model process. If a
post-update health check fails, use the archive under /opt/ruoyi-backups to
restore the previous files before restarting the main backend.
"@
[IO.File]::WriteAllText((Join-Path $Destination 'SERVER-UPDATE.md'), $Readme, (New-Object System.Text.UTF8Encoding($false)))

Get-ChildItem $Destination -File -Recurse |
    Where-Object { $_.Extension -in @('.sh', '.md', '.txt') } |
    ForEach-Object {
    $Content = [IO.File]::ReadAllText($_.FullName).Replace("`r`n", "`n")
    [IO.File]::WriteAllText($_.FullName, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

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
Write-Host "DIRECTORY=$Destination"
Write-Host "SHA256=$Hash"
