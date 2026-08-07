@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo [pdf2hwpx] exe 빌드를 시작합니다.
echo.

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

%PY% -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo PyInstaller가 없어 설치합니다.
    %PY% -m pip install pyinstaller
)

%PY% -m PyInstaller --noconfirm --clean ^
  --onefile ^
  --noconsole ^
  --name pdf2hwpx ^
  --add-data "resources;resources" ^
  --exclude-module matplotlib ^
  --exclude-module numpy ^
  --exclude-module pytest ^
  gui.py

if errorlevel 1 (
    echo.
    echo 빌드에 실패했습니다.
    pause
    exit /b 1
)

echo.
echo 완료. dist\pdf2hwpx.exe 를 더블클릭해서 쓰세요.
dir /b dist
pause
