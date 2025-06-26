@echo off
echo [JIJI] Starting Bot...
cd /d C:\jiji
call .\venv\Scripts\activate.bat

echo [JIJI] Running bot directly...
python bot.py

pause