@echo off
title YO-Cook AI Cooking Mate Launcher

set "PROJ_DIR=%~dp0"
if exist "%~dp0app\main.py" set "PROJ_DIR=%~dp0"
if exist "%~dp0yocook\app\main.py" set "PROJ_DIR=%~dp0yocook\"
if exist "%~dp0Dropbox\yocook\app\main.py" set "PROJ_DIR=%~dp0Dropbox\yocook\"
if exist "D:\KDT2604\Dropbox\yocook\app\main.py" set "PROJ_DIR=D:\KDT2604\Dropbox\yocook\"
if exist "C:\KDT2604\Dropbox\yocook\app\main.py" set "PROJ_DIR=C:\KDT2604\Dropbox\yocook\"
if exist "%USERPROFILE%\Dropbox\yocook\app\main.py" set "PROJ_DIR=%USERPROFILE%\Dropbox\yocook\"

cd /d "%PROJ_DIR%"

echo ========================================================
echo   YO-Cook Backend Server and Mobile App Launcher
echo ========================================================
echo [Project Directory]: %PROJ_DIR%
echo.

if not exist "%PROJ_DIR%app\main.py" (
    echo [ERROR] Cannot find yocook\app\main.py!
    echo Make sure this .bat file is inside the yocook folder.
    pause
    exit /b 1
)

set "PYTHON_EXE=python"
if exist "%PROJ_DIR%.venv\Scripts\python.exe" set "PYTHON_EXE=%PROJ_DIR%.venv\Scripts\python.exe"
if exist "%PROJ_DIR%venv\Scripts\python.exe" set "PYTHON_EXE=%PROJ_DIR%venv\Scripts\python.exe"
if exist "%PROJ_DIR%..\.venv\Scripts\python.exe" set "PYTHON_EXE=%PROJ_DIR%..\.venv\Scripts\python.exe"
if exist "%PROJ_DIR%..\venv\Scripts\python.exe" set "PYTHON_EXE=%PROJ_DIR%..\venv\Scripts\python.exe"
if exist "%PROJ_DIR%..\..\.venv\Scripts\python.exe" set "PYTHON_EXE=%PROJ_DIR%..\..\.venv\Scripts\python.exe"
if exist "D:\KDT2604\.venv\Scripts\python.exe" set "PYTHON_EXE=D:\KDT2604\.venv\Scripts\python.exe"
if exist "C:\KDT2604\.venv\Scripts\python.exe" set "PYTHON_EXE=C:\KDT2604\.venv\Scripts\python.exe"

echo [Using Python]: %PYTHON_EXE%
echo [1/2] Starting FastAPI Backend Server on port 8000...

start "YO-Cook Backend" /D "%PROJ_DIR%" cmd /k ""%PYTHON_EXE%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo Waiting 6 seconds for Backend Server to load Whisper model...
timeout /t 6 /nobreak > nul

echo [2/2] Opening Local App UI (http://localhost:8000)...
start http://localhost:8000

if not exist "C:\Program Files (x86)\cloudflared\cloudflared.exe" goto NO_CF
echo.
echo ========================================================
echo   Creating Public HTTPS URL for Mobile and Team Access
echo   Copy the https://....trycloudflare.com URL below!
echo ========================================================
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --protocol http2 --url http://127.0.0.1:8000
goto END

:NO_CF
echo.
echo Local URL: http://localhost:8000
pause

:END
