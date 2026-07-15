# Launched by start.sh in its own terminal window. Closing this window
# stops the frontend (the pnpm dev process is this window's own
# foreground process).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\apps\web")

Write-Host ""
Write-Host "Reprompt Web starting -> http://localhost:5173" -ForegroundColor Green
Write-Host "Close this window to stop the frontend." -ForegroundColor DarkGray
Write-Host ""

pnpm dev
