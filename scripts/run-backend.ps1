# Launched by start.sh in its own terminal window. Closing this window
# stops the backend (the uv/uvicorn process is this window's own
# foreground process).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\apps\api")

if (Test-Path ".env") {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') {
            [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2])
        }
    }
} else {
    Write-Host "No apps/api/.env found - run scripts/setup.sh first." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Reprompt API starting -> http://localhost:8000  (docs: http://localhost:8000/docs)" -ForegroundColor Green
Write-Host "Close this window to stop the backend." -ForegroundColor DarkGray
Write-Host ""

uv run uvicorn reprompt_api.main:app --reload
