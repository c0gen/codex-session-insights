@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0_internal\" (
  echo Extract the entire ZIP before starting the app. The _internal folder must stay beside the EXE.
  pause
  exit /b 1
)
start "" "%~dp0CodexSessionInsights.exe"
