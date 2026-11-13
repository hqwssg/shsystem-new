param(
    [string]$Name = "monthly-analysis-update-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Destination = Join-Path $Root "deploy-package/$Name"
$Archive = Join-Path $Root "deploy-package/$Name.tar.gz"
$Utf8 = New-Object System.Text.UTF8Encoding($false)

if (Test-Path -LiteralPath $Destination) { throw "Package directory already exists: $Destination" }
New-Item -ItemType Directory -Path $Destination | Out-Null

function Copy-Required($Source, $Target) {
    $From = Join-Path $Root $Source
    if (-not (Test-Path -LiteralPath $From)) { throw "Required build output is missing: $From" }
    $To = Join-Path $Destination $Target
    $Parent = Split-Path -Parent $To
    New-Item -ItemType Directory -Force -Path $Parent | Out-Null
    Copy-Item -LiteralPath $From -Destination $To -Recurse -Force
}

Copy-Required 'ruoyi-admin/target/ruoyi-admin.jar' 'web-main/jar/ruoyi-admin.jar'
Copy-Required 'tpfhs-9/backend/target/carbon-emission-model-1.0.0.jar' 'web-main/jar/carbon-emission-model.jar'
Copy-Required 'ruoyi-ui/dist' 'web-main/html/dist'
Copy-Required 'goview/go-view-master-fetch/dist' 'web-screen/html/dist'
Copy-Required 'tools/server-update/monthly-analysis-update-apply.sh' 'apply-update.sh'
Copy-Required 'tools/server-update/monthly-analysis-update-README.md' 'README.md'
$GeneratedCompressionPath = Join-Path $Destination 'web-screen/html/dist/D:'
if (Test-Path -LiteralPath $GeneratedCompressionPath) {
    Remove-Item -LiteralPath $GeneratedCompressionPath -Recurse -Force
}

$RendererSource = Join-Path $Root 'carbon_report_agent'
$RendererDestination = Join-Path $Destination 'web-main/renderer/carbon_report_agent'
Get-ChildItem -LiteralPath $RendererSource -File -Recurse | Where-Object {
    $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -ne '.pyc'
} | ForEach-Object {
    $Relative = $_.FullName.Substring($RendererSource.Length + 1)
    $Target = Join-Path $RendererDestination $Relative
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $Target -Force
}
Get-ChildItem -LiteralPath $Destination -Directory -Recurse |
    Where-Object Name -eq '__pycache__' |
    Sort-Object FullName -Descending |
    Remove-Item -Force -Recurse
Get-ChildItem -LiteralPath $Destination -File -Recurse |
    Where-Object Extension -eq '.pyc' |
    Remove-Item -Force

$ApplyScript = Join-Path $Destination 'apply-update.sh'
$Content = [IO.File]::ReadAllText($ApplyScript).Replace('PACKAGE_NAME_PLACEHOLDER', $Name)
[IO.File]::WriteAllText($ApplyScript, $Content, $Utf8)
$Readme = Join-Path $Destination 'README.md'
$Content = [IO.File]::ReadAllText($Readme).Replace('PACKAGE_NAME_PLACEHOLDER', $Name)
[IO.File]::WriteAllText($Readme, $Content, $Utf8)

$ChecksumLines = Get-ChildItem -LiteralPath $Destination -File -Recurse |
    Where-Object Name -ne 'SHA256SUMS' |
    Sort-Object FullName |
    ForEach-Object {
        $Relative = $_.FullName.Substring($Destination.Length + 1).Replace('\', '/')
        $Hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$Hash  $Relative"
    }
[IO.File]::WriteAllText((Join-Path $Destination 'SHA256SUMS'), ([string]::Join("`n", $ChecksumLines) + "`n"), $Utf8)

$Tar = Get-Command tar.exe -ErrorAction Stop
& $Tar.Source -czf $Archive -C (Split-Path -Parent $Destination) $Name
if ($LASTEXITCODE -ne 0) { throw 'Creating the update archive failed.' }
$ArchiveHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$Archive.sha256", "$ArchiveHash  $Name.tar.gz`n", $Utf8)

Write-Host "Package: $Destination"
Write-Host "Archive: $Archive"
Write-Host "SHA256:  $ArchiveHash"
