$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$llmKeyFile = Join-Path $root '.runtime/carbon-report-llm-encryption.key'
if (-not $env:CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY) {
    if (-not (Test-Path -LiteralPath $llmKeyFile)) {
        New-Item -ItemType Directory -Path (Split-Path $llmKeyFile -Parent) -Force | Out-Null
        $randomBytes = New-Object byte[] 32
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($randomBytes) } finally { $rng.Dispose() }
        [System.IO.File]::WriteAllText($llmKeyFile, [Convert]::ToBase64String($randomBytes))
    }
    $env:CARBON_REPORT_LLM_CONFIG_ENCRYPTION_KEY = (Get-Content -LiteralPath $llmKeyFile -Raw).Trim()
}
$logs = Join-Path $root ('.runtime/logs/start-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$java = (Get-Command java.exe).Source
$node = (Get-Command node.exe).Source
$redisCommand = Get-Command redis-server.exe -ErrorAction SilentlyContinue
$python = if ($env:PYTHON_PATH) {
    (Resolve-Path -LiteralPath $env:PYTHON_PATH).Path
} else {
    (Get-Command python.exe).Source
}
$env:GOVIEW_AUDIT_SECRET = 'local-integration-secret'
$env:RUOYI_SECURITY_ENDPOINT = 'http://127.0.0.1:8081/internal/security/context'
$env:RUOYI_AUDIT_ENDPOINT = 'http://127.0.0.1:8081/internal/carbon/audit/operation'
$env:RUOYI_AUDIT_URL = 'http://127.0.0.1:8081/internal/goview/audit'
$env:CARBON_REPORT_PYTHON = $python
$env:CARBON_REPORT_RENDERER_ROOT = $root
$env:CARBON_REPORT_WORK_DIR = Join-Path $root 'report-work'
$env:CARBON_REPORT_ARTIFACT_DIR = Join-Path $root 'uploadPath/reports'
$env:ENERGY_PROJECT_ROOT = Join-Path $root 'energy_recovery_agent'
$env:ENERGY_PYTHON = $python
$env:ENERGY_DATABASE_URL = 'mysql://root:1275410782h@127.0.0.1:3306/carbon_emissions'
$env:ENERGY_UPLOAD_DIR = Join-Path $root 'uploadPath/energy'
$env:PYTHON_PATH = $python
$env:STEAM_CALCULATOR_SCRIPT = Join-Path $root 'tpfhs-9/backend/steam_calculator.py'
$env:BROWSER = 'none'
$env:PREDICTION_API_KEY = 'local-prediction-internal-key'
$predictionDbPassword = if ($env:PREDICTION_DB_PASSWORD) { $env:PREDICTION_DB_PASSWORD } elseif ($env:CARBON_DB_PASSWORD) { $env:CARBON_DB_PASSWORD } else { '1275410782h' }
New-Item -ItemType Directory -Path (Join-Path $root '.runtime/redis') -Force | Out-Null

function Start-ServiceProcess($name, $port, $executable, $directory, $arguments) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        Write-Output "$name already listening on $port"
        return
    }
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory (Join-Path $root $directory) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "$name.out.log") -RedirectStandardError (Join-Path $logs "$name.err.log") -PassThru
    Write-Output "$name PID=$($process.Id) PORT=$port"
}

function Wait-HttpReady($name, $url, $timeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Output "$name is ready: $url"
                return
            }
        } catch {
            # The JVM may still be loading modules or waiting for Redis/MySQL.
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "$name did not become ready within $timeoutSeconds seconds: $url"
}

if (Get-NetTCPConnection -State Listen -LocalPort 6379 -ErrorAction SilentlyContinue) {
    Write-Output 'redis already listening on 6379'
} elseif ($redisCommand) {
    Start-ServiceProcess 'redis' 6379 $redisCommand.Source '.' '--bind 127.0.0.1 --port 6379 --appendonly yes --dir .runtime/redis'
} else {
    throw 'Redis is not listening on 6379 and redis-server.exe was not found in PATH.'
}
Start-ServiceProcess 'main-backend' 8081 $java 'ruoyi-admin' '-jar target/ruoyi-admin.jar --server.port=8081'
Start-ServiceProcess 'model-backend' 8082 $java 'tpfhs-9/backend' '-jar target/carbon-emission-model-1.0.0.jar --spring.profiles.active=local --server.port=8082'
Start-ServiceProcess 'goview-backend' 8083 $java 'goview/go-view-serve-master' '-jar target/goview_admin-0.0.1-SNAPSHOT.war --server.port=8083'
Wait-HttpReady 'main-backend' 'http://127.0.0.1:8081/code'
$previousDbHost = $env:DB_HOST
$previousDbPort = $env:DB_PORT
$previousDbName = $env:DB_NAME
$previousDbUser = $env:DB_USER
$previousDbPassword = $env:DB_PASSWORD
$previousPredictionBase = $env:PREDICTION_BASE_URL
try {
    $env:DB_HOST = '127.0.0.1'; $env:DB_PORT = '3306'; $env:DB_NAME = 'carbon_emissions'; $env:DB_USER = 'root'; $env:DB_PASSWORD = $predictionDbPassword
    $env:PREDICTION_BASE_URL = 'http://127.0.0.1:8090'
    Start-ServiceProcess 'prediction-engine' 8090 $python 'railway_carbon_prediction' 'scripts/run_api.py'
    Start-ServiceProcess 'prediction-platform' 8086 $java 'railway_carbon_prediction/railway_carbon_platform/backend' '-jar target/carbon-platform-1.0.0.jar'
} finally {
    $env:DB_HOST = $previousDbHost; $env:DB_PORT = $previousDbPort; $env:DB_NAME = $previousDbName; $env:DB_USER = $previousDbUser; $env:DB_PASSWORD = $previousDbPassword
    $env:PREDICTION_BASE_URL = $previousPredictionBase
}
Start-ServiceProcess 'main-frontend' 80 $node 'ruoyi-ui' 'node_modules/vite/bin/vite.js --host 127.0.0.1 --port 80'
Start-ServiceProcess 'model-frontend' 5177 $node 'tpfhs-9/frontend' 'node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5177 --strictPort'
Start-ServiceProcess 'goview-frontend' 3000 $node 'goview/go-view-master-fetch' 'node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3000 --strictPort'
Start-ServiceProcess 'prediction-frontend' 5173 $node 'railway_carbon_prediction/railway_carbon_platform/frontend' 'node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort'
Write-Output "Logs: $logs"
