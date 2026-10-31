@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Nova v2 - EXE olustur

rem ============================================================
rem  Nova v2 kaynagindan tek dosya Nova.exe uretir (PyInstaller).
rem  Gereksinim: NOVA-SETUP.bat bir kez calistirilmis olmali.
rem  Kullanim:   NOVA-EXE-YAP.bat        (kaynak klasorunde)
rem ============================================================

echo ============================================================
echo   Nova v2 - Windows EXE derleme
echo ============================================================
echo.

set "PROJ=%~dp0"
if exist "%~dp0nova-v2\server.py" set "PROJ=%~dp0nova-v2\"
pushd "%PROJ%"

if not exist "server.py" goto :NOSRC
if not exist ".venv\Scripts\python.exe" goto :NOENV

echo [1/3] PyInstaller kuruluyor...
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller --disable-pip-version-check
if errorlevel 1 goto :FAIL

echo.
echo [2/3] Nova.exe derleniyor (2-5 dakika, sabir)...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --name Nova ^
 --add-data "index.html;." --add-data "app.js;." --add-data "styles.css;." ^
 --collect-submodules uvicorn --collect-submodules anyio --collect-submodules anthropic ^
 --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto ^
 --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto ^
 --hidden-import uvicorn.lifespan.on ^
 launcher.py
if errorlevel 1 goto :FAIL

if not exist "dist\Nova.exe" goto :NOEXE

echo.
echo [3/3] Bitti.
copy /y "dist\Nova.exe" "%USERPROFILE%\Desktop\Nova.exe" >nul 2>nul
if exist "%USERPROFILE%\Desktop\Nova.exe" (
  echo   Masaustune kopyalandi: %USERPROFILE%\Desktop\Nova.exe
) else (
  echo   Cikti: %PROJ%dist\Nova.exe
)
echo.
echo  Nova.exe'ye cift tikla: sunucu baslar + tarayici acilir.
echo  Not: Ilk calistirmada Windows "bilinmeyen yayinci" uyarabilir ->
echo       "Ek bilgi" -> "Yine de calistir".
echo  Veriler: %%APPDATA%%\Nova\nova.db
popd
echo.
pause
exit /b 0

:NOSRC
echo [HATA] server.py bulunamadi. Bu dosyayi nova-v2 klasorunde calistir.
popd
pause
exit /b 1

:NOENV
echo [HATA] Python ortami (.venv) yok. Once NOVA-SETUP.bat calistir.
popd
pause
exit /b 1

:NOEXE
echo [HATA] dist\Nova.exe uretilmedi. Yukaridaki hatalari kontrol et.
popd
pause
exit /b 1

:FAIL
echo.
echo [HATA] Derleme basarisiz. Yukaridaki son 20 satiri bana gonder.
popd
pause
exit /b 1
