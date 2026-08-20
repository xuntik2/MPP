@echo off
chcp 866 >nul
setlocal utf8

echo ==========================================
echo        MemeParser - Initialization...
echo ==========================================

if not exist "venv" (
    echo [1/4] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create venv. Check if Python is installed.
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat

echo [2/4] Installing dependencies...
python -m pip install --upgrade pip -q
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo [3/4] Creating data directories...
if not exist "data\memes\office" mkdir "data\memes\office"
if not exist "data\memes\it" mkdir "data\memes\it"
if not exist "data\memes\mass" mkdir "data\memes\mass"
if not exist "data\memes\dark" mkdir "data\memes\dark"
if not exist "data\memes\news" mkdir "data\memes\news"

echo [4/4] Starting Web Server...
echo.
echo ------------------------------------------
echo  Server is starting...
echo  Open in browser: http://127.0.0.1:8000
echo ------------------------------------------
echo.

timeout /t 3 /nobreak >nul
start http://127.0.0.1:8000

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

pause
