@echo off
:: Quick-start the Temperature Controller SiLA 2 server (after deploy.bat has been run)
::
:: Usage:
::   start_server.bat                  - Start in simulation mode
::   start_server.bat --real           - Start in real mode
::   start_server.bat --port 50099     - Use a different port

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "MODE="
set "PORT=50052"

:: Parse arguments
:parse_args
if "%~1"=="" goto :done_args
if /i "%~1"=="--real" set "MODE=real"
if /i "%~1"=="--port" (
    set "PORT=%~2"
    shift
)
shift
goto :parse_args
:done_args

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run deploy.bat first.
    pause
    exit /b 1
)

echo Temperature Controller SiLA 2 Server - port %PORT%

if "%MODE%"=="real" (
    echo Mode: REAL
    "%VENV_DIR%\Scripts\python.exe" -m temperature_controller --insecure -a 0.0.0.0 -p %PORT% --verbose
) else (
    echo Mode: SIMULATION
    "%VENV_DIR%\Scripts\python.exe" -m temperature_controller --insecure -a 0.0.0.0 -p %PORT% --verbose
)

pause
