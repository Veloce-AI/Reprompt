#!/usr/bin/env bash
# Starts the backend and frontend, each in its own terminal window.
# Closing a window stops that service; `bash stop.sh` stops both from here.
# Safe to re-run, but if both are already running you'll get a port
# conflict in the new windows - run stop.sh first if restarting.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
REPO_ROOT_WIN="$(cygpath -w "$(pwd)")"

echo "== Starting Reprompt =="

echo "Backend starting -> http://localhost:8000  (docs: http://localhost:8000/docs)"
powershell.exe -NoProfile -Command "Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File','$REPO_ROOT_WIN\scripts\run-backend.ps1'"

sleep 1

echo "Frontend starting -> http://localhost:5173"
powershell.exe -NoProfile -Command "Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File','$REPO_ROOT_WIN\scripts\run-frontend.ps1'"

echo
echo "Both are running in their own terminal windows now."
echo "Close a window to stop that one service, or run: bash stop.sh"
