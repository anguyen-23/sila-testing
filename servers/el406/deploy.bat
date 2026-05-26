@echo off
echo === El406 Server Deployment ===
echo.
echo Installing el406 server...
pip install -e "%~dp0"
echo.
echo Adding firewall rule for port 50061...
netsh advfirewall firewall add rule name="El406 SiLA" dir=in action=allow protocol=TCP localport=50061
echo.
echo Done. Start the server with:
echo   python -m el406 --insecure --port 50061 -a 0.0.0.0 --verbose
pause
