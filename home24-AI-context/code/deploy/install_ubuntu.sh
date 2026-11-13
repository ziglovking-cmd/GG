#!/usr/bin/env bash
# Home24 bot — установка на Ubuntu-сервер (systemd).
# Запуск на сервере под root:
#   bash install_ubuntu.sh /root/home24.zip
# Перед этим скопируйте с компьютера (см. deploy/README_SERVER.md):
#   /root/home24.zip  — архив проекта
#   /root/data/       — папка data с ПК (база, контакты, сессия Telegram, managers.json)
#   /root/home24.env  — файл .env с ПК
set -euo pipefail

ZIP="${1:-/root/home24.zip}"
APP_DIR="${APP_DIR:-/opt/home24}"

[ -f "$ZIP" ] || { echo "Нет архива $ZIP"; exit 1; }

echo "== Пакеты"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip unzip

echo "== Код в $APP_DIR"
mkdir -p "$APP_DIR"
if systemctl is-active --quiet home24 2>/dev/null; then
  echo "Останавливаю работающий home24"
  systemctl stop home24
fi
unzip -o -q "$ZIP" -d "$APP_DIR"

if [ -d /root/data ] && [ ! -f "$APP_DIR/data/home24.db" ]; then
  echo "== Переношу data с ПК"
  cp -a /root/data "$APP_DIR/"
fi
if [ -f /root/home24.env ]; then
  echo "== Переношу .env с ПК"
  cp /root/home24.env "$APP_DIR/.env"
fi
mkdir -p "$APP_DIR/logs" "$APP_DIR/data"
chmod 600 "$APP_DIR/.env" 2>/dev/null || true

echo "== Python-окружение"
cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip -q
if ! pip install -q -r requirements.txt; then
  echo "Точные версии не встали на этот Python ($(python -V)), ставлю основные пакеты"
  pip install -q Telethon openai python-dotenv httpx aiohttp qrcode pillow tzdata psutil PySocks python-socks
fi

echo "== Проверка"
PYTHONUTF8=1 python -c "from bot.version import BUILD; print('Сборка:', BUILD)"
PYTHONUTF8=1 python scripts/eval_home24_dialogs.py --offline --out /tmp/home24_dialogs.md | tail -1

echo "== Служба systemd"
cat > /etc/systemd/system/home24.service <<EOF
[Unit]
Description=Home24 Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m bot
Environment=PYTHONUTF8=1
Environment=PYTHONIOENCODING=utf-8
Environment=HOME24_NO_QR=1
Environment=USE_PROXY=0
Environment=TZ=Europe/Moscow
Restart=always
RestartSec=5
StandardOutput=append:$APP_DIR/logs/bot.log
StandardError=append:$APP_DIR/logs/bot.log

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable home24 >/dev/null

echo
echo "Готово. Бот НЕ запущен специально."
echo "1) Остановите бота на компьютере (одна сессия Telegram не должна работать в двух местах)."
echo "2) Запуск:   systemctl start home24"
echo "   Статус:   systemctl status home24"
echo "   Лог:      tail -f $APP_DIR/logs/bot.log"
