import os, json, time, sqlite3, logging, io, zipfile, re, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ['BOT_TOKEN']
OWNER = int(os.environ['OWNER_ID'])
KEY = os.environ['AI_API_KEY']
BASE = os.getenv('AI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
MODEL = os.getenv('AI_MODEL', 'gpt-4o-mini')
DATA_DIR = os.getenv('DATA_DIR', '.')
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'bot.sqlite3')
WEBHOOK_URL = (os.getenv('WEBHOOK_URL') or '').rstrip('/')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET') or TOKEN.split(':')[-1][:32]
PORT = int(os.getenv('PORT', '8080'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
db = sqlite3.connect(DB_PATH, check_same_thread=False)
_run_lock = threading.Lock()
db.executescript('''
create table if not exists chats(
  c text, k integer, onoff integer default 0, mode text default 'me',
  primary key(c,k)
);
create table if not exists msgs(
  c text, k integer, m integer, role text, t text,
  primary key(c,k,m)
);
create table if not exists examples(k integer, peer text, answer text);
create table if not exists state(id integer primary key, v integer);
create table if not exists settings(key text primary key, val text);
''')
# миграция старых баз без колонки mode
cols = {r[1] for r in db.execute('pragma table_info(chats)')}
if 'mode' not in cols:
    db.execute("alter table chats add column mode text default 'me'")
    db.commit()

RATE_SEC = 8
_last_reply = {}

# пресеты: короткое имя → инструкция режима (голос всё равно берём у владельца)
MODES = {
    'me': (
        'как_я',
        'Режим СТАРОГО/обычного чата: отвечай ровно как владелец в ЭТОЙ переписке. '
        'Никаких новых ролей, подкатов и «делового тона», если их нет в истории.',
    ),
    'podkat': (
        'подкат',
        'Режим новых знакомств/девочек: лёгкий флирт, подкаты, интерес к человеку, '
        'игра, лёгкий юмор. Не пошло и не токсично. Не дави. Коротко, живо, как в переписке, '
        'не как пикап-коуч. Цель — завязать разговор и держать искру.',
    ),
    'work': (
        'работа',
        'Рабочий/деловой чат: коротко, по делу, вежливо, без флирта и сленга «для своих». '
        'Без воды. Если чего-то не знаешь по фактам работы — SKIP.',
    ),
    'friend': (
        'друг',
        'Свой/друг: тепло, просто, можно сленг и мемы как у владельца. Без подкатов и без официоза.',
    ),
    'cold': (
        'холод',
        'Холодно/минимум: очень коротко, сухо, без эмодзи и без инициативы. Можно игнорить мелкий флуд смыслом «ок/угу».',
    ),
}
MODE_ALIASES = {
    'me': 'me', 'как_я': 'me', 'как-я': 'me', 'я': 'me', 'старый': 'me', 'old': 'me',
    'podkat': 'podkat', 'подкат': 'podkat', 'подкаты': 'podkat',
    'флирт': 'podkat', 'дев': 'podkat', 'девушка': 'podkat', 'девочки': 'podkat', 'pickup': 'podkat',
    'work': 'work', 'работа': 'work', 'дел': 'work', 'бизнес': 'work',
    'friend': 'friend', 'друг': 'friend', 'свои': 'friend', 'друзей': 'friend',
    'cold': 'cold', 'холод': 'cold', 'сухо': 'cold', 'игнор': 'cold',
}


def mode_key(name: str):
    n = (name or '').strip().lower().replace('ё', 'е')
    return MODE_ALIASES.get(n)


def mode_label(key_or_custom: str) -> str:
    if key_or_custom in MODES:
        return MODES[key_or_custom][0]
    if key_or_custom.startswith('custom:'):
        return 'свой'
    return key_or_custom


def mode_instruction(mode: str) -> str:
    if mode in MODES:
        return MODES[mode][1]
    if mode.startswith('custom:'):
        return 'Свой режим от владельца: ' + mode[7:][:500]
    return MODES['me'][1]


def get_setting(key, default=''):
    row = db.execute('select val from settings where key=?', (key,)).fetchone()
    return row[0] if row else default


def set_setting(key, val):
    with db:
        db.execute('insert or replace into settings values(?,?)', (key, val))


def tg(method, **data):
    r = requests.post(f'https://api.telegram.org/bot{TOKEN}/{method}', json=data, timeout=45)
    j = r.json()
    if not j.get('ok'):
        raise RuntimeError(method + ' ' + str(j.get('error_code')))
    return j['result']


def admin(s):
    tg('sendMessage', chat_id=OWNER, text=s[:4000])


def text_of(x):
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return ''.join(z if isinstance(z, str) else z.get('text', '') for z in x)
    return ''


def user_id_of(from_id):
    if isinstance(from_id, str):
        m = re.match(r'user(\d+)$', from_id)
        return int(m.group(1)) if m else None
    if isinstance(from_id, dict) and from_id.get('type') == 'user':
        try:
            return int(from_id.get('user_id'))
        except (TypeError, ValueError):
            return None
    return None


def load_export_json(raw: bytes):
    if len(raw) >= 2 and raw[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith('.json') and not n.endswith('/')]
            prefer = [n for n in names if n.lower().endswith('result.json')]
            pick = prefer[0] if prefer else (names[0] if names else None)
            if not pick:
                raise ValueError('no json in zip')
            raw = zf.read(pick)
    return json.loads(raw.decode('utf-8-sig'))


def is_skip(ans: str) -> bool:
    s = ans.strip()
    if not s:
        return True
    return re.fullmatch(r'SKIP[.!]?', s, flags=re.I) is not None


def style_notes(owner_lines):
    lines = [t.strip() for t in owner_lines if t and t.strip()]
    if not lines:
        return 'Голоса владельца в этом чате мало — держи короткие фразы, без «помощнического» тона.'
    lengths = [len(t) for t in lines]
    avg = sum(lengths) / len(lengths)
    lower = sum(1 for t in lines if t[:1].islower()) / len(lines)
    emoji = sum(1 for t in lines if re.search(
        r'[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F600-\U0001F64F]', t)) / len(lines)
    excl = sum(1 for t in lines if '!' in t) / len(lines)
    q = sum(1 for t in lines if '?' in t) / len(lines)
    samples = ' | '.join(repr(t[:120]) for t in lines[-10:])
    return (
        f'Средняя длина ≈{avg:.0f} симв.; с маленькой буквы: {lower:.0%}; '
        f'эмодзи: {emoji:.0%}; !: {excl:.0%}; ?: {q:.0%}. '
        f'Эталон фраз: {samples}'
    )


def build_dialogue(hist):
    out = []
    for role, t in hist:
        if role == 'peer':
            who = 'Собеседник'
        elif role == 'owner':
            who = 'Я'
        else:
            who = 'Автоответ (не эталон стиля)'
        out.append(f'{who}: {t}')
    return '\n'.join(out)


def fewshot_block(ex):
    if not ex:
        return 'Примеров нет.'
    return '\n\n'.join(f'Собеседник: {p}\nЯ: {a}' for p, a in ex)


def ask_ai(hist, ex, owner_lines, mode: str, is_old_chat: bool):
    """Старый чат → как я по истории. Новый + режим → режим, но голосом владельца."""
    if is_old_chat and mode == 'me':
        focus = (
            'Это СТАРЫЙ чат с историей. Сначала быстро прочитай переписку. '
            'Ответь как «Я» в ЭТОМ чате: тот же тон к этому человеку, те же привычки.'
        )
    elif is_old_chat:
        focus = (
            'Чат уже не новый: в приоритете реальная история и тон к этому человеку. '
            'Режим ниже — мягкая рамка (не ломай уже сложившийся стиль общения в переписке).'
        )
    else:
        focus = (
            'Это НОВЫЙ или почти новый чат. Истории мало — веди разговор по РЕЖИМУ ниже, '
            'но лексикой/длиной/пунктуацией как у владельца (если есть образцы).'
        )

    system = (
        'Ты пишешь личные сообщения от первого лица за владельца. Не ассистент.\n'
        f'{focus}\n'
        f'Режим чата: {mode_label(mode)}\n{mode_instruction(mode)}\n\n'
        'Правила:\n'
        '- Копируй длину, сленг, регистр, опечатки, эмодзи владельца.\n'
        '- Не пиши «правильнее» владельца. Без списков и дисклеймеров.\n'
        '- Не выдумывай факты, встречи, деньги, коды, согласие. Иначе только SKIP.\n'
        '- На «ты бот?» — честно коротко; иначе автоматизацию не пали.\n'
        '- Выведи ТОЛЬКО текст сообщения, без «Я:» и без кавычек.'
    )
    user_payload = (
        '=== Голос владельца ===\n' + style_notes(owner_lines) + '\n\n'
        '=== Примеры пар ===\n' + fewshot_block(ex) + '\n\n'
        '=== История этого чата (прочитай быстро) ===\n'
        + build_dialogue(hist) + '\n\n'
        'Ответь на последнее сообщение Собеседника одним сообщением.'
    )
    r = requests.post(
        BASE + '/chat/completions',
        headers={'Authorization': 'Bearer ' + KEY},
        json={
            'model': MODEL,
            'temperature': 0.7 if mode == 'podkat' else 0.55,
            'presence_penalty': 0.3 if mode == 'podkat' else 0.15,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user_payload},
            ],
        },
        timeout=45,
    )
    r.raise_for_status()
    choices = r.json().get('choices') or []
    if not choices:
        raise RuntimeError('empty choices')
    return (choices[0].get('message') or {}).get('content', '').strip()[:4000]


def import_examples(k, data):
    if int(data.get('id', -1)) != k:
        raise ValueError('chat id mismatch')
    pairs = []
    prev = ''
    for z in data.get('messages') or []:
        if z.get('type') != 'message':
            continue
        s = text_of(z.get('text', ''))[:1600]
        uid = user_id_of(z.get('from_id'))
        if uid == OWNER and prev and s:
            pairs.append((k, prev, s))
        prev = s if uid == k else ''
    if not pairs:
        raise ValueError('no pairs')
    with db:
        db.execute('delete from examples where k=?', (k,))
        db.executemany('insert into examples values(?,?,?)', pairs[-80:])
    return len(pairs)


def trim_msgs(c, k, keep=60):
    rows = db.execute(
        'select m from msgs where c=? and k=? order by m desc limit ?', (c, k, keep)
    ).fetchall()
    if not rows:
        return
    keep_ids = {m for (m,) in rows}
    all_ids = [m for (m,) in db.execute('select m from msgs where c=? and k=?', (c, k))]
    for m in all_ids:
        if m not in keep_ids:
            db.execute('delete from msgs where c=? and k=? and m=?', (c, k, m))


def help_text():
    presets = ', '.join(f'{v[0]} ({k})' for k, v in MODES.items())
    d = get_setting('default_mode', 'me')
    return (
        '/chats — чаты (вкл/выкл + режим)\n'
        '/on ID · /off ID\n'
        f'/mode ID имя — режим чата\n'
        f'/mode ID свой текст... — свой режим\n'
        f'/default имя — режим для НОВЫХ чатов (сейчас: {mode_label(d)})\n'
        f'Пресеты: {presets}\n'
        'Экспорт JSON/ZIP + ID в подписи — натаскать стиль «как я».'
    )


def handle_owner_message(m):
    a = m.get('text', '').split()
    d = m.get('document')
    if d:
        try:
            cap = (m.get('caption') or '').strip()
            if not cap.isdigit():
                raise ValueError('caption')
            k = int(cap)
            if not db.execute('select 1 from chats where k=?', (k,)).fetchone():
                raise ValueError('unknown chat')
            size = d.get('file_size')
            if size is not None and size > 8_000_000:
                raise ValueError('too big')
            f = tg('getFile', file_id=d['file_id'])
            r = requests.get(
                f"https://api.telegram.org/file/bot{TOKEN}/" + f['file_path'], timeout=40
            )
            r.raise_for_status()
            n = import_examples(k, load_export_json(r.content))
        except Exception:
            admin(
                'Не удалось импортировать. Нужен JSON/ZIP одного известного чата до 8 МБ, '
                'ID в подписи и пары входящее → твой ответ.'
            )
            return
        admin('Загружено пар: ' + str(min(80, n)))
        return

    if not a:
        admin(help_text())
        return

    cmd = a[0].lower()

    if cmd == '/chats':
        rows = list(db.execute(
            'select k,onoff,coalesce(mode,"me") from chats order by rowid desc limit 100'
        ))
        if not rows:
            admin('Пока нет чатов')
            return
        lines = []
        for k, v, mode in rows:
            lines.append(f'{k}: ' + ('вкл' if v else 'выкл') + f' · {mode_label(mode)}')
        admin('\n'.join(lines))
        return

    if cmd in ('/on', '/off') and len(a) == 2 and a[1].isdigit():
        with db:
            cur = db.execute(
                'update chats set onoff=? where k=?',
                (int(cmd == '/on'), int(a[1])),
            )
        admin('Готово' if cur.rowcount else 'Чат ещё не обнаружен')
        return

    if cmd == '/default':
        if len(a) < 2:
            admin('Сейчас для новых: ' + mode_label(get_setting('default_mode', 'me')))
            return
        key = mode_key(a[1])
        if not key:
            admin('Неизвестный пресет. /default подкат|работа|друг|холод|как_я')
            return
        set_setting('default_mode', key)
        admin('Новым чатам режим: ' + MODES[key][0])
        return

    if cmd == '/mode' and len(a) >= 2 and a[1].isdigit():
        k = int(a[1])
        if not db.execute('select 1 from chats where k=?', (k,)).fetchone():
            admin('Чат ещё не обнаружен')
            return
        if len(a) == 2:
            mode = db.execute(
                'select coalesce(mode,"me") from chats where k=? limit 1', (k,)
            ).fetchone()[0]
            admin(f'Чат {k}: режим {mode_label(mode)}')
            return
        key = mode_key(a[2])
        if key:
            new_mode = key
        else:
            # свой режим: /mode ID текст...
            custom = m.get('text', '').split(None, 2)
            if len(custom) < 3 or not custom[2].strip():
                admin('Укажи пресет или свой текст: /mode ID подкат')
                return
            new_mode = 'custom:' + custom[2].strip()[:500]
        with db:
            db.execute('update chats set mode=? where k=?', (new_mode, k))
        admin(f'Чат {k}: режим {mode_label(new_mode)}')
        return

    admin(help_text())


def run(u):
    if 'message' in u:
        m = u['message']
        if m['chat']['id'] != OWNER or m.get('from', {}).get('id') != OWNER:
            return
        handle_owner_message(m)
        return

    m = u.get('business_message')
    if not m or m['chat']['type'] != 'private' or m.get('sender_business_bot'):
        return
    c = m['business_connection_id']
    k = m['chat']['id']
    s = m.get('text')
    mid = m['message_id']
    own = m.get('from', {}).get('id') == OWNER
    if k == OWNER:
        return

    if not db.execute('select 1 from chats where c=? and k=?', (c, k)).fetchone():
        conn = tg('getBusinessConnection', business_connection_id=c)
        if conn['user']['id'] != OWNER or not conn['is_enabled']:
            return
        default_mode = get_setting('default_mode', 'me')
        if default_mode not in MODES:
            default_mode = 'me'
        with db:
            db.execute(
                'insert into chats(c,k,mode) values(?,?,?)',
                (c, k, default_mode),
            )
        admin(
            f"Новый чат: {m['chat'].get('first_name', '')} ({k}). "
            f"Автоответы выкл. Режим: {mode_label(default_mode)}. "
            f"Сменить: /mode {k} подкат|работа|друг|как_я"
        )

    if not s:
        return

    with db:
        cur = db.execute(
            'insert or ignore into msgs values(?,?,?,?,?)',
            (c, k, mid, 'owner' if own else 'peer', s[:3000]),
        )
        fresh = cur.rowcount
        trim_msgs(c, k, keep=60)

    row = db.execute(
        'select onoff, coalesce(mode,"me") from chats where c=? and k=?', (c, k)
    ).fetchone()
    if not fresh or own or time.time() - m['date'] > 300 or not row or not row[0]:
        return

    now = time.time()
    if now - _last_reply.get(k, 0) < RATE_SEC:
        return

    mode = row[1] or 'me'
    hist = list(reversed(db.execute(
        'select role,t from msgs where c=? and k=? order by m desc limit 28', (c, k)
    ).fetchall()))
    ex = db.execute(
        'select peer,answer from examples where k=? order by rowid desc limit 20', (k,)
    ).fetchall()
    owner_in_chat = [t for role, t in hist if role == 'owner']
    # «старый» = уже есть живая переписка владельца или импорт примеров
    is_old = len(owner_in_chat) >= 3 or len(ex) >= 5
    owner_lines = owner_in_chat + [a for _, a in ex]
    # для новых без своих фраз подтянем чужие эталоны голоса (другие чаты), только лексика
    if len(owner_lines) < 4:
        owner_lines += [
            t for (t,) in db.execute(
                "select t from msgs where role='owner' order by rowid desc limit 12"
            )
        ]

    try:
        ans = ask_ai(hist, ex, owner_lines, mode, is_old)
    except Exception:
        admin(f'AI не ответил для чата {k}. Проверь ключ/баланс/модель.')
        return

    if is_skip(ans):
        admin(f'Нужен твой ответ в чате {k}')
        return

    sent = tg('sendMessage', business_connection_id=c, chat_id=k, text=ans)
    _last_reply[k] = now
    with db:
        db.execute(
            'insert or ignore into msgs values(?,?,?,?,?)',
            (c, k, sent['message_id'], 'bot', ans),
        )


def safe_run(u):
    try:
        with _run_lock:
            run(u)
    except Exception as e:
        logging.warning('Ошибка обновления %s: %s', u.get('update_id'), type(e).__name__)
        try:
            admin(
                'Не удалось обработать событие. Проверь баланс и модель API, '
                'сеть и права Telegram Business. Повторной отправки не будет.'
            )
        except Exception:
            pass


def run_polling():
    tg('deleteWebhook', drop_pending_updates=False)
    logging.info('Polling на %s', DB_PATH)
    while True:
        try:
            row = db.execute('select v from state where id=1').fetchone()
            updates = tg(
                'getUpdates',
                offset=row[0] if row else 0,
                timeout=25,
                allowed_updates=['message', 'business_message'],
            )
            for u in updates:
                safe_run(u)
                with db:
                    db.execute('insert or replace into state values(1,?)', (u['update_id'] + 1,))
        except Exception as e:
            logging.warning('Ошибка polling: %s', type(e).__name__)
            time.sleep(5)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        logging.info('%s ' + fmt, self.address_string(), *args)

    def _send(self, code, body=b'ok', ctype='text/plain; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ('/', '/health', '/healthz'):
            self._send(200, b'ok')
        else:
            self._send(404, b'not found')

    def do_POST(self):
        # /telegram/<secret>
        parts = self.path.split('?', 1)[0].rstrip('/').split('/')
        if len(parts) != 3 or parts[1] != 'telegram' or parts[2] != WEBHOOK_SECRET:
            self._send(403, b'forbidden')
            return
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b'{}'
        try:
            u = json.loads(raw.decode('utf-8'))
        except Exception:
            self._send(400, b'bad json')
            return
        self._send(200, b'ok')
        threading.Thread(target=safe_run, args=(u,), daemon=True).start()


def run_webhook():
    url = f'{WEBHOOK_URL}/telegram/{WEBHOOK_SECRET}'
    args = dict(
        url=url,
        allowed_updates=['message', 'business_message'],
        drop_pending_updates=False,
    )
    if re.fullmatch(r'[A-Za-z0-9_-]{1,256}', WEBHOOK_SECRET or ''):
        args['secret_token'] = WEBHOOK_SECRET
    tg('setWebhook', **args)
    logging.info('Webhook → %s (db %s)', url, DB_PATH)
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


if __name__ == '__main__':
    if WEBHOOK_URL:
        run_webhook()
    else:
        run_polling()
