@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Nova v2 - Sunucu

echo ============================================================
echo   Nova v2 - Sunucu baslatiliyor
echo ============================================================
echo.

set "PROJ="
if exist "%~dp0nova-v2\server.py" set "PROJ=%~dp0nova-v2"
if not defined PROJ if exist "%~dp0server.py" set "PROJ=%~dp0."
if not defined PROJ (
  echo [HATA] server.py bulunamadi. Once NOVA-KUR.bat ile dosyalari cikar.
  pause
  exit /b 1
)

pushd "%PROJ%"
if not exist ".venv\Scripts\python.exe" (
  echo [HATA] Python ortami yok. Once NOVA-SETUP.bat dosyasini calistir.
  popd
  pause
  exit /b 1
)

echo Sunucu: http://localhost:5000
echo Durdurmak icin: Ctrl + C
echo.
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start "" http://localhost:5000"
".venv\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 5000

echo.
echo Sunucu kapandi.
popd
pause
exit /b 0
