@echo off
title CANASAN AI - Servidor
cd /d "%~dp0"
color 0B
echo.
echo  ============================================
echo   CANASAN AI - Prediccion de cierre de ventas
echo   http://127.0.0.1:8000
echo  ============================================
echo.
echo  Iniciando servidor (puede tardar unos segundos)...

if not exist "storage" mkdir storage
start "CANASAN AI - Servidor" /min cmd /c "python run.py"

set /a intentos=0
:espera
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "try { $r = Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -TimeoutSec 2 -UseBasicParsing; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto listo
set /a intentos+=1
if %intentos% geq 60 goto fallo
goto espera

:listo
echo  Servidor listo. Abriendo el navegador...
start "" "http://127.0.0.1:8000"
timeout /t 3 >nul
exit /b 0

:fallo
echo.
echo  ERROR: el servidor no respondio en 2 minutos.
echo  Mire la ventana "CANASAN AI - Servidor" para ver el error.
echo  Cierre y vuelva a intentar.
pause
exit /b 1
