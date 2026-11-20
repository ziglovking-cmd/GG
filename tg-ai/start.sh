#!/bin/sh
# Для Serv00 / VPS: перезапуск если процесс умер
cd "$(dirname "$0")"
mkdir -p "${DATA_DIR:-.}"
if pgrep -f "python3? bot.py" >/dev/null 2>&1; then
  exit 0
fi
nohup python3 bot.py >> bot.log 2>&1 &
echo "started pid $!"
