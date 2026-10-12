@echo off
cd /d "%~dp0"
python scripts\launch.py custom
if errorlevel 1 echo FAILED - see the error above.
pause
