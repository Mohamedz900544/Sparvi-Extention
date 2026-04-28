@echo off
setlocal

set "APP_DIR=%~dp0Sparvi Extention Desktop Python exe"
set "EXE_PATH=%APP_DIR%\dist\Sparvi Desktop Pointer.exe"

if exist "%EXE_PATH%" (
  start "" "%EXE_PATH%"
  exit /b 0
)

cd /d "%APP_DIR%"
python client_app.py
