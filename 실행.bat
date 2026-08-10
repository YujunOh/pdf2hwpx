@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

%PY% -c "import fitz, PIL" >nul 2>nul
if errorlevel 1 (
    echo 필요한 패키지를 설치합니다. 처음 한 번만 걸립니다.
    %PY% -m pip install PyMuPDF pillow pywin32
)

%PY% gui.py %*

if errorlevel 1 (
    echo.
    echo 실행에 실패했습니다. 파이썬이 설치되어 있는지 확인하세요.
    pause
)
