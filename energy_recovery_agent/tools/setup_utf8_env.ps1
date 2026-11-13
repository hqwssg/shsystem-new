<# 
Sets the current PowerShell session to UTF-8.

Usage from the project root:
  .\tools\setup_utf8_env.ps1

If local PowerShell policy blocks scripts, run these commands in the same
PowerShell window:
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  .\tools\setup_utf8_env.ps1

This script affects only the current terminal session. Run it again after
opening a new PowerShell window.
#>

$ErrorActionPreference = "Stop"

try {
    chcp 65001 | Out-Null
} catch {
    Write-Warning "Could not switch console code page to 65001: $($_.Exception.Message)"
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

[Console]::InputEncoding = $Utf8NoBom
[Console]::OutputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "UTF-8 environment configured for this PowerShell session."
Write-Host "Code page: $(chcp)"
Write-Host "PYTHONUTF8=$env:PYTHONUTF8"
Write-Host "PYTHONIOENCODING=$env:PYTHONIOENCODING"
