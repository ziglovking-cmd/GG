# Home24 на сервере Ubuntu

Сервер: Ubuntu, вход `root@<IP сервера>`. Бот ставится в `/opt/home24` и работает как служба `home24`.

## 1. С компьютера (PowerShell, в папке бота)

```powershell
scp .\home24-project-v10-2026-11-10.zip root@<IP>:/root/home24.zip
scp -r .\data root@<IP>:/root/data
scp .\.env root@<IP>:/root/home24.env
```

`data` с компьютера несёт базу контактов, историю, `managers.json` и сохранённую сессию Telegram — без неё на сервере придётся входить в аккаунт заново.

## 2. На сервере

```bash
ssh root@<IP>
passwd                      # сразу сменить пароль root
cd /root && unzip -o -q home24.zip deploy/install_ubuntu.sh
bash deploy/install_ubuntu.sh /root/home24.zip
```

Скрипт ставит Python, пакеты, проверяет сборку и 48 диалогов, создаёт службу. Сам бот не запускает.

## 3. Переезд

1. На компьютере остановить бота: закрыть окна, в Диспетчере задач завершить `python`, выключить автозапуск (`uninstall_autostart.bat`).
2. На сервере: `systemctl start home24`
3. В Telegram боту: `/script` → «Сборка бота: v10 · 10.11.2026», папка `/opt/home24`.

Одна сессия Telegram в двух местах сразу — риск, что Telegram её сбросит. Поэтому сначала стоп на компьютере, потом старт на сервере.

## Обновление потом

```bash
scp .\home24-новый.zip root@<IP>:/root/home24.zip     # с компьютера
bash /opt/home24/deploy/install_ubuntu.sh /root/home24.zip   # на сервере; data и .env не трогает
systemctl start home24
```

## Команды

| Что | Команда |
|---|---|
| статус | `systemctl status home24` |
| лог | `tail -f /opt/home24/logs/bot.log` |
| перезапуск | `systemctl restart home24` |
| стоп | `systemctl stop home24` |
| стереть историю с гостем | `cd /opt/home24 && systemctl stop home24 && .venv/bin/python scripts/reset_contact.py 8996… --yes && systemctl start home24` |
| прогон диалогов с Groq | `cd /opt/home24 && .venv/bin/python scripts/eval_home24_dialogs.py` |
