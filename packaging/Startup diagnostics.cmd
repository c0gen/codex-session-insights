@echo off
setlocal
cd /d "%~dp0"
set "insightsDirectory=%LOCALAPPDATA%\Codex Session Insights"
if defined CODEX_INSIGHTS_DATA_DIR set "insightsDirectory=%CODEX_INSIGHTS_DATA_DIR%"
"%~dp0CodexSessionInsights.exe" --data-dir "%insightsDirectory%" --diagnose
if exist "%insightsDirectory%\startup.log" (
  start "" notepad.exe "%insightsDirectory%\startup.log"
) else (
  echo The executable did not create a startup log. Check that the full ZIP was extracted and review any Windows launch warning.
  pause
)
