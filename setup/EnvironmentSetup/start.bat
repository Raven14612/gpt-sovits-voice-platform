@echo off
setlocal EnableExtensions
cd /d "%~dp0..\.."
if not exist "%CD%\runtimes\ui\python.exe" (
  echo Package UI Python missing. See setup\EnvironmentSetup\PREPARE.md.
  echo Source checkout: use Windows x64 Python 3.13 to run scripts\assemble_ui_runtime.py.
  exit /b 1
)
"%CD%\runtimes\ui\python.exe" -s -u "%CD%\setup\EnvironmentSetup\env_setup\checker.py" %*
exit /b %errorlevel%
