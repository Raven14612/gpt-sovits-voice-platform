@echo off
setlocal EnableExtensions

rem Always run from the project root, regardless of the caller's current directory.
cd /d "%~dp0"

echo [1/2] Checking port 7860...
for /f %%P in ('powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue ^| Select-Object -ExpandProperty OwningProcess -Unique"') do (
    echo Stopping process %%P on port 7860...
    taskkill /PID %%P /T /F >nul 2>&1
)

rem Give Windows a moment to release the listening socket.
timeout /t 1 /nobreak >nul

echo [2/2] Starting the project WebUI at http://127.0.0.1:7860/
python -u app.py

if errorlevel 1 (
    echo.
    echo WebUI exited with code %errorlevel%.
    echo Check that Python is installed and available on PATH.
    pause
)

endlocal
