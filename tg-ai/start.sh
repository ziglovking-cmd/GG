#!/bin/sh
# Serv00 / VPS: поднять bot.py, если ещё не запущен
set -e
DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
cd "$DIR"

# virtualenv Serv00, если есть
if [ -x "$HOME/.virtualenvs/tgbot/bin/python" ]; then
  PY="$HOME/.virtualenvs/tgbot/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY=$(command -v python3)
else
  PY=python
fi

# уже жив?
if pgrep -f "$DIR/bot.py" >/dev/null 2>&1; then
  exit 0
fi

mkdir -p "${DATA_DIR:-.}"
# polling: WEBHOOK_URL в .env должен быть пустым
nohup "$PY" "$DIR/bot.py" >> "$DIR/bot.log" 2>&1 &
echo "started $! with $PY"
