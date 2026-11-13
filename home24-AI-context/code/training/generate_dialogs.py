# -*- coding: utf-8 -*-
"""Генератор эталонных диалогов Home24 (гость ↔ менеджер-бот) с разными исходами.

    python training/generate_dialogs.py            # → training/dialogs_home24.jsonl (+ sample.md, finetune.jsonl)
    python training/generate_dialogs.py --n 1500 --seed 7

Ответы «бота» здесь — эталон, а не то, что бот отвечает сейчас. Тексты берутся из кода бота
(phrases.py, life.py, smart.py, faq.py), то есть из script.md, поэтому набор не расходится со скриптом.
Карточки квартир не выдумываются: на их месте маркер [КАРТОЧКИ] — система подставит каталог.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

from bot import phrases as P  # noqa: E402

CARDS = "[КАРТОЧКИ: 2–3 квартиры из каталога под даты, гостей и район]"
HANDOFF = P.HANDOFF_LINE
OUT_DIR = ROOT / "training"

# ─────────────────────────── банки фраз гостя ───────────────────────────

NAMES = ["Мария", "Алексей", "Ольга", "Дмитрий", "Анна", "Сергей", "Екатерина", "Игорь", "Наталья",
         "Павел", "Юлия", "Андрей", "Светлана", "Роман", "Ирина", "Максим", "Татьяна", "Артём", "Елена", "Кирилл"]

# (как пишет гость, как бот повторяет)
DATES: list[tuple[str, str]] = [
    ("с 12 по 15 декабря", "С 12 по 15 декабря"),
    ("12-15 декабря", "С 12 по 15 декабря"),
    ("с 3 по 6 января", "С 3 по 6 января"),
    ("на выходные", "На выходные"),
    ("в эти выходные", "На эти выходные"),
    ("с пятницы по воскресенье", "С пятницы по воскресенье"),
    ("на новый год", "На Новый год"),
    ("с 30 декабря по 2 января", "С 30 декабря по 2 января"),
    ("с 5 января на 3 ночи", "С 5 января на 3 ночи"),
    ("20 ноября на неделю", "С 20 ноября на неделю"),
    ("завтра на сутки", "Завтра на сутки"),
    ("на сегодня", "На сегодня"),
    ("с 1 по 10 марта", "С 1 по 10 марта"),
    ("на майские", "На майские"),
    ("с 14 по 16 февраля", "С 14 по 16 февраля"),
    ("с 25 по 28 ноября", "С 25 по 28 ноября"),
    ("7.12-9.12", "С 7 по 9 декабря"),
    ("с 3 декабря на двое суток", "С 3 декабря на двое суток"),
    ("с 18 по 22 декабря", "С 18 по 22 декабря"),
    ("на 8 марта", "На 8 марта"),
    ("с 10 по 12 января", "С 10 по 12 января"),
    ("на следующие выходные", "На следующие выходные"),
    ("с понедельника по пятницу", "С понедельника по пятницу"),
    ("с 2 по 9 февраля", "С 2 по 9 февраля"),
]
DATES_UNKNOWN = ["пока не знаем", "даты ещё не знаю", "пока не определились", "не знаю пока", "точных дат нет"]

GUESTS: list[tuple[str, int]] = [
    ("двое", 2), ("нас трое", 3), ("я один", 1), ("одна", 1), ("4 человека", 4), ("мы с мужем", 2),
    ("с женой и ребёнком", 3), ("2 взрослых и ребёнок", 3), ("нас пятеро", 5), ("6 человек", 6),
    ("вдвоём", 2), ("3 взрослых", 3), ("двое взрослых и двое детей", 4), ("нас четверо, из них двое детей", 4),
    ("я с мамой", 2), ("компания 5 человек", 5), ("2", 2), ("3", 3), ("трое", 3), ("нас 4", 4),
]
GUESTS_IN_SENTENCE = [g for g in GUESTS if not g[0].isdigit()]
GUEST_WORD = {1: "один", 2: "двое", 3: "трое", 4: "четверо", 5: "пятеро", 6: "шестеро"}

DISTRICTS: list[tuple[str, str]] = [
    ("ближе к центру", "центр"), ("где потише", "тихий"), ("центр", "центр"), ("у метро, остальное неважно", "у метро"),
    ("в Коммунарке", "Коммунарка"), ("Нагатино", "Нагатино"), ("без разницы", "любой"),
    ("поближе к Бауманской", "Бауманская"), ("ближе к Ленинскому проспекту", "Ленинский проспект"),
    ("в Новой Москве", "Новая Москва"), ("спокойный район", "тихий"), ("неважно, главное у метро", "у метро"),
]

OPENERS_INBOUND = ["Здравствуйте", "Добрый день", "Добрый вечер", "Привет", "Здравствуйте!", "Доброе утро",
                   "здравствуйте, нужна квартира", "Добрый день, хочу снять квартиру", "Здравствуйте, есть свободные квартиры?",
                   "Подскажите, вы сдаёте квартиры посуточно?", "Хочу забронировать", "Здравствуйте, нужна квартира в Москве"]

PURPOSES: dict[str, dict[str, Any]] = {
    "командировка": {"say": ["еду в командировку", "приезжаю по работе", "командировка"],
                     "ask": ("нужны закрывающие документы", P.offer_facts and "Документы для отчёта сделаем. Напишите, что нужно.")},
    "лечение": {"say": ["приезжаем на лечение", "едем с мамой в клинику", "лечение в Москве"],
                "ask": ("нужно поближе к клинике", "Подскажите клинику или район, найду квартиру поближе.")},
    "ремонт": {"say": ["у нас дома ремонт", "на время ремонта", "делаем ремонт, негде жить"],
               "ask": ("месяц можно?", "Да, можно и на месяц, условия скажет менеджер.")},
    "отдых": {"say": ["приезжаем погулять по Москве", "хотим отдохнуть", "приезжаем на экскурсии"],
              "ask": None},
    "к родным": {"say": ["едем к родственникам", "приезжаем в гости к родным", "к сыну в гости"],
                 "ask": None},
    "романтика": {"say": ["хочу устроить сюрприз девушке", "годовщина свадьбы", "романтический вечер"],
                  "ask": ("а кино на проекторе правда есть?", "Да, можем подготовить романтический вечер с кино на проекторе.")},
    "праздник": {"say": ["хотим отметить день рождения", "девичник", "отмечаем юбилей"],
                 "ask": ("а украсить квартиру можно?", "Тихо отметить можно, и квартиру можем украсить.")},
    "фотосессия": {"say": ["нужна квартира для фотосессии", "фотосъёмка на пару часов"],
                   "ask": None},
}

# попутные вопросы: (тема, варианты вопроса, эталонный ответ без вопроса воронки)
SIDE: list[tuple[str, list[str], str]] = [
    ("питомцы", ["можно с собакой?", "а с котом можно?", "мы с собачкой маленькой, можно?"],
     "С питомцами можно не во всех квартирах. По вашей скажет менеджер."),
    ("парковка", ["есть парковка?", "мы на машине, где поставить?", "парковка есть?"],
     "Парковка зависит от дома, где-то двор, где-то городская рядом. По вашей квартире уточнит менеджер."),
    ("заезд", ["во сколько заезд?", "со скольки можно заселиться?", "когда заселение?"],
     "Заезд после 15:00, точное время зависит от квартиры."),
    ("выезд", ["до скольки выезд?", "во сколько надо выехать?"],
     "Выезд до 12:00. Позже иногда можно, зависит от квартиры."),
    ("вайфай", ["есть вайфай?", "интернет есть?", "какой пароль от вайфая?"],
     "Вайфай есть почти везде. Пароль будет в инструкции перед заездом, в чат пароли не отправляю."),
    ("курение", ["можно курить?", "курить в квартире можно?"],
     "В квартирах не курим. На балконе можно, если он есть и дом не против."),
    ("ранний заезд", ["можно заехать пораньше?", "можно заехать в 9 утра?", "ранний заезд возможен?"],
     "Ранний заезд иногда можно, если квартира свободна. Напишите время, менеджер проверит."),
    ("поздний выезд", ["можно выехать попозже?", "поздний выезд можно?"],
     "Поздний выезд иногда можно. Скажу, когда выберете квартиру."),
    ("кухня", ["есть кухня?", "можно готовить?", "посуда есть?"],
     "Кухня и посуда есть почти везде. Что именно есть, видно в описании."),
    ("залог", ["нужен залог?", "депозит берёте?", "залог какой?"], "Залог 2 000 ₽, во всех квартирах. Возвращаем после выезда, как только пройдёт клининг."),
    ("оплата", ["как оплатить?", "картой можно?", "оплата как?"],
     "Оплата картой онлайн или переводом. Менеджер всё пришлёт при брони."),
    ("ключи", ["как получить ключи?", "кто нас встретит?"], "Код или ключ пришлём перед заездом, заселение без встречи."),
    ("уборка", ["бельё чистое?", "уборка будет?"], "Перед каждым заездом уборка, чистое бельё и полотенца."),
    ("дети", ["с ребёнком можно?", "детская кроватка есть?"], "С детьми можно) Кроватку или стульчик уточню по квартире."),
    ("кофе", ["кофемашина есть?", "а кофе есть?"], "В каждой квартире есть кофемашина."),
    ("завтрак", ["завтрак входит?", "завтраки есть?"], "Завтрака нет, это квартира. Зато почти везде есть кухня и в каждой кофемашина."),
    ("трансфер", ["встретите из аэропорта?", "трансфер есть?"],
     "Трансфера нет. Удобнее всего на такси или аэроэкспрессе, дальше на метро."),
    ("паспорт", ["какие документы нужны?", "паспорт нужен?"],
     "При заселении нужен паспорт. Про регистрацию иностранцев скажет менеджер."),
    ("ночь", ["приедем ночью, можно?", "заселиться после полуночи можно?"],
     "Ночью заехать можно, код и инструкция будут заранее."),
    ("баллы", ["что за баллы?", "бонусы есть?"],
     "При прямой брони баллы: 500 за регистрацию, потом с каждого проживания. 1 балл = 1 ₽."),
    ("скидка", ["скидки есть?", "а дешевле можно?", "промокод есть?"],
     "Промокодов нет, но напрямую без комиссии агрегаторов. Плюс баллы при прямой брони, 500 за регистрацию."),
    ("по часам", ["можно на пару часов?", "почасово сдаёте?"], "Сдаём посуточно, по часам нет."),
    ("бассейн", ["бассейн есть?", "спа есть?"], "Бассейна и спа нет, у нас квартиры, не отель."),
    ("вечеринка", ["можно вечеринку?", "будет человек 10 вечером, норм?"],
     "Тихо отдохнуть можно, шумные вечеринки нет. Жить можно по числу спальных мест."),
    ("адрес Скандинавии", ["где Скандинавия?", "какое метро у Скандинавии?"],
     "«Скандинавия»: Фитарёвская улица, 17, Коммунарка, м. Коммунарка."),
    ("адрес Дюма", ["какой адрес у Дюма?", "где находится Дюма?"],
     "«Дюма»: Ленинский проспект, 38А, м. Ленинский проспект."),
    ("адрес Чехова", ["где Чехов?", "адрес Чехова какой?"],
     "«Чехов»: Балакиревский пер, 23, Басманный, м. Бауманская."),
]

PICKS = ["второй", "первый нравится", "давайте второй вариант", "третий", "давайте первую", "первый)"]
RETURNING = [("да, уже были", "да"), ("были в прошлом году", "да"), ("впервые", "нет"), ("нет, первый раз", "нет")]

LATER = ["я подумаю", "посоветуюсь с мужем и напишу", "подумаю и вернусь", "позже напишу", "надо подумать"]
REFUSE = ["нет, спасибо", "не нужно", "спасибо, не надо", "нет, не надо"]
STOP = ["не пишите мне больше", "отпишите меня", "уберите меня из рассылки", "больше не пишите", "нет, не интересно, не пишите"]
WRONG = ["вы ошиблись", "я у вас не останавливалась", "это не я"]
BOOKED_ELSEWHERE = ["спасибо, мы уже сняли другую", "уже нашли квартиру", "мы уже забронировали"]
PRICE = ["сколько будет стоить?", "а цена какая?", "сколько стоит?"]
AVAIL = ["а свободно на эти даты?", "есть свободные?"]
HUMAN = ["позовите менеджера", "можно живого человека?", "соедините с менеджером"]
POLITE_MGR = ["Уважаемый менеджер, ответьте мне", "менеджер, ответьте пожалуйста"]
RUDE = ["ты тупая что ли", "вы там все дураки?"]
MAT = ["бля, сколько можно спрашивать", "да блин, сука, ответьте нормально"]
BOT_Q = ["вы бот?", "это робот отвечает?", "ты бот?"]
THANKS = ["спасибо!", "спасибо)", "спс", "благодарю"]
YES = ["да", "ага", "ок", "давайте", "да, расскажите", "Здравствуйте! Да", "интересно", "конечно"]
TROUBLE = [("у нас сломался кран", "trouble"), ("нет горячей воды", "trouble"), ("не работает вайфай в квартире", "trouble")]
PAY = ["я оплатила, вот чек", "перевела деньги, проверьте"]
CANCEL = ["хочу отменить бронь", "можно перенести бронь?"]
EXTEND = ["можно продлить на день?", "хотим остаться ещё на ночь"]
COMPLAINT = ["в квартире грязно, я очень недовольна", "ужасно, всё сломано", "у вас плохо было в прошлый раз"]


def noise(rng: random.Random, text: str) -> str:
    """Как пишут живые люди: без заглавной, без точки, иногда «))»."""
    r = rng.random()
    if r < 0.30:
        text = text[:1].lower() + text[1:]
    if rng.random() < 0.25:
        text = text.rstrip("?.!")
    if rng.random() < 0.08:
        text += "))"
    if rng.random() < 0.05:
        text = text.replace("квартир", "квартр").replace("сколько", "сколко")
    return text


class Dlg:
    def __init__(self, rng: random.Random, start: str):
        self.rng = rng
        self.start = start
        self.turns: list[dict[str, Any]] = []
        self.slots: dict[str, Any] = {"dates": "", "guests": "", "district": "", "returning": ""}
        self.rot: dict[str, int] = {}
        self.tags: list[str] = []

    def pick(self, pool: list[Any], [REDACTED] -> Any:
        i = self.rot.get(key, self.rng.randrange(len(pool)))
        self.rot[key] = i + 1
        return pool[i % len(pool)]

    def bot(self, *msgs: str) -> None:
        for m in msgs:
            if m:
                self.turns.append({"role": "bot", "text": m})

    def guest(self, text: str, **expect: Any) -> None:
        known = [k for k in ("dates", "guests", "district") if self.slots.get(k)]
        self.turns.append({"role": "guest", "text": text, "expect": {"known_before": known, **expect}})

    def set_expect(self, **kw: Any) -> None:
        for t in reversed(self.turns):
            if t["role"] == "guest":
                t["expect"].update(kw)
                return

    # следующий вопрос воронки (одна штука, формулировки чередуются как у живого менеджера)
    def next_ask(self) -> str:
        if not self.slots["dates"]:
            return self.pick(P.LOOKING_START, "dates")
        if not self.slots["guests"]:
            return self.pick([v[0] for v in P.DATES_OK], "guests").replace("Поняла. ", "").replace("Хорошо. ", "")
        if not self.slots["district"]:
            return self.pick([v[0] for v in P.GUESTS_OK], "district")
        return ""


def _guest_echo(n: int, said: str = "") -> str:
    if n == 1 and re.search(r"(?i)\bодна\b", said):
        return "одна"
    return GUEST_WORD.get(n, f"{n} гостей")


def funnel(d: Dlg, *, side_chance: float = 0.45, finish: str = "booking") -> None:
    """Даты → гости → район → карточки → выбор → (были ли у нас) → менеджер. С попутными вопросами."""
    rng = d.rng
    sides = rng.sample(SIDE, k=3)
    # даты
    if not d.slots["dates"]:
        if rng.random() < 0.12:
            d.guest(noise(rng, rng.choice(DATES_UNKNOWN)), intent="dates_unknown")
            d.slots["dates"] = "ещё не определились"
            d.bot(WAIT_OFFER)
        else:
            g, echo = rng.choice(DATES)
            if rng.random() < side_chance:
                topic, qs, ans = sides.pop()
                d.guest(noise(rng, f"{g}, {rng.choice(qs)}"), intent="dates+side", topic=topic)
                d.slots["dates"] = echo
                d.bot(f"{echo}. {ans} {d.next_ask()}".strip())
            else:
                d.guest(noise(rng, g), intent="dates")
                d.slots["dates"] = echo
                d.bot(f"{echo}. {d.next_ask()}")
    # гости
    if not d.slots["guests"]:
        g, n = rng.choice(GUESTS)
        if rng.random() < side_chance * 0.7:
            topic, qs, ans = sides.pop()
            d.guest(noise(rng, f"{g}. {rng.choice(qs)}"), intent="guests+side", topic=topic)
            d.slots["guests"] = n
            d.bot(f"{_guest_echo(n, g).capitalize()}. {ans} {d.next_ask()}".strip())
        else:
            d.guest(noise(rng, g), intent="guests")
            d.slots["guests"] = n
            d.bot(f"{_guest_echo(n, g).capitalize()}. {d.next_ask()}")
        # поправка
        if rng.random() < 0.08:
            n2 = n + 1
            d.guest(noise(rng, f"ой, не {n}, а {n2}"), intent="correction")
            d.slots["guests"] = n2
            d.bot(f"Поняла, {_guest_echo(n2)}.")
    # попутный вопрос отдельным сообщением
    if sides and rng.random() < side_chance:
        topic, qs, ans = sides.pop()
        d.guest(noise(rng, rng.choice(qs)), intent="side", topic=topic)
        d.bot(f"{ans} {d.next_ask()}".strip())
    # район
    if not d.slots["district"]:
        g, canon = rng.choice(DISTRICTS)
        d.guest(noise(rng, g), intent="district")
        d.slots["district"] = canon
    tail = "Какая ближе? Напишите номер или название)" if d.slots["returning"] else "Вы у нас уже были или впервые?"
    if finish == "district_then_later":
        d.bot("Подобрала несколько вариантов:", CARDS, tail)
        d.guest(noise(rng, rng.choice(LATER)), intent="later")
        d.bot(P.LATER_LINE)
        d.tags.append("later_after_cards")
        return
    if finish == "district_then_price":
        d.bot("Подобрала несколько вариантов:", CARDS, tail)
        d.guest(noise(rng, rng.choice(PRICE)), intent="price", esc=True)
        d.bot("Цена зависит от дат и квартиры. Сейчас подключу менеджера, он скажет точно.")
        return
    # как в боте: карточки сразу после района; новому гостю — «были у нас или впервые?» в том же ходе
    if d.slots["returning"]:
        d.bot("Подобрала несколько вариантов:", CARDS, "Какая ближе? Напишите номер или название)")
        d.guest(noise(rng, rng.choice(PICKS)), intent="pick", esc=True)
        d.bot(HANDOFF)
        return
    d.bot("Подобрала несколько вариантов:", CARDS, "Вы у нас уже были или впервые?")
    way = rng.choice(["pick_and_ret", "first_time", "regular"])
    if way == "pick_and_ret":
        pick = rng.choice(["второй, мы у вас уже были", "первый нравится, впервые у вас", "третий, были в прошлом году"])
        d.guest(noise(rng, pick), intent="pick", esc=True)
        d.slots["returning"] = "да" if "был" in pick else "нет"
        d.bot(HANDOFF)
    elif way == "first_time":
        d.guest(noise(rng, rng.choice(["впервые", "нет, первый раз", "первый раз у вас"])), intent="returning", esc=True)
        d.slots["returning"] = "нет"
        d.bot(HANDOFF)
    else:
        d.guest(noise(rng, rng.choice(["да, уже были", "были в прошлом году", "да, останавливались"])), intent="returning")
        d.slots["returning"] = "да"
        d.bot("Здорово) Напомните название или адрес квартиры, отмечу как постоянного гостя.")
        d.guest(noise(rng, rng.choice(["Скандинавия", "Чехов", "не помню уже", "на Фитарёвской", "Россо вроде"])), intent="favorite", esc=True)
        d.bot(HANDOFF)


# ─────────────────────────────── сценарии ───────────────────────────────

WAIT_OFFER = "Хорошо, не спешите) Могу пока скинуть пару квартир, чтобы были на примете?"
WAIT_THINK = "Хорошо, как надумаете, пишите) Подберу квартиру."
ACKS = ["хорошо", "Хорошо", "ок", "окей", "ладно", "хорошо, спасибо", "договорились", "понятно", "ок, напишу"]


def _facts_invite(topic: str) -> str:
    """Факты по предложению + мягкое приглашение, как в бот (phrases.offer_reply)."""
    line = P.offer_facts(topic)
    sep = "\n\n" if re.search(r"https?://\S+$", line.rstrip()) else " "
    return line.rstrip() + sep + "Если что-то планируете, напишите, подберу квартиру)"


def sc_outreach(rng: random.Random) -> Dlg:
    d = Dlg(rng, "outreach")
    idx = rng.randrange(len(P.GREETINGS))
    topic = P.OUTREACH_OFFER[idx]
    name = rng.choice(NAMES)
    tod = rng.choice(["Добрый день", "Добрый вечер", "Здравствуйте"])
    letter = P.GREETINGS[idx][0].format(tod=tod, name_part=f", {name}", stay="")
    d.bot(letter)
    d.slots["returning"] = "да"
    d.tags += ["outreach", f"offer:{topic}"]
    branch = rng.choices(
        ["yes_then_funnel", "yes_then_later", "refuse", "stop", "wrong", "booked", "who", "number",
         "direct_dates", "later", "yes_then_question", "ghost", "rude_then_ok", "bot_then_ok", "yes_then_ack"],
        weights=[22, 8, 9, 7, 3, 5, 4, 4, 10, 6, 8, 5, 3, 3, 8],
    )[0]
    d.tags.append(branch)
    if branch.startswith("yes"):
        yes = rng.choice(YES)
        d.guest(noise(rng, yes), intent="consent")
        if topic == "need":
            d.bot(d.pick(P.LOOKING_START, "dates"))
        else:
            d.bot(_facts_invite(topic))
            d.set_expect(no_dates_question=True)
        if branch == "yes_then_ack" and topic != "need":
            # «Хорошо» на «напишите, подберу» → «Будем ждать!» → ещё «хорошо» → 😊 (скрин 46)
            d.guest(noise(rng, rng.choice(ACKS)), intent="ack_wait")
            d.bot("Будем ждать!")
            d.set_expect(no_question=True)
            if rng.random() < 0.6:
                d.guest(rng.choice(ACKS), intent="ack_wait")
                d.bot("😊")
                d.set_expect(no_question=True)
            return d
        if branch == "yes_then_later":
            d.guest(noise(rng, rng.choice(LATER)), intent="later")
            d.bot(P.LATER_LINE)
            return d
        if branch == "yes_then_question":
            topic2, qs, ans = rng.choice(SIDE)
            d.guest(noise(rng, rng.choice(qs)), intent="side", topic=topic2)
            d.bot(f"{ans} {d.next_ask()}".strip())
        if topic != "need" and branch == "yes_then_funnel":
            opener = rng.choice(["класс, а на новый год есть что-то?", "о, интересно, нам как раз нужна квартира",
                                 "здорово. нам нужна квартира", "понятно, спасибо. а квартира на выходные есть?"])
            if "новый год" in opener:
                d.slots["dates"] = "На Новый год"
                d.guest(noise(rng, opener), intent="dates")
                d.bot(f"На Новый год подберу. {d.next_ask()}")
            elif "выходные" in opener:
                d.slots["dates"] = "На выходные"
                d.guest(noise(rng, opener), intent="dates")
                d.bot(f"На выходные подберу. {d.next_ask()}")
            else:
                d.guest(noise(rng, opener), intent="looking")
                d.bot(d.next_ask())
        funnel(d, finish=rng.choice(["booking"] * 6 + ["district_then_later", "district_then_price"]))
        return d
    if branch == "refuse":
        d.guest(noise(rng, rng.choice(REFUSE)), intent="refuse")
        d.bot(d.pick(P.SOFT_CLOSE_LEAD, "close"))
        return d
    if branch == "stop":
        d.guest(noise(rng, rng.choice(STOP)), intent="stop", stop=True)
        d.bot(d.pick(P.STOP_ACK, "stop"))
        return d
    if branch == "wrong":
        d.guest(noise(rng, rng.choice(WRONG)), intent="wrong", stop=True)
        d.bot("Поняла, больше не пишу. Извините за беспокойство.")
        return d
    if branch == "booked":
        d.guest(noise(rng, rng.choice(BOOKED_ELSEWHERE)), intent="booked_elsewhere")
        d.bot("Хорошо) Понадобится квартира в следующий раз, пишите.")
        return d
    if branch == "who":
        d.guest(noise(rng, rng.choice(["а вы кто?", "кто это?", "что за Home24?"])), intent="who")
        d.bot("Это Home24, квартиры посуточно в Москве) Вы у нас останавливались, поэтому пишу.")
        if rng.random() < 0.5:
            d.guest(noise(rng, rng.choice(YES)), intent="consent")
            d.bot(_facts_invite(topic if topic != "need" else "services"))
        return d
    if branch == "number":
        d.guest(noise(rng, rng.choice(["откуда у вас мой номер?", "где вы взяли мой номер?"])), intent="number")
        d.bot("Вы бронировали у нас квартиру, номер остался с той брони. "
              "Если не хотите сообщений, напишите, больше не побеспокою.")
        if rng.random() < 0.4:
            d.guest(noise(rng, rng.choice(STOP)), intent="stop", stop=True)
            d.bot(d.pick(P.STOP_ACK, "stop"))
        return d
    if branch == "direct_dates":
        g, echo = rng.choice(DATES)
        gg, n = rng.choice(GUESTS_IN_SENTENCE)
        d.guest(noise(rng, f"Здравствуйте! Нужна квартира {g}, {gg}"), intent="dates+guests")
        d.slots.update(dates=echo, guests=n)
        d.bot(f"{echo}, {_guest_echo(n, gg)}. {d.next_ask()}")
        funnel(d)
        return d
    if branch == "later":
        d.guest(noise(rng, rng.choice(LATER)), intent="later")
        d.bot(P.LATER_LINE)
        return d
    if branch == "ghost":
        d.guest(noise(rng, rng.choice(YES)), intent="consent")
        d.bot(_facts_invite(topic) if topic != "need" else d.pick(P.LOOKING_START, "dates"))
        d.tags.append("no_reply_after")  # гость пропал — бот не дожимает
        return d
    if branch == "rude_then_ok":
        d.guest(noise(rng, rng.choice(RUDE)), intent="rude")
        d.bot("Извините, если не так поняла. Давайте ещё раз, или позвать менеджера?")
        d.guest(noise(rng, "ладно. нужна квартира на выходные"), intent="dates")
        d.slots["dates"] = "На выходные"
        d.bot(f"На выходные подберу. {d.next_ask()}")
        funnel(d, side_chance=0.2)
        return d
    if branch == "bot_then_ok":
        d.guest(noise(rng, rng.choice(BOT_Q)), intent="bot")
        d.bot("Я виртуальный помощник Home24, могу позвать менеджера.")
        if rng.random() < 0.5:
            d.guest(noise(rng, rng.choice(HUMAN)), intent="human", esc=True)
            d.bot(HANDOFF)
        else:
            d.guest(noise(rng, "ок, тогда расскажите"), intent="consent")
            d.bot(_facts_invite(topic if topic != "need" else "services"))
        return d
    return d


def sc_inbound(rng: random.Random) -> Dlg:
    d = Dlg(rng, "inbound")
    d.tags.append("inbound")
    branch = rng.choices(
        ["hello_funnel", "purpose_funnel", "all_in_one", "price_first", "side_first", "browsing", "later_mid",
         "refuse_mid", "human", "polite_mgr", "mat_then_ok", "bot_q", "hourly", "minor", "thanks_end", "unknown_dates"],
        weights=[16, 18, 8, 7, 10, 6, 5, 3, 3, 3, 2, 3, 2, 2, 5, 7],
    )[0]
    d.tags.append(branch)
    if branch == "hello_funnel":
        d.guest(noise(rng, rng.choice(OPENERS_INBOUND)), intent="hello")
        hello = rng.choice(P.INBOUND_HELLO)
        d.bot(" ".join(x.format(tod="Добрый день", name_part="") for x in hello))
        d.rot["dates"] = 1
        funnel(d)
    elif branch == "purpose_funnel":
        purpose = rng.choice(list(PURPOSES))
        info = PURPOSES[purpose]
        d.tags.append(f"purpose:{purpose}")
        say = rng.choice(info["say"])
        if rng.random() < 0.5:
            g, echo = rng.choice(DATES)
            d.guest(noise(rng, f"Здравствуйте, {say}, {g}"), intent="purpose+dates")
            d.slots["dates"] = echo
            lead = {"командировка": "Для командировки у нас удобно.", "праздник": "Тихо отметить можно, и квартиру можем украсить.",
                    "романтика": "Можем подготовить романтический вечер с кино на проекторе.",
                    "фотосессия": "Да, есть квартиры для фотосессий, условия скажет менеджер."}.get(purpose, "")
            d.bot(f"{lead} {echo}. {d.next_ask()}".strip())
        else:
            d.guest(noise(rng, f"Здравствуйте, {say}"), intent="purpose")
            lead = {"командировка": "Для командировки у нас удобно, и документы для отчёта сделаем.",
                    "лечение": "Поняла.", "ремонт": "Да, на время ремонта у нас часто живут)",
                    "праздник": "Тихо отметить можно, и квартиру можем украсить.",
                    "романтика": "Можем подготовить романтический вечер с кино на проекторе.",
                    "фотосессия": "Да, есть квартиры для фотосессий, условия скажет менеджер."}.get(purpose, "С радостью подберу.")
            d.bot(f"{lead} {d.next_ask()}".strip())
        if info["ask"] and rng.random() < 0.6:
            q, a = info["ask"]
            d.guest(noise(rng, q), intent="purpose_q", topic=purpose)
            d.bot(f"{a} {d.next_ask()}".strip())
        funnel(d, finish=rng.choice(["booking"] * 5 + ["district_then_later", "district_then_price"]))
    elif branch == "all_in_one":
        g, echo = rng.choice(DATES)
        gg, n = rng.choice(GUESTS_IN_SENTENCE)
        dd, canon = rng.choice(DISTRICTS)
        d.guest(noise(rng, f"Здравствуйте, нужна квартира {g}, {gg}, {dd}"), intent="dates+guests+district")
        d.slots.update(dates=echo, guests=n, district=canon)
        funnel(d)
    elif branch == "price_first":
        d.guest(noise(rng, rng.choice(["сколько стоит квартира на сутки?", "какие цены?", "сколько стоит у вас?"])), intent="price")
        d.bot(f"Цена зависит от дат и квартиры. {d.next_ask()}")
        g, echo = rng.choice(DATES)
        d.guest(noise(rng, g), intent="dates")
        d.slots["dates"] = echo
        d.bot(f"{echo}. {d.next_ask()}")
        funnel(d, finish=rng.choice(["booking", "district_then_price"]))
    elif branch == "side_first":
        topic, qs, ans = rng.choice(SIDE)
        q2 = ""
        if rng.random() < 0.3:
            t2, qs2, a2 = rng.choice([s for s in SIDE if s[0] != topic])
            q2 = f" и {rng.choice(qs2)}"
            ans = f"{ans} {a2}"
        d.guest(noise(rng, f"{rng.choice(qs)}{q2}"), intent="side", topic=topic)
        d.bot(f"{ans} {d.next_ask()}".strip())
        funnel(d, side_chance=0.3)
    elif branch == "browsing":
        d.guest(noise(rng, rng.choice(["пока просто смотрю", "на будущее присматриваюсь", "просто интересуюсь"])), intent="browsing")
        d.bot(d.pick([v[0] for v in P.BROWSING_START], "browse"))
        if rng.random() < 0.6:
            d.guest(noise(rng, rng.choice(["да, скиньте", "давайте", "можно"])), intent="consent")
            d.bot("Вот несколько вариантов:", CARDS, "Как появятся даты, напишите, проверю свободные.")
        else:
            d.guest(noise(rng, rng.choice(REFUSE)), intent="refuse")
            d.bot(d.pick(P.SOFT_CLOSE_LEAD, "close"))
    elif branch == "later_mid":
        d.guest(noise(rng, rng.choice(OPENERS_INBOUND)), intent="hello")
        d.bot(" ".join(x.format(tod="Добрый день", name_part="") for x in rng.choice(P.INBOUND_HELLO)))
        g, echo = rng.choice(DATES)
        d.guest(noise(rng, g), intent="dates")
        d.slots["dates"] = echo
        d.bot(f"{echo}. {d.next_ask()}")
        d.guest(noise(rng, rng.choice(LATER)), intent="later")
        d.bot(P.LATER_LINE)
    elif branch == "refuse_mid":
        d.guest(noise(rng, "здравствуйте, нужна квартира"), intent="hello")
        d.bot(d.pick(P.LOOKING_START, "dates"))
        d.guest(noise(rng, rng.choice(["а, нет, уже не нужно", "отбой, нашли"])), intent="refuse")
        d.bot(d.pick(P.SOFT_CLOSE_LEAD, "close"))
    elif branch == "human":
        d.guest(noise(rng, rng.choice(HUMAN)), intent="human", esc=True)
        d.bot(HANDOFF)
    elif branch == "polite_mgr":
        d.guest(rng.choice(POLITE_MGR), intent="polite_manager", esc=False)
        d.bot("Да, я тут, слушаю вас.")
        g, echo = rng.choice(DATES)
        d.guest(noise(rng, f"нужна квартира {g}"), intent="dates")
        d.slots["dates"] = echo
        d.bot(f"{echo}. {d.next_ask()}")
        funnel(d)
    elif branch == "mat_then_ok":
        d.guest(rng.choice(MAT), intent="rude")
        d.bot("Давайте спокойно, я помогу. Что нужно по квартире?")
        d.guest(noise(rng, "квартира на выходные нужна"), intent="dates")
        d.slots["dates"] = "На выходные"
        d.bot(f"На выходные подберу. {d.next_ask()}")
        funnel(d, side_chance=0.2)
    elif branch == "bot_q":
        d.guest(noise(rng, rng.choice(BOT_Q)), intent="bot")
        d.bot("Я виртуальный помощник Home24, могу позвать менеджера.")
        d.guest(noise(rng, "ладно, нужна квартира"), intent="looking")
        d.bot(d.next_ask())
        funnel(d)
    elif branch == "hourly":
        d.guest(noise(rng, rng.choice(["можно снять на 3 часа?", "почасово можно?", "нужна квартира на пару часов"])), intent="hourly")
        d.bot(f"Сдаём посуточно, по часам нет. {d.next_ask()}")
        if rng.random() < 0.5:
            d.guest(noise(rng, "тогда не надо"), intent="refuse")
            d.bot(d.pick(P.SOFT_CLOSE_LEAD, "close"))
        else:
            funnel(d)
    elif branch == "minor":
        d.guest(noise(rng, rng.choice(["можно заселить детей 16 лет одних?", "сын 17 лет заселится один?"])), intent="minor")
        d.bot("Заселяется взрослый по своему паспорту, дети одни не заселяются.")
    elif branch == "thanks_end":
        topic, qs, ans = rng.choice(SIDE)
        d.guest(noise(rng, rng.choice(qs)), intent="side", topic=topic)
        d.bot(f"{ans} {d.next_ask()}".strip())
        d.guest(noise(rng, rng.choice(THANKS)), intent="thanks")
        d.bot(rng.choice(P.THANKS))
        d.set_expect(no_question=True)
    elif branch == "unknown_dates":
        d.guest(noise(rng, rng.choice(OPENERS_INBOUND)), intent="hello")
        d.bot(" ".join(x.format(tod="Добрый день", name_part="") for x in rng.choice(P.INBOUND_HELLO)))
        d.guest(noise(rng, rng.choice(DATES_UNKNOWN)), intent="dates_unknown")
        d.slots["dates"] = "ещё не определились"
        d.bot(WAIT_OFFER)
        d.set_expect(no_dates_question=True)
        if rng.random() < 0.5:
            g, n = rng.choice(GUESTS)
            d.guest(noise(rng, g), intent="guests")
            d.slots["guests"] = n
            d.bot(f"{_guest_echo(n, g).capitalize()}. {d.next_ask()}")
            d.guest(noise(rng, rng.choice(["пока не знаем", "без разницы", "не знаю, где удобнее", "всё равно"])), intent="district_any")
            d.slots["district"] = "любой"
            d.bot("Хорошо, подберу в разных районах) Как появятся даты, напишите, сразу пришлю варианты.")
            d.set_expect(no_dates_question=True)
        else:
            d.guest(noise(rng, rng.choice(DATES_UNKNOWN)), intent="dates_unknown")
            d.bot(WAIT_THINK)
            d.set_expect(no_dates_question=True)
            if rng.random() < 0.6:
                # гость думает: «хорошо» → «Будем ждать!» → «хорошо» → 😊 (скрин 46)
                d.guest(noise(rng, rng.choice(ACKS)), intent="ack_wait")
                d.bot("Будем ждать!")
                d.set_expect(no_question=True)
                if rng.random() < 0.5:
                    d.guest(rng.choice(ACKS), intent="ack_wait")
                    d.bot("😊")
                    d.set_expect(no_question=True)
    return d


def sc_stay(rng: random.Random) -> Dlg:
    """Гость уже живёт или забронировал: проблемы, оплата, отмена, продление, жалоба."""
    d = Dlg(rng, "stay")
    d.tags.append("stay")
    kind = rng.choice(["trouble", "pay", "cancel", "extend", "complaint", "wait"])
    d.tags.append(kind)
    if kind == "trouble":
        d.guest(noise(rng, rng.choice(TROUBLE)[0]), intent="trouble", esc=True)
        d.bot("Это уже по проживанию, сразу передаю менеджеру.")
    elif kind == "pay":
        d.guest(noise(rng, rng.choice(PAY)), intent="pay", esc=True)
        d.bot("Оплату по сообщению не подтверждаю, передам менеджеру, он сверит чек.")
    elif kind == "cancel":
        d.guest(noise(rng, rng.choice(CANCEL)), intent="cancel", esc=True)
        d.bot("Отмена и перенос зависят от условий брони. Передам менеджеру, он скажет точно.")
    elif kind == "extend":
        d.guest(noise(rng, rng.choice(EXTEND)), intent="extend", esc=True)
        d.bot("Продление зависит от занятости квартиры. Передам менеджеру.")
    elif kind == "complaint":
        d.guest(noise(rng, rng.choice(COMPLAINT)), intent="complaint", esc=True)
        d.bot("Очень жаль, что так вышло. Напишите подробнее, я сразу передам администратору, разберёмся.")
    else:
        d.guest(noise(rng, rng.choice(["сколько ждать менеджера?", "когда ответит менеджер?"])), intent="wait")
        d.bot("Менеджер обычно отвечает минут за 10–15 в рабочее время.")
    return d


OUTCOME_BY_LAST = [
    (HANDOFF, "менеджер (бронь)"),
    ("Цена зависит от дат и квартиры. Сейчас подключу", "менеджер (цена)"),
    ("Это уже по проживанию", "менеджер (проблема)"),
    ("сверит чек", "менеджер (оплата)"),
    ("Отмена и перенос", "менеджер (отмена)"),
    ("Продление зависит", "менеджер (продление)"),
    ("Очень жаль, что так вышло", "менеджер (жалоба)"),
    (P.LATER_LINE, "подумает"),
]


def outcome_of(d: Dlg) -> str:
    last_bot = next((t["text"] for t in reversed(d.turns) if t["role"] == "bot"), "")
    last_guest = next((t for t in reversed(d.turns) if t["role"] == "guest"), None)
    if last_guest and last_guest["expect"].get("stop"):
        return "стоп-лист"
    for marker, name in OUTCOME_BY_LAST:
        if marker in last_bot:
            return name
    if last_bot in P.SOFT_CLOSE_LEAD:
        return "мягкое закрытие"
    if "Понадобится квартира в следующий раз" in last_bot:
        return "уже снял другую"
    if "no_reply_after" in d.tags:
        return "гость пропал"
    if "Дети одни" in last_bot or "дети одни" in last_bot:
        return "отказ по правилам"
    if CARDS in [t["text"] for t in d.turns if t["role"] == "bot"]:
        return "показали варианты"
    return "ответ на вопрос"


def build(n: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    makers = [(sc_outreach, 0.48), (sc_inbound, 0.44), (sc_stay, 0.08)]
    tries = 0
    while len(out) < n and tries < n * 50:
        tries += 1
        maker = rng.choices([m for m, _ in makers], weights=[w for _, w in makers])[0]
        d = maker(random.Random(rng.random()))
        [REDACTED] for t in d.turns], ensure_ascii=False).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": f"h24-{len(out) + 1:04d}",
                "start": d.start,
                "outcome": outcome_of(d),
                "tags": d.tags,
                "slots": d.slots,
                "turns": d.turns,
            }
        )
    return out


def to_finetune(dialogs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Формат chat-дообучения (OpenAI / Mistral / Together): messages с ролями."""
    system = "Ты менеджер Home24 (посуточная аренда квартир в Москве). Пиши коротко, тепло, по script.md."
    rows = []
    for dlg in dialogs:
        msgs = [{"role": "system", "content": system}]
        for t in dlg["turns"]:
            role = "assistant" if t["role"] == "bot" else "user"
            if msgs[-1]["role"] == role and role == "assistant":
                msgs[-1]["content"] += "\n" + t["text"]
            else:
                msgs.append({"role": role, "content": t["text"]})
        if msgs[-1]["role"] == "assistant" and any(m["role"] == "user" for m in msgs):
            rows.append({"messages": msgs})
    return rows


def sample_md(dialogs: list[dict[str, Any]], k: int = 60) -> str:
    by_outcome: dict[str, list[dict[str, Any]]] = {}
    for dlg in dialogs:
        by_outcome.setdefault(dlg["outcome"], []).append(dlg)
    lines = [f"# Эталонные диалоги Home24 — выборка ({k} из {len(dialogs)})", "",
             "| Исход | Диалогов |", "| --- | --- |"]
    for o, ds in sorted(by_outcome.items(), [REDACTED] x: -len(x[1])):
        lines.append(f"| {o} | {len(ds)} |")
    lines.append("")
    rng = random.Random(1)
    picked: list[dict[str, Any]] = []
    for o, ds in sorted(by_outcome.items(), [REDACTED] x: -len(x[1])):
        picked += rng.sample(ds, k=min(len(ds), max(2, k * len(ds) // len(dialogs))))
    for dlg in picked[:k]:
        lines.append(f"## {dlg['id']} · {dlg['outcome']} · {', '.join(dlg['tags'][:3])}")
        for t in dlg["turns"]:
            who = "Бот" if t["role"] == "bot" else "Гость"
            lines.append(f"- **{who}:** {t['text']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=24)
    args = ap.parse_args()
    dialogs = build(args.n, args.seed)
    OUT_DIR.mkdir(exist_ok=True)
    with (OUT_DIR / "dialogs_home24.jsonl").open("w", encoding="utf-8") as f:
        for dlg in dialogs:
            f.write(json.dumps(dlg, ensure_ascii=False) + "\n")
    with (OUT_DIR / "finetune_home24.jsonl").open("w", encoding="utf-8") as f:
        for row in to_finetune(dialogs):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (OUT_DIR / "dialogs_home24_sample.md").write_text(sample_md(dialogs), encoding="utf-8")
    turns = sum(1 for dlg in dialogs for t in dlg["turns"] if t["role"] == "guest")
    print(f"Диалогов: {len(dialogs)}, реплик гостя: {turns}")


if __name__ == "__main__":
    main()
