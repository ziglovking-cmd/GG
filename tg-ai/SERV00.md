# Serv00 — бот 24/7 без карты

## 1. Рега

1. https://www.serv00.com → Register  
2. Вопрос про cost of hosting → пиши **`free`**  
3. Жди письмо / активацию (иногда сутки+)  
4. Зайди в панель (в письме будет `panelX.serv00.com`)

## 2. В панели обязательно

1. Смени язык на English (если надо): сверху язык  
2. **Additional services → Run your own applications → Enabled**  
   Без этого скрипты не запустятся.  
3. Запомни: **Login**, **пароль**, адрес SSH (типа `sX.serv00.com`)

## 3. SSH

С компа (PowerShell / Терминал):

```bash
ssh ТВОЙ_ЛОГИН@sX.serv00.com
```

(точный хост — в панели / письме)

## 4. Поставь бота (копируй по блокам)

```bash
# права на свои программы уже Enabled
mkdir -p ~/.virtualenvs ~/tg-ai
cd ~/.virtualenvs
virtualenv -p python3.12 tgbot
source ~/.virtualenvs/tgbot/bin/activate

cd ~
git clone https://github.com/ziglovking-cmd/GG.git
cp -r ~/GG/tg-ai/* ~/tg-ai/
cd ~/tg-ai
pip install -r requirements.txt

cp .env.example .env
nano .env
```

В `.env` так (остальное можно не трогать):

```
BOT_TOKEN=токен_от_BotFather
OWNER_ID=твой_числовой_id
AI_API_KEY=AIza_ключ_gemini
AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
AI_MODEL=gemini-2.0-flash
WEBHOOK_URL=
DATA_DIR=.
```

Сохрани в nano: `Ctrl+O`, Enter, `Ctrl+X`.

## 5. Первый запуск

```bash
cd ~/tg-ai
source ~/.virtualenvs/tgbot/bin/activate
chmod +x start.sh
./start.sh
tail -f bot.log
```

Должно быть что-то вроде `Polling на ...`. `Ctrl+C` только выйдет из лога, бот продолжит работать.

Проверка в Telegram: напиши боту `/chats`.

## 6. Cron — чтобы сам поднимался

В панели: **Cron jobs → Add cron job**

- Frequency: каждые **5 минут** (или `*/5 * * * *`)  
- Command:

```bash
/usr/home/ТВОЙ_ЛОГИН/tg-ai/start.sh
```

Подставь свой логин вместо `ТВОЙ_ЛОГИН`.  
Путь обычно `/usr/home/ЛОГИН/...` — проверь: `echo $HOME`.

Либо из SSH:

```bash
crontab -e
```

строка:

```
*/5 * * * * /usr/home/ТВОЙ_ЛОГИН/tg-ai/start.sh
```

## 7. Чтобы аккаунт не слили

Раз в **≤3 месяца** зайди в панель или по SSH. Иначе Serv00 может удалить аккаунт.

## Если не стартует

```bash
cd ~/tg-ai
source ~/.virtualenvs/tgbot/bin/activate
python bot.py
```

Смотри ошибку в терминале / `bot.log`. Частые:
- не включил **Run your own applications**
- пустой/кривой `.env`
- Gemini ключ неверный
- `git` нет → качай zip с GitHub и `scp` на сервер
