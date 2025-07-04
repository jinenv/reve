@echo off
echo [REVE] Starting Bot...
cd /d C:\reve
call .\venv\Scripts\activate.bat

echo [REVE] Running bot directly...
python bot.py

pause