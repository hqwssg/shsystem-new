$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Name = 'report-ai-verification-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$Destination = Join-Path $Root "deploy-package/$Name"
New-Item -ItemType Directory -Path "$Destination/scripts" | Out-Null
$Sources = @{
    'tools/server-update/verify-report-ai-runtime.sh' = 'verify-report-ai-runtime.sh'
    'tools/server-update/check-report-ai-health.sh' = 'scripts/check-report-ai-health.sh'
    'tools/server-update/verify-report-ai-files.py' = 'scripts/verify-report-ai-files.py'
    'docs/report-ai-healthcheck-fix-20261108.md' = 'README.md'
}
$Utf8 = New-Object System.Text.UTF8Encoding($false)
foreach ($Source in $Sources.Keys) {
    $Content = [IO.File]::ReadAllText((Join-Path $Root $Source)).Replace("`r`n", "`n")
    [IO.File]::WriteAllText((Join-Path $Destination $Sources[$Source]), $Content, $Utf8)
}
$Commit = (& git -C $Root rev-parse HEAD)
if ($LASTEXITCODE -ne 0) { throw 'Cannot read Git revision.' }
$Dirty = [bool](& git -C $Root status --porcelain --untracked-files=no)
[IO.File]::WriteAllText("$Destination/BUILD-INFO.txt", "GitCommit=$Commit`nIncludesUncommittedWorktree=$Dirty`n", $Utf8)
$Records = Get-ChildItem -LiteralPath $Destination -Recurse -File | Sort-Object FullName | ForEach-Object {
    $Relative = $_.FullName.Substring($Destination.Length + 1).Replace('\', '/')
    "$( (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower() )  $Relative"
}
[IO.File]::WriteAllText("$Destination/SHA256SUMS", ($Records -join "`n") + "`n", $Utf8)
& tar.exe -czf "$Destination.tar.gz" -C (Split-Path $Destination -Parent) $Name
if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
$Hash = (Get-FileHash -LiteralPath "$Destination.tar.gz" -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$Destination.tar.gz.sha256", "$Hash  $Name.tar.gz`n", $Utf8)
Write-Output "PACKAGE=$Destination.tar.gz"
Write-Output "SHA256=$Hash"
