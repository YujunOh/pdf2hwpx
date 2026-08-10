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

rem 안 쓰는 무거운 것들을 뺀다. 115MB에서 34MB로 줄어든다.
rem   lxml 7MB      XML은 정규식으로 처리한다
rem PIL은 빼지 말 것. 미리보기 배경을 PDF에서 구워 화면에 올릴 때 쓴다.
rem   Pythonwin 7MB pywin32의 MFC GUI 부분. COM만 쓰므로 필요 없다
rem setuptools, pip, unittest, pydoc은 빼지 말 것. 빼면 exe가 조용히 멈춘다.
%PY% -m PyInstaller --noconfirm --clean ^
  --onefile ^
  --noconsole ^
  --name pdf2hwpx ^
  --add-data "resources;resources" ^
  --exclude-module matplotlib ^
  --exclude-module numpy ^
  --exclude-module pytest ^
  --exclude-module pandas ^
  --exclude-module lxml ^
  --exclude-module Pythonwin ^
  --exclude-module win32ui ^
  --exclude-module win32uiole ^
  --exclude-module dde ^
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
