# One-command reliable dev-server restart for Windows.
#
#   powershell -ExecutionPolicy Bypass -File scripts\dev-restart.ps1
#
# Why this exists (see DEV_TRACKER.md "Ghost dev-server root cause"):
# uvicorn --reload spawns its real worker via Python multiprocessing. If the
# reloader parent dies (closed terminal, crash), Windows does NOT cascade the
# kill - the worker survives as an orphan that keeps serving STALE code on
# port 8000 indefinitely. Worse, netstat then reports the port as owned by
# the now-dead parent PID, so `Stop-Process -Id <netstat pid>` fails with
# "Cannot find a process" while the port stays busy - the "ghost socket".
# The reliable kill is by *command line* via WMI, which finds the orphan
# worker directly. This script does that, verifies the ports are truly free,
# starts fresh servers, and health-checks that the new backend is actually
# serving current code (not another stale orphan).

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "== Reprompt dev restart ==" -ForegroundColor Cyan

# --- 1. Kill every dev-server process by command line (not by netstat PID) ---
$targets = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @("python.exe", "node.exe") -and (
        $_.CommandLine -match "uvicorn.*reprompt_api" -or
        $_.CommandLine -match "multiprocessing\.spawn" -or
        # vite dev server only - deliberately does NOT match vitest runs
        ($_.CommandLine -match "vite[\\/]bin[\\/]vite\.js" -and $_.CommandLine -match "Reprompt")
    )
}
foreach ($p in $targets) {
    Write-Host ("Killing PID {0} ({1}): {2}" -f $p.ProcessId, $p.Name,
        $p.CommandLine.Substring(0, [Math]::Min(100, $p.CommandLine.Length))) -ForegroundColor Yellow
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
if (-not $targets) { Write-Host "No existing dev-server processes found." }
Start-Sleep -Seconds 2

# --- 2. Verify ports 8000/5173 are genuinely free ---
foreach ($port in 8000, 5173) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $ownerPid = $listener[0].OwningProcess
        $owner = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
        if ($owner) {
            Write-Host "Port ${port} still held by live PID $ownerPid ($($owner.ProcessName)) - killing it." -ForegroundColor Yellow
            Stop-Process -Id $ownerPid -Force
            Start-Sleep -Seconds 2
        } else {
            # netstat/Get-NetTCPConnection blames a dead PID: the real holder
            # is an orphan worker WMI should have caught above. If we get
            # here, hunt any remaining multiprocessing orphan explicitly.
            Write-Host "Port ${port} shows a ghost listener (dead PID $ownerPid). Hunting orphans..." -ForegroundColor Red
            Get-CimInstance Win32_Process |
                Where-Object { $_.CommandLine -match "multiprocessing\.spawn" } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Start-Sleep -Seconds 2
            if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
                throw "Port ${port} is still held after orphan hunt. Reboot, or start the API on another port (uvicorn --port 8001 + VITE_API_URL in apps/web/.env.local)."
            }
        }
    }
}
Write-Host "Ports 8000 and 5173 are free." -ForegroundColor Green

# --- 3. Start fresh servers (same terminal-window pattern as start.sh) ---
Start-Process powershell -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $repoRoot 'scripts\run-backend.ps1')
Start-Process powershell -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $repoRoot 'scripts\run-frontend.ps1')

# --- 4. Health-check: fresh backend must serve CURRENT code ---
# /settings/system-models only exists in post-2026-07-16 code; a stale orphan
# that somehow survived would 404 it or miss it from the openapi spec.
# 90s: `uv run` can block on the venv lock if another uv process is active.
$deadline = (Get-Date).AddSeconds(90)
$ok = $false
while ((Get-Date) -lt $deadline) {
    try {
        $spec = Invoke-RestMethod http://localhost:8000/openapi.json -TimeoutSec 3
        if ($spec.paths.PSObject.Properties.Name -contains "/settings/system-models") { $ok = $true; break }
        throw "Backend on :8000 is up but serving STALE code (no /settings/system-models route)."
    } catch {
        if ($_.Exception.Message -match "STALE") { throw }
        Start-Sleep -Seconds 1
    }
}
if (-not $ok) { throw "Backend did not come up on :8000 within 90s - check the backend terminal window." }
Write-Host "Backend healthy on http://localhost:8000 and serving current code." -ForegroundColor Green

$deadline = (Get-Date).AddSeconds(30)
$ok = $false
while ((Get-Date) -lt $deadline) {
    try {
        $null = Invoke-WebRequest http://localhost:5173 -TimeoutSec 3 -UseBasicParsing
        $ok = $true; break
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $ok) { throw "Frontend did not come up on :5173 within 30s - check the frontend terminal window." }
Write-Host "Frontend healthy on http://localhost:5173." -ForegroundColor Green
Write-Host ""
Write-Host "Restart complete. Hard-refresh the browser (Ctrl+Shift+R)." -ForegroundColor Cyan
