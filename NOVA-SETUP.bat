@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "LOG=%~dp0kurulum-log.txt"
echo === Nova v2 kurulum logu === > "%LOG%"
echo Tarih: %DATE% %TIME% >> "%LOG%"
title Nova v2 - Ortam Kurulumu

echo ============================================================
echo   Nova v2 - Python ortami kurulumu (teshisli)
echo ============================================================
echo.

set "PROJ="
if exist "%~dp0nova-v2\server.py" set "PROJ=%~dp0nova-v2"
if not defined PROJ if exist "%~dp0server.py" set "PROJ=%~dp0."
if not defined PROJ (
  echo [HATA] server.py bulunamadi.
  echo        Bu dosyayi "nova-v2" klasorunun yanina koy ya da icine at.
  echo        Simdiki konum: %~dp0
  echo.
  pause
  exit /b 1
)
echo Proje klasoru: %PROJ%
echo Proje klasoru: %PROJ% >> "%LOG%"
echo.

echo [1/5] Python araniyor...
set "PYEXE="
set "PYARG="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 (
  set "PYEXE=py"
  set "PYARG=-3"
)
if defined PYEXE goto :PYFOUND
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYEXE=python"
if defined PYEXE goto :PYFOUND
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
if defined PYEXE goto :PYFOUND
for /d %%D in ("C:\Python3*") do if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
if defined PYEXE goto :PYFOUND
goto :NOPY

:PYFOUND
echo       Bulundu: "%PYEXE%" %PYARG%
echo Python: "%PYEXE%" %PYARG% >> "%LOG%"
"%PYEXE%" %PYARG% --version
"%PYEXE%" %PYARG% --version >> "%LOG%" 2>&1
"%PYEXE%" %PYARG% -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)"
if errorlevel 1 (
  echo       [HATA] Python 3.10 veya uzeri gerekli.
  goto :NOPY
)
echo.

pushd "%PROJ%"

echo [2/5] venv olusturuluyor...
if exist ".venv\Scripts\python.exe" (
  echo       .venv zaten var, atlandi.
) else (
  "%PYEXE%" %PYARG% -m venv .venv
)
if not exist ".venv\Scripts\python.exe" goto :FAILVENV

echo [3/5] pip guncelleniyor...
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check
echo pip guncelleme cikis kodu: %ERRORLEVEL% >> "%LOG%"

echo [4/5] Bagimliliklar kuruluyor (birkac dakika surebilir)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto :FAILPIP

echo [5/5] Kontrol ediliyor...
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, anthropic; print('      Bagimliliklar tamam.')"
if errorlevel 1 goto :FAILPIP

echo.
echo ============================================================
echo  Kurulum basarili.
echo.
echo  Sunucuyu baslatmak icin:  NOVA-BASLAT.bat  (cift tikla)
echo  Yazarak:  cd /d "%PROJ%"
echo            .venv\Scripts\python -m uvicorn server:app --host 127.0.0.1 --port 5000
echo.
echo  Tarayici: http://localhost:5000
echo  Gercek model (opsiyonel): set ANTHROPIC_API_KEY=sk-ant-...
echo ============================================================
echo Basarili >> "%LOG%"
popd
echo.
pause
exit /b 0

:FAILVENV
echo.
echo [HATA] venv olusturulamadi.
echo        Cozum: Python'u resmi kurulumla yeniden kur (Add to PATH isaretli).
echo        https://www.python.org/downloads/windows/
echo venv basarisiz >> "%LOG%"
popd
pause
exit /b 1

:FAILPIP
echo.
echo [HATA] Bagimliliklar kurulamadi.
echo        En sik neden: internet/proxy. Kurumsal proxy varsa:
echo          set HTTPS_PROXY=http://kullanici:sifre@proxy:8080
echo        Sonra bu dosyayi tekrar calistir.
echo pip basarisiz >> "%LOG%"
popd
pause
exit /b 1

:NOPY
echo.
echo [HATA] Kullanilabilir Python bulunamadi.
echo.
echo  1) https://www.python.org/downloads/windows/ adresinden Python 3.12 indir
echo  2) Kurulumda "Add python.exe to PATH" kutusunu ISARETLE
echo  3) Bilgisayari yeniden baslat, bu dosyayi tekrar calistir
echo.
echo  Kontrol: cmd acip  py -3 --version  yaz. Surum gorunuyorsa Python hazir.
echo python bulunamadi >> "%LOG%"
type "%LOG%"
pause
exit /b 1
