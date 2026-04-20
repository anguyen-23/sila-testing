@echo off
REM Launches all SiLA 2 servers and the client web UI.
REM Usage: start_all.bat
REM Close this window or press Ctrl+C to stop everything.

cd /d "%~dp0"

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo ERROR: Could not find .venv. Run: python -m venv .venv ^&^& pip install -r requirements.txt
    exit /b 1
)

echo === Starting SiLA 2 servers ===

start "Temperature Controller (50052)" python -m temperature_controller --insecure --port 50052
echo   Temperature Controller  -^> port 50052

start "Pump Controller (50053)" python -m pump_controller --insecure --port 50053
echo   Pump Controller         -^> port 50053

start "Plate Reader (50054)" python -m plate_reader --insecure --port 50054
echo   Plate Reader            -^> port 50054

start "Multidrop Combi (50055)" python -m multidrop_combi --insecure --port 50055
echo   Multidrop Combi         -^> port 50055

start "Venus API (50056)" python -m venus_api --insecure --port 50056
echo   Venus API               -^> port 50056

start "Barcode Scanner (50057)" python -m barcode_scanner --insecure --port 50057
echo   Barcode Scanner         -^> port 50057

start "Phenix Imager (50058)" python -m phenix_imager --insecure --port 50058
echo   Phenix Imager           -^> port 50058

start "Micronic Tube Scanner (50059)" python -m micronic_tube_scanner --insecure --port 50059
echo   Micronic Tube Scanner   -^> port 50059

echo.
echo === Starting Client Web UI ===

start "Web UI (5000)" python -m client_web_ui
echo   Web UI                  -^> http://localhost:5000

echo.
echo Everything is running. Close the individual windows to stop each process.
pause
