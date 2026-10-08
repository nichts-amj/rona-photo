@echo off
cd /d "%~dp0"
if not exist "%~dp0desktop\bin\Rona Photo.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\build.ps1"
  if errorlevel 1 exit /b 1
)
start "" "%~dp0desktop\bin\Rona Photo.exe"
