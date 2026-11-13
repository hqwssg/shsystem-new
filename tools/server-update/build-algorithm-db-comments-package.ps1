$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$Name = 'algorithm-db-comments-20261111-r5'
$PackageRoot = Join-Path $Root 'deploy-package'
$Destination = Join-Path $PackageRoot $Name
$Archive = Join-Path $PackageRoot "$Name.tar.gz"
$ArchiveSha = "$Archive.sha256"

if (Test-Path -LiteralPath $Destination) { throw "Package directory already exists: $Destination" }
if (Test-Path -LiteralPath $Archive) { throw "Archive already exists: $Archive" }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$Source = Join-Path $Root 'tools/algorithm-db-comments'
if (-not (Test-Path -LiteralPath $Source)) { throw "Missing source directory: $Source" }
Get-ChildItem -LiteralPath $Source -File | Where-Object { $_.Name -notin @('__pycache__') -and $_.Extension -ne '.pyc' } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Destination $_.Name)
}

$Manifest = @(
    'algorithm-db-comments-20261111-r5',
    'scope: resume an existing legacy COMMENT plan after MySQL expands default charset and CHECK literal metadata',
    'compatibility: legacy hash strips only exact default column charset expansion, retains collation, rejects schema drift',
    'database backup: not included',
    'database password: not included',
    'application binaries, frontend assets, business data: not included',
    'service restart: not required'
)
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $Destination 'MANIFEST.txt'), ($Manifest -join "`n") + "`n", $Utf8NoBom)

$Records = foreach ($File in (Get-ChildItem -LiteralPath $Destination -File | Sort-Object Name)) {
    "$( (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant() )  $($File.Name)"
}
[IO.File]::WriteAllText((Join-Path $Destination 'SHA256SUMS'), ($Records -join "`n") + "`n", $Utf8NoBom)

& tar.exe -czf $Archive -C $PackageRoot $Name
if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
$ArchiveHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText($ArchiveSha, "$ArchiveHash  $Name.tar.gz`n", $Utf8NoBom)
Write-Output "PACKAGE=$Archive"
Write-Output "SHA256=$ArchiveHash"
