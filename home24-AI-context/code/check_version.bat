@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Папка: %cd%
python -c "from bot.version import BUILD; print('Сборка в этой папке:', BUILD)"
python -c "from bot.phrases import is_consent; print('«Здравствуйте! Да» = согласие:', is_consent('Здравствуйте! Да'))"
echo.
echo Должно быть: Сборка v10 и «согласие: True».
echo Если бот в Telegram на /script показывает другую сборку или другую папку,
echo значит работает старая копия бота — остановите её и запустите run_windows.bat из ЭТОЙ папки.
pause
