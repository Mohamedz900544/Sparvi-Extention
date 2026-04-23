@echo off
setlocal

cd /d "%~dp0"
set "DIST_DIR=dist"
set "WORK_DIR=build"
set "SPEC_DIR=."

echo [1/4] Installing client build dependencies...
python -m pip install -r requirements-client.txt
if errorlevel 1 exit /b 1

echo [2/4] Closing running Sparvi Desktop Pointer processes...
taskkill /IM "Sparvi Desktop Pointer.exe" /F >nul 2>&1
ping 127.0.0.1 -n 3 >nul

echo [3/4] Cleaning old build output...
if exist "dist\Sparvi Desktop Pointer.exe" del /F /Q "dist\Sparvi Desktop Pointer.exe" >nul 2>&1
if exist "dist\Sparvi Desktop Pointer.exe" (
  echo Existing exe is still locked. Building into a fresh output folder.
  set "DIST_DIR=dist-fresh"
  set "WORK_DIR=build-fresh"
)
if exist "%WORK_DIR%" rmdir /S /Q "%WORK_DIR%"
if exist "%DIST_DIR%" rmdir /S /Q "%DIST_DIR%"
if exist "Sparvi Desktop Pointer.spec" del /F /Q "Sparvi Desktop Pointer.spec"

echo [4/4] Building Windows exe...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onefile ^
  --distpath "%DIST_DIR%" ^
  --workpath "%WORK_DIR%" ^
  --specpath "%SPEC_DIR%" ^
  --name "Sparvi Desktop Pointer" ^
  client_app.py
if errorlevel 1 exit /b 1

echo.
echo Build finished successfully.
echo EXE: %DIST_DIR%\Sparvi Desktop Pointer.exe
endlocal
