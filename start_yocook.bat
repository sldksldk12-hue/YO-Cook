@echo off
title YO-Cook AI Cooking Mate Launcher
cd /d "%~dp0"

echo ========================================================
echo   YO-Cook Backend Server and Mobile App Launcher
echo ========================================================
echo.

set PYTHON_EXE=python
if exist "%~dp0.venv\Scripts\python.exe" set PYTHON_EXE="%~dp0.venv\Scripts\python.exe"
if exist "%~dp0venv\Scripts\python.exe" set PYTHON_EXE="%~dp0venv\Scripts\python.exe"
if exist "%~dp0..\.venv\Scripts\python.exe" set PYTHON_EXE="%~dp0..\.venv\Scripts\python.exe"
if exist "%~dp0..\..\.venv\Scripts\python.exe" set PYTHON_EXE="%~dp0..\..\.venv\Scripts\python.exe"
if exist "D:\KDT2604\.venv\Scripts\python.exe" set PYTHON_EXE="D:\KDT2604\.venv\Scripts\python.exe"

echo [Using Python]: %PYTHON_EXE%
echo [1/2] Starting FastAPI Backend Server on port 8000...

start "YO-Cook Backend" cmd /k "%PYTHON_EXE% -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo Waiting 6 seconds for Backend Server to load Whisper model...
timeout /t 6 /nobreak > nul

echo [2/2] Opening Local App UI (http://localhost:8000/app)...
start http://localhost:8000/app

if not exist "C:\Program Files (x86)\cloudflared\cloudflared.exe" goto NO_CF
echo.
echo ========================================================
echo   Creating Public HTTPS URL for Mobile and Team Access
echo   Copy the https://....trycloudflare.com URL below
echo   and add /app at the end!
echo ========================================================
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --protocol http2 --url http://127.0.0.1:8000
goto END

:NO_CF
echo.
echo Local URL: http://localhost:8000/app
pause

:END
