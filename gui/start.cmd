@echo off
rem Startet die GUI aus dem venv. Legt das venv beim ersten Mal an.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Lege venv an und installiere pyserial ...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto :error
)

start "" ".venv\Scripts\pythonw.exe" "smbuspeek.py"
exit /b 0

:error
echo.
echo Fehlgeschlagen. Ist Python 3 im PATH?
pause
exit /b 1
