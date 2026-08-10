@echo off
setlocal
cd /d "%~dp0"

rem Everything here is ASCII on purpose. cmd reads a .bat using the system
rem code page, so Korean text in this file breaks depending on the console.
rem The Korean PDF path lives in out\sample.dhp instead, which is UTF-8 JSON.

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

%PY% -c "import fitz, PIL" >nul 2>nul
if errorlevel 1 (
    echo Installing required packages. This happens only once.
    %PY% -m pip install PyMuPDF pillow pywin32
)

if exist "out\sample.dhp" (
    %PY% gui.py "out\sample.dhp"
) else (
    %PY% gui.py
)

if errorlevel 1 (
    echo.
    echo Failed to start. Check that Python is installed.
    pause
)
