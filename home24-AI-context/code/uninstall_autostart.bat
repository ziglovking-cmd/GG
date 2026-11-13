@echo off
chcp 65001 >nul
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Home24Bot.lnk"
if exist "%LNK%" (
  del /f /q "%LNK%"
  echo Автозапуск убран.
) else (
  echo Ярлыка не было.
)
pause
