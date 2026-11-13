param(
    [Parameter(Mandatory = $true)]
    [Alias("DatabaseUrl")]
    [string]$DeploymentDatabaseUrl,
    [string]$AdminUrl = "",
    [string]$HealthcheckDatabaseUrl = "",
    [switch]$SkipDependencyInstall,
    [switch]$SkipBootstrap,
    [switch]$SkipSecurity,
    [switch]$AllowInsecure
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not $SkipDependencyInstall) {
        python -m pip install -r requirements-database.txt
        if ($LASTEXITCODE -ne 0) { throw "Database Python dependency installation failed." }
    }
    if (-not $SkipBootstrap) {
        if ([string]::IsNullOrWhiteSpace($AdminUrl)) {
            throw "-AdminUrl is required unless -SkipBootstrap is specified."
        }
        python -m database.cli bootstrap --admin-url $AdminUrl
        if ($LASTEXITCODE -ne 0) { throw "Failed to create the carbon_emissions database." }
    }
    python -m database.cli --database-url $DeploymentDatabaseUrl migrate
    if ($LASTEXITCODE -ne 0) { throw "Database migration failed." }
    if (-not $SkipSecurity) {
        python -m database.cli --database-url $DeploymentDatabaseUrl apply-security
        if ($LASTEXITCODE -ne 0) { throw "Database security role setup failed." }
    }
    $healthUrl = if ([string]::IsNullOrWhiteSpace($HealthcheckDatabaseUrl)) {
        $DeploymentDatabaseUrl
    } else {
        $HealthcheckDatabaseUrl
    }
    $healthArgs = @("tools/database_healthcheck.py", "--database-url", $healthUrl)
    if (-not $AllowInsecure) {
        $healthArgs += "--require-tls"
    }
    python @healthArgs
    if ($LASTEXITCODE -ne 0) { throw "Database health check failed." }
}
finally {
    Pop-Location
}
