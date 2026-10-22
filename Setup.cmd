@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 agentlab.py setup
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Instala Python 3.11 o posterior desde https://www.python.org/downloads/windows/
    echo Activa la opcion Add Python to PATH y vuelve a abrir Setup.cmd.
  ) else (
    python agentlab.py setup
  )
)
pause
