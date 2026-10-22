@echo off
setlocal
cd /d "%~dp0"
if not exist "desktop\AgentLab.Desktop\bin\Release\AgentLab.Desktop.exe" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-Desktop.ps1"
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
start "" "desktop\AgentLab.Desktop\bin\Release\AgentLab.Desktop.exe" --root "%~dp0."
