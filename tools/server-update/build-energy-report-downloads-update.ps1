param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Name = "server-energy-report-update-$Stamp"
$Destination = Join-Path $Root "deploy-package/$Name"
$Utf8 = New-Object System.Text.UTF8Encoding($false)
New-Item -ItemType Directory -Path $Destination | Out-Null

if (-not $SkipBuild) {
    Push-Location (Join-Path $Root 'ruoyi-ui')
    $PreviousNodeOptions = $env:NODE_OPTIONS
    try {
        $env:NODE_OPTIONS = '--openssl-legacy-provider --max-old-space-size=8192'
        & npm.cmd run build:prod
        if ($LASTEXITCODE -ne 0) { throw 'Main frontend build failed.' }
    } finally {
        $env:NODE_OPTIONS = $PreviousNodeOptions
        Pop-Location
    }
}

function Copy-Payload($Source, $Target) {
    $SourcePath = Join-Path $Root $Source
    $TargetPath = Join-Path $Destination $Target
    if (-not (Test-Path -LiteralPath $SourcePath)) { throw "Missing artifact: $SourcePath" }
    New-Item -ItemType Directory -Force -Path (Split-Path $TargetPath -Parent) | Out-Null
    Copy-Item -LiteralPath $SourcePath -Destination $TargetPath -Recurse -Force
}

Copy-Payload 'ruoyi-ui/dist' 'web-main/html/dist'
Copy-Payload 'tools/server-update/energy-report-downloads-apply.sh' 'apply-update.sh'

$EngineRoot = Join-Path $Root 'energy_recovery_agent'
Get-ChildItem -LiteralPath $EngineRoot -File -Recurse | Where-Object {
    $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
    $_.FullName -notmatch '[\\/]\.pytest_cache[\\/]' -and
    $_.FullName -notmatch '[\\/]outputs[\\/]' -and
    $_.Extension -ne '.pyc'
} | ForEach-Object {
    $Relative = $_.FullName.Substring($EngineRoot.Length + 1)
    $Target = Join-Path $Destination ("web-main/energy-engine/" + $Relative)
    New-Item -ItemType Directory -Force -Path (Split-Path $Target -Parent) | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $Target -Force
}

$Readme = @'
# Energy report targeted update

- Includes archived artifact downloads, Chinese Markdown filenames, and the Matplotlib CJK font fix.
- Replaces /home/ruoyi/projects/ruoyi-ui and /home/ruoyi/energy-engine only.
- Does not execute SQL or ship deployment migrations/JAR files, database initialization, uploads, or historical task data.
- Apply with: WEB_CONTAINER=ruoyi-web WEB_HOST_PORT=53221 sh apply-update.sh
'@
[IO.File]::WriteAllText((Join-Path $Destination 'README.md'), $Readme, $Utf8)

Get-ChildItem $Destination -File -Recurse | Where-Object { $_.Extension -eq '.sh' } | ForEach-Object {
    $Content = [IO.File]::ReadAllText($_.FullName).Replace("`r`n", "`n")
    [IO.File]::WriteAllText($_.FullName, $Content, $Utf8)
}

$Files = Get-ChildItem $Destination -File -Recurse | Sort-Object FullName
$Records = foreach ($File in $Files) {
    $Relative = $File.FullName.Substring($Destination.Length + 1).Replace('\', '/')
    "$( (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant() )  $Relative"
}
[IO.File]::WriteAllText((Join-Path $Destination 'SHA256SUMS'), ($Records -join "`n") + "`n", $Utf8)

$Archive = "$Destination.tar.gz"
& tar.exe -czf $Archive -C (Split-Path $Destination -Parent) $Name
if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
$Hash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$Archive.sha256", "$Hash  $Name.tar.gz`n", $Utf8)
Write-Host "PACKAGE=$Archive"
Write-Host "SHA256=$Hash"
