@echo off
setlocal
cd /d "%~dp0sekiro-server"
if errorlevel 1 (
  echo [ERROR] cannot cd to sekiro-server
  pause
  exit /b 1
)
set "JAVA_HOME=D:\Java\jdk18\jdk-18.0.2.1"
if exist "%JAVA_HOME%\bin\java.exe" set "PATH=%JAVA_HOME%\bin;%PATH%"
echo Sekiro server starting on port 5612
echo Dir: %CD%
call bin\sekiro.bat
echo.
echo Server stopped. Press any key to close.
pause >nul