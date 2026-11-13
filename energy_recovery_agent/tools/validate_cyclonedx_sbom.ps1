param(
    [string]$SbomPath = "outputs/security_audit_20260911/composition/sbom.cyclonedx.json",
    [string]$OutputPath = "outputs/security_audit_20260911/composition/sbom_schema_validation.json"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedSbom = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $SbomPath))
$resolvedOutput = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $OutputPath))
$policy = Get-Content -LiteralPath (Join-Path $projectRoot "security/audit_policy.json") -Raw | ConvertFrom-Json
$schemaUrl = $policy.official_sources.cyclonedx_schema
$temporaryDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("energy_retry_cyclonedx_" + [guid]::NewGuid().ToString("N"))
$schemaPath = Join-Path $temporaryDirectory "bom-1.6.schema.json"

New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
try {
    Invoke-WebRequest -Uri $schemaUrl -OutFile $schemaPath -UseBasicParsing
    $sbomText = Get-Content -LiteralPath $resolvedSbom -Raw
    $accepted = Test-Json -Json $sbomText -SchemaFile $schemaPath
    $result = [ordered]@{
        schema_version = "1.0"
        validated_at_utc = [DateTime]::UtcNow.ToString("o")
        accepted = [bool]$accepted
        sbom_path = $resolvedSbom
        sbom_sha256 = (Get-FileHash -LiteralPath $resolvedSbom -Algorithm SHA256).Hash.ToLowerInvariant()
        schema_url = $schemaUrl
        schema_sha256 = (Get-FileHash -LiteralPath $schemaPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $outputDirectory = Split-Path -Parent $resolvedOutput
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $resolvedOutput -Encoding utf8NoBOM
    $result | ConvertTo-Json -Depth 5
    if (-not $accepted) {
        exit 1
    }
}
finally {
    Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
}

