@echo off
:: Screen Capture Helper — runs in the user session to provide
:: window enumeration and screen capture to SiLA services.
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" screen_capture_helper.py
