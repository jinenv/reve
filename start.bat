@echo off
echo [NYXA] Activating virtual environment...
call .\venv\Scripts\activate.bat

if not exist .env (
    echo [ERROR] .env file is missing.
    pause
    exit /b
)

echo [NYXA] Updating dependencies...
pip install -r requirements.txt

echo [NYXA] Applying database migrations...
alembic upgrade head

echo [NYXA] Starting Bot...
python run.py

echo [NYXA] Bot shut down.
pause
