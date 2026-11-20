@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" "%SCRIPT_DIR%scripts\panel_photo_labeler.py" %*
) else (
    python "%SCRIPT_DIR%scripts\panel_photo_labeler.py" %*
)

pause
exit /b %ERRORLEVEL%
