@echo off
:: Temperature Controller SiLA 2 Server - One-click deploy script
::
:: Usage:
::   deploy.bat              - Install and start in simulation mode
::   deploy.bat --real       - Install and start in real mode
::   deploy.bat --install    - Install only (don't start)

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "VENV_DIR=%SCRIPT_DIR%\.venv"
set "MODE=simulation"
set "INSTALL_ONLY=0"

:: Parse arguments
:parse_args
if "%~1"=="" goto :done_args
if /i "%~1"=="--real" set "MODE=real"
if /i "%~1"=="--install" set "INSTALL_ONLY=1"
shift
goto :parse_args
:done_args

echo.
echo ============================================
echo   Temperature Controller SiLA 2 Server - Deploy
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo [OK] Python %PYVER% found

:: Create venv if needed
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo.
    echo [1/3] Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)

:: Install/upgrade package
echo.
echo [2/3] Installing temperature_controller and dependencies...
"%VENV_DIR%\Scripts\pip.exe" install --upgrade pip >nul 2>&1
"%VENV_DIR%\Scripts\pip.exe" install -e "%SCRIPT_DIR%"
if errorlevel 1 (
    echo [ERROR] Installation failed
    pause
    exit /b 1
)
echo [OK] Installation complete

:: Open firewall port (may require admin)
echo.
echo [3/3] Checking firewall rule...
netsh advfirewall firewall show rule name="SiLA Temperature Controller" >nul 2>&1
if errorlevel 1 (
    echo      Adding firewall rule for port 50052...
    netsh advfirewall firewall add rule name="SiLA Temperature Controller" dir=in action=allow protocol=tcp localport=50052 >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Could not add firewall rule. Run as Administrator if needed.
    ) else (
        echo [OK] Firewall rule added
    )
) else (
    echo [OK] Firewall rule already exists
)

if "%INSTALL_ONLY%"=="1" (
    echo.
    echo Installation complete. Start manually with:
    echo   "%VENV_DIR%\Scripts\python.exe" -m temperature_controller --insecure -a 0.0.0.0 -p 50052 --verbose
    pause
    exit /b 0
)

:: Start server
echo.
echo ============================================
if "%MODE%"=="simulation" (
    echo   Starting in SIMULATION mode
    echo ============================================
    echo.
    "%VENV_DIR%\Scripts\python.exe" -m temperature_controller --insecure -a 0.0.0.0 -p 50052 --verbose
) else (
    echo   Starting in REAL mode
    echo ============================================
    echo.
    "%VENV_DIR%\Scripts\python.exe" -m temperature_controller --insecure -a 0.0.0.0 -p 50052 --verbose
)

pause
