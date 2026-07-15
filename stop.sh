#!/usr/bin/env bash
# Stops the backend (uvicorn) and frontend (vite) dev servers started by
# start.sh.
#
# Does NOT use netstat's port->PID column - confirmed unreliable during
# testing on this machine: uvicorn --reload spawns its actual worker via
# Python's multiprocessing on Windows, and force-killing the reloader
# parent leaves that worker running as an orphan (Windows doesn't cascade
# process-tree kills by default). netstat then reports the port as owned
# by the now-dead parent PID, which no longer corresponds to any real
# process - killing that PID silently does nothing, and the real orphaned
# worker keeps the port held. Confirmed by inspecting the orphan's own
# command line: `python -c "from multiprocessing.spawn import spawn_main;
# spawn_main(parent_pid=<dead pid>...)"`.
#
# Instead, match by command line directly via WMI (Get-CimInstance), which
# reliably finds every real process regardless of the parent/child
# relationship - the reloader, its multiprocessing worker, and vite's
# node process all get caught by one pass.
set -uo pipefail

echo "== Stopping Reprompt =="

result=$(powershell.exe -NoProfile -Command '
$killed = @()
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @("python.exe","node.exe") -and
    ($_.CommandLine -match "reprompt_api" -or $_.CommandLine -match "multiprocessing.spawn" -or $_.CommandLine -match "vite" -or $_.CommandLine -match "pnpm.*dev")
} | ForEach-Object {
    $target = if ($_.CommandLine -match "vite" -or $_.CommandLine -match "pnpm.*dev") { "Frontend" } else { "Backend" }
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    $killed += "$target"
}
if ($killed.Count -eq 0) { "NONE" } else { $killed -join "," }
')

if [ "$result" = "NONE" ] || [ -z "$result" ]; then
  echo "Backend: not running"
  echo "Frontend: not running"
else
  backend_count=$(echo "$result" | tr ',' '\n' | grep -c "^Backend$" || true)
  frontend_count=$(echo "$result" | tr ',' '\n' | grep -c "^Frontend$" || true)
  if [ "$backend_count" -gt 0 ]; then
    echo "Backend: stopped successfully ($backend_count process(es))"
  else
    echo "Backend: not running"
  fi
  if [ "$frontend_count" -gt 0 ]; then
    echo "Frontend: stopped successfully ($frontend_count process(es))"
  else
    echo "Frontend: not running"
  fi
fi
