@echo off
cd /d "%~dp0"
rem Doppio clic per avviare il Diario del Ricercatore su Windows (si apre nel browser).
rem Serve Python 3: https://www.python.org/downloads/windows/ (spunta Add python.exe to PATH).

where py >nul 2>nul
if %errorlevel%==0 goto usapy
where python >nul 2>nul
if %errorlevel%==0 goto usapython

echo.
echo Python 3 non trovato.
echo Installalo da https://www.python.org/downloads/windows/
echo e spunta "Add python.exe to PATH" durante l'installazione.
echo.
pause
exit /b 1

:usapy
py -3 diario_web.py
goto fine

:usapython
python diario_web.py

:fine
echo.
echo Il Diario si e' fermato. Se vedi un errore qui sopra, copia il testo.
pause
