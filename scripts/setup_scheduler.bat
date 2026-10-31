@echo off
REM ==============================================================================
REM AtliQ Morning Digest Agent - Windows Task Scheduler Setup Script
REM Registers a daily scheduled task to run at 8:00 AM using the local Python venv.
REM ==============================================================================

set TASK_NAME=AtliQMorningDigestAgent
set WORKSPACE_DIR=%~dp0..
cd /d "%WORKSPACE_DIR%"

if not exist logs mkdir logs

echo Registering Windows Task '%TASK_NAME%' to run daily at 8:00 AM...

schtasks /create /tn "%TASK_NAME%" /tr "\"%WORKSPACE_DIR%\venv\Scripts\python.exe\" -m src.main" /sc daily /st 08:00 /f

if %ERRORLEVEL% equ 0 (
    echo [SUCCESS] Task '%TASK_NAME%' registered successfully!
    echo To view the task, open Task Scheduler or run: schtasks /query /tn "%TASK_NAME%"
) else (
    echo [ERROR] Failed to register scheduled task. Please run as Administrator if required.
)

pause

