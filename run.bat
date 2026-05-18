@echo off
echo ===========================================
echo        SNTI AI Chatbot Launcher
echo ===========================================

echo [1/3] Activating virtual environment...
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo WARNING: Virtual environment not found at .venv\Scripts\activate.bat
)

echo [2/3] Starting Backend API in a new window...
start "SNTI Backend" python -m uvicorn api.main:app --reload --port 8000

echo [3/3] Starting Frontend React App in a new window...
cd frontend
start "SNTI Frontend" npm run dev

echo.
echo Done! Two terminal windows opened:
echo   - Backend:  http://127.0.0.1:8000
echo   - Frontend: http://localhost:5173
echo.
echo Close each window independently when done.

