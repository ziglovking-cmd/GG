@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LNK=%STARTUP%\Home24Bot.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%LNK%'); $s.TargetPath='%~dp0start.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
echo Ярлык автозапуска создан:
echo %LNK%
echo Чтобы убрать: uninstall_autostart.bat
pause
