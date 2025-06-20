@echo off
echo [JIJI] Activating virtual environment...
call .\venv\Scripts\activate.bat

if not exist .env (
    echo [ERROR] .env file is missing.
    pause
    exit /b
)

echo [JIJI] Updating dependencies...
pip install -r requirements.txt

echo [JIJI] Applying database migrations...
alembic upgrade head

echo [JIJI] Starting Bot...
python run.py

echo [JIJI] Bot shut down.
pause
