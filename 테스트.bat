@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

rem 실제 디자인 PDF를 열어 둔 상태로 GUI를 띄운다. 아무것도 안 쳐도
rem 바로 F5 를 누를 수 있게 하려는 것이다.

set "DESIGN=%USERPROFILE%\OneDrive\문서\카카오톡 받은 파일\MoYanG 교재 디자인 3차_페이지단위v2_260809_202209.pdf"

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

%PY% -c "import fitz, PIL" >nul 2>nul
if errorlevel 1 (
    echo 필요한 패키지를 설치합니다. 처음 한 번만 걸립니다.
    %PY% -m pip install PyMuPDF pillow pywin32
)

if exist "%DESIGN%" (
    echo 디자인 PDF를 찾았습니다. 그 파일로 시작합니다.
    %PY% gui.py "%DESIGN%"
) else (
    echo 디자인 PDF를 못 찾았습니다. 빈 화면으로 시작합니다.
    echo 찾아보기로 PDF를 고르세요.
    %PY% gui.py
)

if errorlevel 1 (
    echo.
    echo 실행에 실패했습니다. 파이썬이 설치되어 있는지 확인하세요.
    pause
)
