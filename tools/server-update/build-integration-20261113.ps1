$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$out = Join-Path $repo 'deploy-package\server-update-20261113-four-updates-r2'
if (Test-Path -LiteralPath $out) {
    throw "Refusing to overwrite existing package directory: $out"
}

$manifestPath = Join-Path $repo 'docs\integration-20261113\algorithm-source-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Missing tracked algorithm source manifest: $manifestPath" }
$algorithmManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding utf8 | ConvertFrom-Json
$package = Join-Path $repo 'deploy-package'
$payload = Join-Path $out 'payload'
$targets = @(
    'ruoyi-ui', 'carbon-model', 'carbon-emission-model',
    'energy-engine', 'single-train-engine', 'single-train-algorithm', 'optional-data-init'
)
New-Item -ItemType Directory -Path $payload -Force | Out-Null
foreach ($target in $targets) {
    New-Item -ItemType Directory -Path (Join-Path $payload $target) -Force | Out-Null
}

function Copy-TreeContents([string]$source, [string]$destination) {
    if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "Missing build output: $source" }
    $items = @(Get-ChildItem -LiteralPath $source -Force)
    if ($items.Count -eq 0) { throw "Build output is empty: $source" }
    foreach ($item in $items) {
        Copy-Item -LiteralPath $item.FullName -Destination $destination -Recurse -Force
    }
}

Copy-TreeContents (Join-Path $repo 'ruoyi-ui\dist') (Join-Path $payload 'ruoyi-ui')
Copy-TreeContents (Join-Path $repo 'tpfhs-9\frontend\dist') (Join-Path $payload 'carbon-model')
$jar = Join-Path $repo 'tpfhs-9\backend\target\carbon-emission-model-1.0.0.jar'
if (-not (Test-Path -LiteralPath $jar -PathType Leaf)) { throw "Missing built backend jar: $jar" }
Copy-Item -LiteralPath $jar -Destination (Join-Path $payload 'carbon-emission-model\carbon-emission-model.jar')

$deployFiles = [System.Collections.Generic.List[object]]::new()
foreach ($entry in $algorithmManifest.files) {
    $source = Join-Path $repo ($entry.path.Replace('/', '\'))
    if ($entry.path.StartsWith('energy_recovery_agent/')) {
        $relative = $entry.path.Substring('energy_recovery_agent/'.Length)
        $target = Join-Path $payload 'energy-engine'
    } elseif ($entry.path.StartsWith('single_train_recovery_agent/')) {
        $relative = $entry.path.Substring('single_train_recovery_agent/'.Length)
        $target = Join-Path $payload 'single-train-engine'
    } elseif ($entry.path.StartsWith('new_function/single_train_energy_optimization-f6d1797/')) {
        $relative = $entry.path.Substring('new_function/single_train_energy_optimization-f6d1797/'.Length)
        $target = Join-Path $payload 'single-train-algorithm'
    } else { continue }
    if ($relative -match '(^|/)tests?(/|$)|\.pyc$|__pycache__') { continue }
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Manifest source missing: $source" }
    $destination = Join-Path $target ($relative.Replace('/', '\'))
    New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination
    $deployFiles.Add([pscustomobject]@{ source = $entry.path; target = $destination.Substring($out.Length + 1).Replace('\', '/'); sha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() })
}
if ($deployFiles.Count -lt 35) { throw "Unexpectedly small algorithm payload: $($deployFiles.Count) files" }

Copy-TreeContents (Join-Path $repo 'tools\algorithm-demo-20261113') (Join-Path $payload 'optional-data-init')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'initialize-algorithm-demo-no-backup-20261113.sh') -Destination $out
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'deploy-integration-20261113.sh') -Destination $out
Copy-Item -LiteralPath (Join-Path $repo 'docs\server-update-20261113.md') -Destination $out
Copy-Item -LiteralPath (Join-Path $repo 'docs\integration-20261113\source-audit.json') -Destination $out
Copy-Item -LiteralPath (Join-Path $repo 'docs\integration-20261113\README.md') -Destination (Join-Path $out 'integration-record.md')
[System.IO.File]::WriteAllText((Join-Path $out 'payload-manifest.json'), ($deployFiles | ConvertTo-Json -Depth 4), [System.Text.UTF8Encoding]::new($false))
$sourceCommit = & git -C $repo rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'Cannot identify source commit' }
$buildInfo = [ordered]@{ sourceCommit = $sourceCommit; builtAt = (Get-Date).ToString('o'); packageKind = 'targeted-application-update'; automaticDatabaseInitialization = $false; serverBackup = $false }
[System.IO.File]::WriteAllText((Join-Path $out 'build-info.json'), ($buildInfo | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))

$sumLines = Get-ChildItem -LiteralPath $out -File -Recurse | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($out.Length + 1).Replace('\', '/')
    $fileHash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$fileHash  $relative"
}
[System.IO.File]::WriteAllLines((Join-Path $out 'SHA256SUMS'), [string[]]$sumLines, [System.Text.UTF8Encoding]::new($false))
$archive = "$out.tar.gz"
if (Test-Path -LiteralPath $archive) { throw "Refusing to overwrite existing archive: $archive" }
tar -czf $archive -C (Split-Path $out -Parent) (Split-Path $out -Leaf)
if ($LASTEXITCODE -ne 0) { throw 'tar failed' }
$archiveHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$archiveHash  $(Split-Path $archive -Leaf)" | Set-Content -LiteralPath "$archive.sha256" -Encoding ascii
Get-Item -LiteralPath $archive, "$archive.sha256" | Select-Object FullName,Length
