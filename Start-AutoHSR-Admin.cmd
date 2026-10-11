@echo off
setlocal
set "AUTOHSR_LAUNCHER=%~dp0Start-AutoHSR.cmd"
if not exist "%AUTOHSR_LAUNCHER%" (
    echo Start-AutoHSR.cmd was not found beside this launcher.
    pause
    exit /b 1
)

powershell.exe -NoProfile -Command "try { Start-Process -FilePath $env:AUTOHSR_LAUNCHER -Verb RunAs -WindowStyle Hidden -ErrorAction Stop } catch { Write-Error $_; exit 1 }"
if errorlevel 1 (
    echo Administrator launch was cancelled or failed.
    pause
    exit /b 1
)
exit /b 0
