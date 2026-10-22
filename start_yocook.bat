@echo off
title YO-Cook AI Cooking Mate Launcher
cd /d "%~dp0"

echo ========================================================
echo   YO-Cook Backend Server and Mobile App Launcher
echo ========================================================
echo.
echo [1/2] Starting FastAPI Backend Server on port 8000...

if exist "D:\KDT2604\.venv\Scripts\uvicorn.exe" goto RUN_VENV
start "YO-Cook Backend" cmd /k "uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
goto OPEN_APP

:RUN_VENV
start "YO-Cook Backend" cmd /k "D:\KDT2604\.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000 --reload"

:OPEN_APP
timeout /t 3 /nobreak > nul
echo [2/2] Opening Local App UI (http://localhost:8000/app)...
start http://localhost:8000/app

if not exist "C:\Program Files (x86)\cloudflared\cloudflared.exe" goto NO_CF
echo.
echo ========================================================
echo   Creating Public HTTPS URL for Mobile and Team Access
echo   Copy the https://....trycloudflare.com URL below
echo   and add /app at the end!
echo ========================================================
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8000
goto END

:NO_CF
echo.
echo Local URL: http://localhost:8000/app
pause

:END
