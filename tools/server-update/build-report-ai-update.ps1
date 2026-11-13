param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (-not $SkipBuild) {
    $Maven = Get-Command mvnd.exe -ErrorAction SilentlyContinue
    if (-not $Maven) { $Maven = Get-Command mvn.cmd -ErrorAction Stop }
    & $Maven.Source -pl ruoyi-admin -am package
    if ($LASTEXITCODE -ne 0) { throw 'Backend build/tests failed.' }
    Push-Location (Join-Path $Root 'ruoyi-ui')
    try {
        & npm.cmd run build:prod
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
}
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Name = "server-report-ai-update-$Stamp"
$Destination = Join-Path $Root "deploy-package/$Name"
New-Item -ItemType Directory -Path $Destination | Out-Null
function Copy-ReportPayload($Source, $Target) {
    $From = Join-Path $Root $Source
    $To = Join-Path $Destination $Target
    New-Item -ItemType Directory -Force -Path (Split-Path $To -Parent) | Out-Null
    Copy-Item -LiteralPath $From -Destination $To -Recurse
}
Copy-ReportPayload 'ruoyi-admin/target/ruoyi-admin.jar' 'web-main/jar/ruoyi-admin.jar'
Copy-ReportPayload 'ruoyi-ui/dist' 'web-main/html/dist'
# Copy only source-controlled renderer files, excluding local caches and credentials.
$AgentFiles = & git -C $Root ls-files -- carbon_report_agent
if ($LASTEXITCODE -ne 0 -or -not $AgentFiles) { throw 'Cannot enumerate tracked report renderer files.' }
foreach ($Relative in $AgentFiles) {
    Copy-ReportPayload $Relative ("web-main/renderer/" + $Relative)
}
Copy-ReportPayload 'tools/server-update/deploy-report-ai.sh' 'deploy-report-ai.sh'
Copy-ReportPayload 'tools/server-update/start-web.sh' 'scripts/start-web.sh'
Copy-ReportPayload 'tools/server-update/prepare-report-ai-key.py' 'scripts/prepare-report-ai-key.py'
Copy-ReportPayload 'tools/server-update/check-report-ai-health.sh' 'scripts/check-report-ai-health.sh'
Copy-ReportPayload 'tools/server-update/verify-report-ai-files.py' 'scripts/verify-report-ai-files.py'
Copy-ReportPayload 'docs/report-ai-update-20261108.md' 'README.md'
Copy-ReportPayload 'docs/report-ai-verification-20261108.md' 'VERIFICATION.md'
$Utf8 = New-Object System.Text.UTF8Encoding($false)
Get-ChildItem -LiteralPath $Destination -File -Recurse | Where-Object { $_.Extension -in @('.sh', '.py', '.md') } | ForEach-Object {
    [IO.File]::WriteAllText($_.FullName, [IO.File]::ReadAllText($_.FullName).Replace("`r`n", "`n"), $Utf8)
}
$Files = Get-ChildItem -LiteralPath $Destination -File -Recurse | Sort-Object FullName
$Records = foreach ($File in $Files) {
    $Relative = $File.FullName.Substring($Destination.Length + 1).Replace('\', '/')
    "$( (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLower() )  $Relative"
}
[IO.File]::WriteAllText("$Destination/SHA256SUMS", ($Records -join "`n") + "`n", $Utf8)
$Commit = (& git -C $Root rev-parse HEAD)
$Dirty = [bool](& git -C $Root status --porcelain --untracked-files=no)
[IO.File]::WriteAllText("$Destination/BUILD-INFO.txt", "GitCommit=$Commit`nIncludesUncommittedWorktree=$Dirty`nBuiltAt=$(Get-Date -Format o)`n", $Utf8)
$InfoHash = (Get-FileHash "$Destination/BUILD-INFO.txt" -Algorithm SHA256).Hash.ToLower()
[IO.File]::AppendAllText("$Destination/SHA256SUMS", "$InfoHash  BUILD-INFO.txt`n", $Utf8)
$Archive = "$Destination.tar.gz"
& tar.exe -czf $Archive -C (Split-Path $Destination -Parent) $Name
if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
$Hash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$Archive.sha256", "$Hash  $Name.tar.gz`n", $Utf8)
Write-Output "PACKAGE=$Archive"
Write-Output "SHA256=$Hash"
