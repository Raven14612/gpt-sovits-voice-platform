@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
if not exist "%~dp0runtimes\ui\python.exe" (
    echo Package UI runtime missing: runtimes\ui\python.exe
    echo See README.md to assemble the UI runtime. No PATH Python fallback is used.
    set "PLATFORM_EXIT_CODE=1"
    goto startup_failed
)
"%~dp0runtimes\ui\python.exe" -s -u "%~dp0scripts\launch.py" %*
set "PLATFORM_EXIT_CODE=%errorlevel%"
if "%PLATFORM_EXIT_CODE%"=="0" exit /b 0

:startup_failed
echo.
echo Startup failed. Please read the error above.
echo Details, when available: data\logs\launcher-error.log
if not "%~1"=="" exit /b %PLATFORM_EXIT_CODE%
echo Press any key to close this window.
pause >nul
exit /b %PLATFORM_EXIT_CODE%
