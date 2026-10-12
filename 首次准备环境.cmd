@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup_simulation.ps1
if errorlevel 1 echo FAILED - see the error above.
pause
