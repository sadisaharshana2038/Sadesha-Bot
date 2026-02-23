@echo off
title Google Drive Uploader Bot
echo Starting Google Drive Uploader Bot...

:: Check for Python
where py >nul 2>nul
if %errorlevel% neq 0 (
    echo Python 'py' launcher not found. Please install Python from python.org.
    pause
    exit /b
)

:: Install dependencies if needed
echo Checking/Installing dependencies...
py -m pip install -r requirements.txt

:: Run the bot
echo Bot is starting...
py -u main.py

pause
