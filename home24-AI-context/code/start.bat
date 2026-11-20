@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set HOME24_WEB_LOGIN=1
set HOME24_NO_QR=1
set USE_PROXY=0

if not exist "logs" mkdir "logs"

REM Python: PATH, затем типичный путь Gleb / Local
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY (
  if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    set "PY=%LocalAppData%\Programs\Python\Python311\python.exe"
  )
)
if not defined PY (
  if exist "[REDACTED]\AppData\Local\Programs\Python\Python311\python.exe" (
    set "PY=[REDACTED]\AppData\Local\Programs\Python\Python311\python.exe"
  )
)
if not defined PY (
  echo [ERROR] Python 3.11 не найден. Установите с python.org и отметьте Add to PATH.
  echo Либо поправьте путь PY в start.bat
  pause
  exit /b 1
)

echo Home24. Python: %PY%
echo Лог: logs\bot.log
echo На странице входа сначала выберите менеджера, затем Telegram Desktop.
echo.

:loop
"%PY%" run_home24.py
set ERR=%ERRORLEVEL%

if "%ERR%"=="42" (
  echo.
  echo Сессия отозвана или отсутствует. Открываю страницу входа...
  echo [%date% %time%] SESSION_DEAD exit=42 >> "logs\bot.log"
  "%PY%" -m bot.web_login
  echo После успешного входа бот продолжит работу.
  goto loop
)

if "%ERR%"=="0" (
  echo Бот завершился штатно.
  goto end
)

echo [%date% %time%] bot exited %ERR%, restart in 8s >> "logs\bot.log"
echo Сбой (код %ERR%), перезапуск через 8 сек. Ctrl+C — стоп.
timeout /t 8 /nobreak >nul
goto loop

:end
pause
endlocal
