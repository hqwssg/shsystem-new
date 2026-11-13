param(
    [ValidateSet("start", "stop", "status")]
    [string]$Action = "status",
    [int]$Port = 55432,
    [string]$InstanceRoot = "$env:LOCALAPPDATA\energy_retry_pg16"
)

$pgCtl = Join-Path $InstanceRoot "pgsql\bin\pg_ctl.exe"
$pgReady = Join-Path $InstanceRoot "pgsql\bin\pg_isready.exe"
$dataDir = Join-Path $InstanceRoot "data"
$logPath = Join-Path $InstanceRoot "postgresql.log"

if (-not (Test-Path -LiteralPath $pgCtl) -or -not (Test-Path -LiteralPath $dataDir)) {
    throw "未找到已初始化的本地PostgreSQL测试实例：$InstanceRoot"
}

switch ($Action) {
    "start" {
        & $pgCtl -D $dataDir -l $logPath -o "`"-p`" `"$Port`" `"-h`" `"127.0.0.1`"" -w start
    }
    "stop" {
        & $pgCtl -D $dataDir -m fast -w stop
    }
    "status" {
        & $pgReady -h 127.0.0.1 -p $Port -U postgres
    }
}

exit $LASTEXITCODE
