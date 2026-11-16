@echo off
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "VENV_PY=%~dp0..\tools\jadx-mcp\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [error] venv python not found: %VENV_PY%
  exit /b 1
)
if "%~1"=="" (
  echo Drag a capture file onto dec.bat, or type its full path below.
  set /p "INPUT=File path: "
  if not defined INPUT goto :eof
  "%VENV_PY%" "%~dp0decrypt_capture.py" "%INPUT%"
) else (
  "%VENV_PY%" "%~dp0decrypt_capture.py" %*
)
echo.
pause
