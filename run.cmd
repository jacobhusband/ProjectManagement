@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe"

rem launch.py imports main so Python can cache its bytecode; running main.py directly
rem recompiles all of it on every start.
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" "%SCRIPT_DIR%launch.py" %*
) else (
    python "%SCRIPT_DIR%launch.py" %*
)

exit /b %ERRORLEVEL%
