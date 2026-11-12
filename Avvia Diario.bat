@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Doppio clic per avviare il Diario del Ricercatore. Si apre nel browser.
rem Se Python non c'e', prova a installarlo da solo (serve internet, ~2 minuti, una volta sola).

set "PY="
where py >nul 2>nul && py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && python --version >nul 2>nul && set "PY=python"
)
if not defined PY goto cercalocale
goto avvia

:cercalocale
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY="%%D\python.exe""
if defined PY goto avvia

echo.
echo ===============================================
echo   Per funzionare il Diario ha bisogno di Python.
echo   Lo installo io adesso, non devi fare nulla.
echo   Attendi qualche minuto...
echo ===============================================
echo.
where winget >nul 2>nul
if errorlevel 1 goto manuale
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY="%%D\python.exe""
if defined PY goto avvia

:manuale
echo.
echo Non sono riuscito a installare Python da solo.
echo Si aprira' la pagina di download: scarica, apri il file e
echo SPUNTA la casella "Add python.exe to PATH", poi premi Install Now.
echo Finito, fai di nuovo doppio clic su "Avvia Diario".
start https://www.python.org/downloads/windows/
echo.
pause
exit /b 1

:avvia
%PY% diario_web.py
if errorlevel 1 (
  echo.
  echo Qualcosa non ha funzionato. Copia il testo qui sopra e mandalo a chi ti ha dato il Diario.
  pause
  exit /b 1
)
rem Tutto ok: il Diario e' partito in background, questa finestra si chiude da sola.
timeout /t 3 >nul
exit /b 0
