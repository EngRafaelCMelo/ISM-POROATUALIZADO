@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Ambiente virtual nao encontrado. Execute: python -m venv .venv
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app.py
