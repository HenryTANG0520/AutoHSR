@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 1

if exist "%~dp0dist\AutoHSR\AutoHSR.exe" (
    start "" "%~dp0dist\AutoHSR\AutoHSR.exe"
    exit /b 0
)

if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" -m autohsr
    exit /b 0
)

echo AutoHSR is not installed in this folder.
echo Run setup.ps1 with Python 3.10 or newer, then start again.
echo Example: powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
pause
exit /b 1
