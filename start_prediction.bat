@echo off
rem One-click launcher for the pre-match prediction webapp.
rem Double-click to start the server and open the browser.
rem Close this window to stop the server. Optional arg: port (default 8600).

setlocal
rem repo root is fixed so the launcher works from any location (e.g. desktop)
set "REPO=C:\football"
cd /d "%REPO%"
set "PYTHONPATH=%REPO%\src"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8600"

rem if the service is already up on this port, just open the page
curl -s --max-time 3 http://127.0.0.1:%PORT%/api/health >nul 2>&1
if %errorlevel%==0 (
    echo Service already running - opening page...
    start "" http://127.0.0.1:%PORT%/
    exit /b 0
)

echo Starting server on port %PORT% (close this window to stop)...
start "" http://127.0.0.1:%PORT%/
python -m football_prediction.cli serve --port %PORT%
