@echo off
setlocal

cd /d "%~dp0"
set "DIST_DIR=dist"
set "WORK_DIR=build"
set "TEMP_ICON=%TEMP%\sparvi-desktop-pointer-build-icon.ico"

echo [1/4] Installing client build dependencies...
python -m pip install -r requirements-client.txt
if errorlevel 1 exit /b 1

for /f "usebackq delims=" %%A in (`python -c "import struct; print(struct.calcsize('P') * 8)"`) do set "PYTHON_BITS=%%A"
echo Building with %PYTHON_BITS%-bit Python.
echo Compatibility: this PySide6/Qt6 build is for Windows 10 1809 or newer on the same CPU architecture.
echo It will not run on 32-bit Windows if built with 64-bit Python, or on Windows 7/8/8.1.
echo.

echo [2/4] Closing running Sparvi Desktop processes...
taskkill /IM "Sparvi Desktop Pointer.exe" /F >nul 2>&1
taskkill /IM "Sparvi Desktop Student.exe" /F >nul 2>&1
taskkill /IM "Sparvi Desktop Teacher.exe" /F >nul 2>&1
ping 127.0.0.1 -n 3 >nul

echo [3/4] Cleaning old build output...
if exist "dist\Sparvi Desktop Pointer.exe" del /F /Q "dist\Sparvi Desktop Pointer.exe" >nul 2>&1
if exist "dist\Sparvi Desktop Student.exe" del /F /Q "dist\Sparvi Desktop Student.exe" >nul 2>&1
if exist "dist\Sparvi Desktop Teacher.exe" del /F /Q "dist\Sparvi Desktop Teacher.exe" >nul 2>&1
if exist "dist\Sparvi Desktop Student.exe" (
  echo Existing student exe is still locked. Building into a fresh output folder.
  set "DIST_DIR=dist-fresh"
  set "WORK_DIR=build-fresh"
)
if exist "dist\Sparvi Desktop Teacher.exe" (
  echo Existing teacher exe is still locked. Building into a fresh output folder.
  set "DIST_DIR=dist-fresh"
  set "WORK_DIR=build-fresh"
)
if exist "dist\Sparvi Desktop Pointer.exe" (
  echo Existing exe is still locked. Building into a fresh output folder.
  set "DIST_DIR=dist-fresh"
  set "WORK_DIR=build-fresh"
)
if exist "%WORK_DIR%" rmdir /S /Q "%WORK_DIR%"
if exist "%DIST_DIR%" rmdir /S /Q "%DIST_DIR%"
if exist "%TEMP_ICON%" del /F /Q "%TEMP_ICON%" >nul 2>&1
if exist "icon.ico" del /F /Q "icon.ico" >nul 2>&1

echo [4/4] Building Windows exe from icon.png...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --distpath "%DIST_DIR%" ^
  --workpath "%WORK_DIR%" ^
  "Sparvi Desktop Pointer.spec"
if errorlevel 1 exit /b 1

if exist "%TEMP_ICON%" del /F /Q "%TEMP_ICON%" >nul 2>&1

echo.
echo Build finished successfully.
echo Generic EXE: %DIST_DIR%\Sparvi Desktop Pointer.exe
echo Student EXE: %DIST_DIR%\Sparvi Desktop Student.exe
echo Teacher EXE: %DIST_DIR%\Sparvi Desktop Teacher.exe
endlocal
