@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set HOME24_NO_QR=1
set USE_PROXY=0

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python не найден в PATH. Установите Python 3.11 x64 и отметьте "Add to PATH".
  pause
  exit /b 1
)

if not exist "logs" mkdir "logs"

echo [%date% %time%] Home24 bot start (cwd=%cd%)>> "logs\bot.log"
echo Home24 bot. Лог: logs\bot.log
echo Рассылка на старте НЕ запускается. Остановка: Ctrl+C в этом окне.

:loop
python -m bot >> "logs\bot.log" 2>&1
set ERR=%ERRORLEVEL%
echo [%date% %time%] bot exited code=%ERR%, restart in 5s>> "logs\bot.log"
echo Бот упал (код %ERR%), перезапуск через 5 сек...
timeout /t 5 /nobreak >nul
goto loop
