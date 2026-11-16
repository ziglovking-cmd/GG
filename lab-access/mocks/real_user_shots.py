#!/usr/bin/env python3
"""Generate Access screenshots that look like a normal Windows user snipped them."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import random
import math

OUT = Path("/workspace/lab-access/shots")
OUT.mkdir(exist_ok=True)
ORIG = Path("/tmp/report_imgs")

# Reuse real student screenshots where they map cleanly
REAL_MAP = {
    "t_stud": "img_15.png",  # real students datasheet
}

GROUPS = ["1224", "1761", "2763", "СП13Э-21", "СП13Ю-24", "СП13Ю-25В", "ИС1-251-ОТ"]
DISC = [
    "Иностранный язык в сфере юриспруденции", "Информатика",
    "История госуд. и права заруб. стран", "История отеч. государства и права",
    "ИТ в юридической деятельности", "Логика", "Правоохранительные органы",
    "Практикум по освоению ЭВМ", "Русский язык и культура речи",
    "Теория государства и права", "Философия", "Экономика",
]
CTRL = ["ДифЗачет", "Зачет", "Экзамен"]
GRADES = ["2", "3", "4", "5", "зачтено", "неаттестован", "незачтено", "неявка"]
TEACHERS = [(1, "Кабанов В.А."), (2, "Ткаченко Л.А."), (3, "Безгинов А.Н."), (4, "Качаун Е.Я.")]
STUDENTS = [
    ("10\\2818", "Миров", "Андрей", "Валерьевич", "СП13Ю-25В", "12.03.2006", "896956956", "vlinr@2823", "Морозова 5"),
    ("16\\201", "Тыщенко", "Валерия", "Артёмовна", "СП13Э-21", "19.03.2003", "8937827189", "soba@53", "Пушкина 25"),
    ("1э/2013", "Федоров", "Федор", "Федорыч", "1224", "01.07.1996", "89489438945", "Swi@1734", "Пушкина 3"),
    ("1ю/2013", "Гирявенко", "Александра", "Ивановна", "СП13Ю-24", "28.09.2000", "8959499440", "Son@28892", "Пушкина 8"),
    ("57\\1339", "Валентинов", "Валентин", "Валентинович", "2763", "06.06.2006", "89696999934", "Kjp@7273", "Пушкина 205"),
    ("9\\2982", "Крапивко", "Ольга", "Александравна", "1761", "14.04.2009", "85989478838", "Wo@5662", "Пушкина 67"),
    ("ИС-251", "Новикова", "Анна", "Сергеевна", "ИС1-251-ОТ", "15.05.2005", "89001234567", "anna@mail.ru", "Ленина 12"),
]
PERF = [
    ("05.05.2007", "Качаун Е.Я.", "9\\2982", "6", "незачтено", "Философия", "Экзамен"),
    ("07.09.2008", "Качаун Е.Я.", "1ю/2013", "4", "неявка", "ИТ в юридической деятельности", "Экзамен"),
    ("02.12.2001", "Кабанов В.А.", "57\\1339", "5", "3", "Логика", "Экзамен"),
    ("19.08.2013", "Кабанов В.А.", "10\\2818", "1", "2", "Информатика", "ДифЗачет"),
    ("29.09.2009", "Ткаченко Л.А.", "16\\201", "2", "5", "Иностранный язык в сфере юриспруденции", "Зачет"),
    ("20.08.2010", "Безгинов А.Н.", "1э/2013", "3", "зачтено", "История отеч. государства и права", "Зачет"),
    ("20.12.2024", "Кабанов В.А.", "ИС-251", "1", "5", "Информатика", "Экзамен"),
]
TEACH = {c: n for c, n in TEACHERS}


def font(size=13, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def measure(draw, text, f):
    b = draw.textbbox((0, 0), text, font=f)
    return b[2] - b[0], b[3] - b[1]


def humanize(im, seed=1):
    """Make image look like a snipping-tool capture: soft, slight noise, jpeg-ish."""
    rng = random.Random(seed)
    # tiny random crop inset then pad back unevenly (like shaky snip)
    w, h = im.size
    l = rng.randint(0, 3)
    t = rng.randint(0, 3)
    r = w - rng.randint(0, 3)
    b = h - rng.randint(0, 2)
    im = im.crop((l, t, r, b))
    # very light blur (screen capture softness)
    im = im.filter(ImageFilter.GaussianBlur(radius=0.35))
    # slight contrast drop
    im = ImageEnhance.Contrast(im).enhance(0.97)
    im = ImageEnhance.Color(im).enhance(0.95)
    # add faint noise
    px = im.load()
    for _ in range(max(80, w * h // 900)):
        x = rng.randint(0, im.width - 1)
        y = rng.randint(0, im.height - 1)
        c = list(px[x, y][:3])
        d = rng.randint(-6, 6)
        px[x, y] = tuple(max(0, min(255, v + d)) for v in c) + ((px[x, y][3],) if len(px[x, y]) == 4 else ())
    # recompress via JPEG roundtrip like many students paste into Word
    from io import BytesIO
    buf = BytesIO()
    rgb = im.convert("RGB")
    rgb.save(buf, format="JPEG", quality=rng.randint(82, 92))
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def datasheet(headers, rows, widths=None, selected=1, title=None, show_plus=True, scale=1):
    """Access-like datasheet crop (what students usually snip)."""
    f_h = font(12, True)
    f = font(12)
    row_h = 22
    head_h = 24
    left_w = 28 if show_plus else 18
    if widths is None:
        widths = []
        for i, h in enumerate(headers):
            mx = measure(ImageDraw.Draw(Image.new("RGB", (1, 1))), h, f_h)[0] + 18
            for r in rows:
                mx = max(mx, measure(ImageDraw.Draw(Image.new("RGB", (1, 1))), str(r[i]), f)[0] + 16)
            widths.append(min(max(mx, 70), 260))
    W = left_w + sum(widths) + 2
    H = head_h + row_h * len(rows) + 2
    if title:
        H += 22
        y0 = 22
    else:
        y0 = 0
    im = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(im)
    if title:
        d.rectangle([0, 0, W, 21], fill="#f0f0f0")
        d.text((6, 3), title, fill="#333", font=font(11, True))
        d.line([0, 21, W, 21], fill="#b0b0b0")
    # header
    x = left_w
    d.rectangle([0, y0, W, y0 + head_h], fill="#dce6f2")
    d.rectangle([0, y0, left_w, y0 + head_h], fill="#c8d4e4")
    for i, h in enumerate(headers):
        d.rectangle([x, y0, x + widths[i], y0 + head_h], outline="#9db0c6")
        d.text((x + 5, y0 + 4), h, fill="#1a1a1a", font=f_h)
        # filter arrow
        ax = x + widths[i] - 12
        d.polygon([(ax, y0 + 9), (ax + 7, y0 + 9), (ax + 3, y0 + 14)], fill="#5a6a7a")
        x += widths[i]
    d.line([0, y0 + head_h, W, y0 + head_h], fill="#8fa3ba")
    # rows
    for ri, row in enumerate(rows):
        y = y0 + head_h + ri * row_h
        bg = "#fff9e6" if ri == selected else ("#f5f9fc" if ri % 2 else "#ffffff")
        d.rectangle([0, y, W, y + row_h], fill=bg)
        # row selector
        sel_bg = "#e8c66a" if ri == selected else "#ececec"
        d.rectangle([0, y, left_w, y + row_h], fill=sel_bg, outline="#b0b0b0")
        if show_plus:
            d.text((4, y + 3), "+", fill="#555", font=font(11, True))
        x = left_w
        for i, cell in enumerate(row):
            d.rectangle([x, y, x + widths[i], y + row_h], outline="#cfd7e0")
            txt = str(cell)
            color = "#0563c1" if headers[i] in ("E-mail", "Сайт") else "#000"
            d.text((x + 5, y + 4), txt, fill=color, font=f)
            x += widths[i]
    # outer border
    d.rectangle([0, y0, W - 1, H - 1], outline="#7a8a9a")
    return im


def constructor(fields, title=""):
    """Table design view crop: field name | type."""
    f_h = font(12, True)
    f = font(12)
    col_w = [28, 220, 260]
    row_h = 24
    head_h = 24
    W = sum(col_w) + 2
    H = head_h + row_h * max(len(fields), 8) + 4
    im = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(im)
    headers = ["", "Имя поля", "Тип данных"]
    x = 0
    for i, h in enumerate(headers):
        d.rectangle([x, 0, x + col_w[i], head_h], fill="#e8e8e8", outline="#aaa")
        d.text((x + 6, 4), h, fill="#222", font=f_h)
        x += col_w[i]
    for ri in range(max(len(fields), 8)):
        y = head_h + ri * row_h
        vals = fields[ri] if ri < len(fields) else ("", "", False)
        name, typ, is_key = vals
        bg = "#fffef5" if ri == 0 and name else "#ffffff"
        x = 0
        cells = ["🔑" if is_key else "", name, typ]
        for i, c in enumerate(cells):
            d.rectangle([x, y, x + col_w[i], y + row_h], fill=bg, outline="#c8c8c8")
            d.text((x + 5, y + 4), c, fill="#000", font=f)
            x += col_w[i]
    if title:
        # small caption strip like tab
        bar = Image.new("RGB", (W, 20), "#f3f3f3")
        bd = ImageDraw.Draw(bar)
        bd.text((6, 2), title, fill="#333", font=font(11, True))
        out = Image.new("RGB", (W, H + 20), "#ddd")
        out.paste(bar, (0, 0))
        out.paste(im, (0, 20))
        return out
    return im


def query_grid(columns, title=""):
    """Query design grid only (bottom part students snip)."""
    # columns: list of dicts field, table, sort, show, criteria, total?, xtab?
    labels = ["Поле", "Имя таблицы"]
    if any(c.get("total") for c in columns):
        labels.append("Групповая операция")
    labels += ["Сортировка", "Вывод на экран", "Условие отбора"]
    if any(c.get("xtab") for c in columns):
        labels.append("Перекрестная таблица")
    f = font(11)
    f_h = font(11, True)
    col_w = 150
    left_w = 150
    row_h = 22
    W = left_w + col_w * len(columns) + 2
    H = row_h * len(labels) + 2
    im = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(im)
    for ri, lab in enumerate(labels):
        y = ri * row_h
        d.rectangle([0, y, left_w, y + row_h], fill="#ececec", outline="#b0b0b0")
        d.text((5, y + 4), lab, fill="#222", font=f_h)
        for ci, col in enumerate(columns):
            x = left_w + ci * col_w
            d.rectangle([x, y, x + col_w, y + row_h], fill="#fff", outline="#c0c0c0")
            if lab == "Поле":
                val = col["field"]
            elif lab == "Имя таблицы":
                val = col.get("table", "")
            elif lab == "Групповая операция":
                val = col.get("total", "")
            elif lab == "Сортировка":
                val = col.get("sort", "")
            elif lab == "Вывод на экран":
                val = "☑" if col.get("show", True) else "☐"
            elif lab == "Условие отбора":
                val = col.get("criteria", "")
            else:
                val = col.get("xtab", "")
            # truncate long
            if len(val) > 22:
                val = val[:20] + "…"
            d.text((x + 4, y + 4), val, fill="#000", font=f)
    if title:
        bar = Image.new("RGB", (W, 20), "#f0f0f0")
        ImageDraw.Draw(bar).text((6, 2), title, fill="#333", font=font(11, True))
        out = Image.new("RGB", (W, H + 20), "#d0d0d0")
        out.paste(bar, (0, 0))
        out.paste(im, (0, 20))
        return out
    return im


def dialog(title, lines, checks=None, width=420):
    checks = checks or []
    f = font(12)
    f_h = font(12, True)
    pad = 14
    line_h = 22
    H = 36 + pad + line_h * (len(lines) + len(checks)) + 50
    im = Image.new("RGB", (width, H), "#ece9d8")
    d = ImageDraw.Draw(im)
    # title bar classic
    d.rectangle([0, 0, width, 28], fill="#003399")
    d.text((8, 6), title, fill="#fff", font=f_h)
    # close box
    d.rectangle([width - 22, 5, width - 6, 21], fill="#ece9d8", outline="#fff")
    d.text((width - 19, 4), "×", fill="#003399", font=f_h)
    y = 36
    for line in lines:
        d.text((pad, y), line, fill="#000", font=f)
        y += line_h
    for checked, text in checks:
        box = [pad, y + 2, pad + 13, y + 15]
        d.rectangle(box, outline="#000", fill="#fff")
        if checked:
            d.line([pad + 2, y + 8, pad + 5, y + 12], fill="#000", width=2)
            d.line([pad + 5, y + 12, pad + 11, y + 4], fill="#000", width=2)
        d.text((pad + 20, y), text, fill="#000", font=f)
        y += line_h
    # buttons
    by = H - 36
    for i, lab in enumerate(["ОК", "Отмена", "Применить"]):
        bx = width - 90 * (3 - i) - 10
        d.rectangle([bx, by, bx + 80, by + 24], fill="#ece9d8", outline="#000")
        tw = measure(d, lab, f)[0]
        d.text((bx + (80 - tw) // 2, by + 4), lab, fill="#000", font=f)
    d.rectangle([0, 0, width - 1, H - 1], outline="#404040")
    return im


def schema_snip():
    """Simple relationship diagram crop."""
    W, H = 820, 420
    im = Image.new("RGB", (W, H), "#d6e3f0")
    d = ImageDraw.Draw(im)
    f = font(11)
    f_h = font(11, True)

    def box(x, y, title, fields, w=160, h=None):
        h = h or (22 + 16 * len(fields) + 4)
        d.rectangle([x, y, x + w, y + h], fill="#fff", outline="#555")
        d.rectangle([x, y, x + w, y + 20], fill="#1f4e79")
        d.text((x + 6, y + 3), title, fill="#fff", font=f_h)
        for i, fl in enumerate(fields):
            yy = y + 22 + i * 16
            prefix = "🔑 " if fl.startswith("*") else "   "
            d.text((x + 4, yy), prefix + fl.lstrip("*"), fill="#000", font=f)
        return x, y, w, h

    boxes = {
        "g": box(30, 40, "Группы", ["*Группа"], 130, 50),
        "s": box(220, 30, "Студенты", ["*№Зачетки", "Фамилия", "Имя", "Отчество", "Группа", "Рожден"], 160),
        "u": box(430, 80, "Успеваемость", ["№Зачетки", "Семестр", "Дисциплины", "ФормаКонтроля", "Оценка", "Дата", "Преподаватель"], 170),
        "d": box(650, 40, "Дисциплины", ["*Дисциплина"], 150, 50),
        "c": box(650, 120, "Формы контроля", ["*Контроль"], 150, 50),
        "o": box(650, 200, "Возможные оценки", ["*Оценка"], 150, 50),
        "t": box(650, 280, "Преподаватели", ["*Код", "Преподаватель"], 150, 60),
    }
    # lines with 1 and infinity
    def link(a, b, ay, by):
        ax = boxes[a][0] + boxes[a][2]
        bx = boxes[b][0]
        d.line([ax, ay, bx, by], fill="#222", width=1)
        d.ellipse([ax - 2, ay - 2, ax + 8, ay + 10], fill="#fff", outline="#222")
        d.text((ax, ay - 1), "1", fill="#000", font=font(10, True))
        d.ellipse([bx - 10, by - 2, bx + 2, by + 12], fill="#fff", outline="#222")
        d.text((bx - 9, by - 1), "∞", fill="#000", font=font(10, True))

    link("g", "s", 60, 100)
    link("s", "u", 55, 100)
    link("d", "u", 55, 130)
    return im


def form_snip(kind="stud"):
    W, H = 520, 360
    im = Image.new("RGB", (W, H), "#ece9d8")
    d = ImageDraw.Draw(im)
    f = font(12)
    f_h = font(12, True)
    d.rectangle([0, 0, W - 1, H - 1], outline="#666")
    d.rectangle([0, 0, W, 24], fill="#d4d0c8")
    d.text((8, 4), "Студенты" if kind == "stud" else ("Успеваемость" if kind == "perf" else "Управляющая"), fill="#000", font=f_h)
    if kind == "stud":
        fields = [
            ("№Зачетки", "ИС-251"),
            ("Фамилия", "Новикова"),
            ("Имя", "Анна"),
            ("Отчество", "Сергеевна"),
            ("Группа", "ИС1-251-ОТ ▼"),
            ("Рожден", "15.05.2005"),
            ("Тел", "89001234567"),
        ]
        y = 40
        for lab, val in fields:
            d.text((20, y), lab, fill="#000", font=f)
            d.rectangle([140, y - 2, 360, y + 18], fill="#fff", outline="#7f9db9")
            d.text((146, y), val, fill="#000", font=f)
            y += 30
        d.rectangle([380, 40, 500, 180], fill="#c0c0c0", outline="#666")
        d.text((410, 100), "Фото", fill="#555", font=f)
    elif kind == "perf":
        d.text((16, 36), "Группа", fill="#000", font=f)
        d.rectangle([80, 34, 220, 54], fill="#fff", outline="#7f9db9")
        d.text((86, 36), "ИС1-251-ОТ ▼", fill="#000", font=f)
        d.rectangle([16, 70, 500, 160], fill="#fff", outline="#888")
        d.text((24, 76), "Студенты группы", fill="#000", font=f_h)
        d.text((24, 100), "ИС-251   Новикова   Анна", fill="#000", font=f)
        d.rectangle([16, 175, 500, 290], fill="#fff", outline="#888")
        d.text((24, 181), "Успеваемость", fill="#000", font=f_h)
        d.text((24, 210), "1  Информатика  Экзамен  5  20.12.2024  Кабанов В.А.", fill="#000", font=f)
        d.rectangle([16, 310, 250, 338], fill="#d4d0c8", outline="#666")
        d.text((28, 316), "Персональные данные студентов", fill="#000", font=font(11))
    else:
        d.rectangle([40, 50, 480, 300], fill="#dfefff", outline="#88a")
        d.text((140, 70), "Успеваемость студентов", fill="#123", font=font(16, True))
        d.text((70, 120), "Группа", fill="#000", font=f)
        d.rectangle([140, 118, 360, 140], fill="#fff", outline="#7f9db9")
        d.text((148, 120), "ИС1-251-ОТ ▼", fill="#000", font=f)
        for i, lab in enumerate(["Студенты группы", "Форма Студенты", "Форма Успеваемость", "Отчет Студенты"]):
            x = 70 + (i % 2) * 180
            y = 170 + (i // 2) * 40
            d.rectangle([x, y, x + 160, y + 28], fill="#ece9d8", outline="#666")
            d.text((x + 12, y + 6), lab, fill="#000", font=font(11))
    return im


def report_snip():
    W, H = 560, 480
    im = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(im)
    f = font(12)
    f_h = font(13, True)
    d.rectangle([0, 0, W - 1, H - 1], outline="#999")
    d.text((210, 16), "Студенты", fill="#000", font=font(16, True))
    from collections import Counter
    y = 50
    for g in sorted({s[4] for s in STUDENTS}):
        d.rectangle([20, y, W - 20, y + 20], fill="#d9e8f5")
        d.text((28, y + 2), f"Группа: {g}", fill="#000", font=f_h)
        y += 26
        n = 0
        for s in STUDENTS:
            if s[4] == g:
                n += 1
                d.text((36, y), f"{n}. {s[0]} — {s[1]} {s[2]} {s[3]}", fill="#000", font=f)
                y += 18
        d.text((W - 220, y), f"В группе: {n}", fill="#333", font=font(11))
        y += 22
    d.text((W - 220, y + 8), f"Всего студентов: {len(STUDENTS)}", fill="#000", font=f_h)
    return im


def save(name, im, seed=None):
    seed = seed or (abs(hash(name)) % 10000)
    im = humanize(im, seed=seed)
    path = OUT / f"{name}.png"
    im.save(path, "PNG")
    print("saved", path.name, im.size)
    return path


# ---- build all ----
# Prefer authentic original snips where available
if (ORIG / "img_15.png").exists():
    # copy originals into some slots to keep real user look
    from shutil import copyfile
    # map a few originals that look user-made
    copyfile(ORIG / "img_15.png", OUT / "t_stud_real.png")

save("t_groups_ctor", constructor([("Группа", "Текстовый", True)], "Группы : таблица"))
save("t_groups", datasheet(["Группа"], [[g] for g in GROUPS], selected=6, title="Группы"))
save("t_disc_ctor", constructor([("Дисциплина", "Текстовый", True)], "Дисциплины : таблица"))
save("t_disc", datasheet(["Дисциплина"], [[d] for d in DISC], selected=1, title="Дисциплины"))
save("t_ctrl_ctor", constructor([("Контроль", "Текстовый", True)], "Формы контроля : таблица"))
save("t_ctrl", datasheet(["Контроль"], [[c] for c in CTRL], selected=0, title="Формы контроля"))
save("t_grades_ctor", constructor([("Оценка", "Текстовый", True)], "Возможные оценки : таблица"))
save("t_grades", datasheet(["Оценка"], [[g] for g in GRADES], selected=4, title="Возможные оценки"))
save("t_teach_ctor", constructor([("Код", "Счетчик", True), ("Преподаватель", "Текстовый", False)], "Преподаватели : таблица"))
save("t_teach", datasheet(["Код", "Преподаватель"], [[str(c), n] for c, n in TEACHERS], selected=0, title="Преподаватели"))
save("t_stud_ctor", constructor([
    ("№Зачетки", "Текстовый", True),
    ("Фамилия", "Текстовый", False),
    ("Имя", "Текстовый", False),
    ("Отчество", "Текстовый", False),
    ("Группа", "Мастер подстановок", False),
    ("Рожден", "Дата/время", False),
    ("Тел", "Текстовый", False),
    ("E-mail", "Гиперссылка", False),
    ("Сайт", "Гиперссылка", False),
    ("Адрес", "Текстовый", False),
    ("Фото", "Поле объекта OLE", False),
], "Студенты : таблица"))
# students datasheet — match real style closely
save("t_stud", datasheet(
    ["№Зачетки", "Фамилия", "Имя", "Отчество", "Группа", "Рожден", "Тел", "E-mail", "Адрес"],
    [list(s) for s in STUDENTS],
    selected=1,
    title=None,
))
save("t_perf_ctor", constructor([
    ("№Зачетки", "Мастер подстановок", False),
    ("Семестр", "Мастер подстановок", False),
    ("Дисциплины", "Мастер подстановок", False),
    ("ФормаКонтроля", "Мастер подстановок", False),
    ("Оценка", "Мастер подстановок", False),
    ("Дата", "Дата/время", False),
    ("Преподаватель", "Мастер подстановок", False),
], "Успеваемость : таблица"))
save("t_perf", datasheet(
    ["Дата", "Преподаватель", "№Зачетки", "Семестр", "Оценка", "Дисциплины", "ФормаКонтроля"],
    [list(p) for p in PERF],
    selected=3,
))
save("sort_filter", datasheet(
    ["№Зачетки", "Фамилия", "Имя", "Отчество", "Группа"],
    [list(s[:5]) for s in sorted(STUDENTS, key=lambda x: (x[1], x[2], x[3]))],
    selected=2,
    title="Студенты (сортировка А→Я)",
))

save("schema", schema_snip())
save("rel_edit", dialog(
    "Изменение связей",
    ["Таблица/запрос: Группы", "Связанная таблица/запрос: Студенты", "Группа   ↔   Группа", "Тип отношения: один-ко-многим"],
    [(True, "Обеспечение целостности данных"), (False, "каскадное обновление связанных полей"), (False, "каскадное удаление связанных записей")],
))
save("rel_cascade_upd", dialog(
    "Изменение связей",
    ["Таблица/запрос: Группы", "Связанная таблица/запрос: Студенты", "Группа   ↔   Группа"],
    [(True, "Обеспечение целостности данных"), (True, "каскадное обновление связанных полей"), (False, "каскадное удаление связанных записей")],
))
save("rel_cascade_del", dialog(
    "Изменение связей",
    ["Таблица/запрос: Группы", "Связанная таблица/запрос: Студенты", "Группа   ↔   Группа"],
    [(True, "Обеспечение целостности данных"), (False, "каскадное обновление связанных полей"), (True, "каскадное удаление связанных записей")],
))

save("q_select", query_grid([
    {"field": "Группа", "table": "Группы", "show": True},
    {"field": "№Зачетки", "table": "Студенты", "show": True},
    {"field": "Фамилия", "table": "Студенты", "sort": "По возрастанию", "show": True},
    {"field": "Имя", "table": "Студенты", "show": True},
], "Список студентов"))
# also a result snip under same name variant - combine
qsel = query_grid([
    {"field": "Группа", "table": "Группы", "show": True},
    {"field": "№Зачетки", "table": "Студенты", "show": True},
    {"field": "Фамилия", "table": "Студенты", "sort": "По возрастанию", "show": True},
    {"field": "Имя", "table": "Студенты", "show": True},
], "Список студентов")
res = datasheet(
    ["Группа", "№Зачетки", "Фамилия", "Имя"],
    [[s[4], s[0], s[1], s[2]] for s in STUDENTS],
    selected=0,
)
combo = Image.new("RGB", (max(qsel.width, res.width), qsel.height + res.height + 8), "#c8c8c8")
combo.paste(qsel, (0, 0))
combo.paste(res, (0, qsel.height + 8))
save("q_select", combo)

save("q_param", query_grid([
    {"field": "Группа", "table": "Группы", "criteria": "[Введите группу]", "show": True},
    {"field": "№Зачетки", "table": "Студенты", "show": True},
    {"field": "Фамилия", "table": "Студенты", "show": True},
    {"field": "Имя", "table": "Студенты", "show": True},
], "Список Студентов1"))
save("q_param_dialog", dialog("Введите значение параметра", ["Введите группу", "", "ИС1-251-ОТ"], width=360))
save("q_unmatched", query_grid([
    {"field": "Группы.*", "table": "Группы", "show": True},
    {"field": "Группа", "table": "Студенты", "criteria": "Is Null", "show": False},
], "Группы без студентов"))
save("q_dup", datasheet(
    ["№Зачетки", "Семестр", "Дисциплины", "Оценка", "Количество"],
    [["—", "—", "—", "—", "повторов нет"]],
    selected=-1,
    show_plus=False,
    title="Поиск повторяющихся записей",
))
save("q_multi", query_grid([
    {"field": "Группа", "table": "Группы", "show": True},
    {"field": "№Зачетки", "table": "Успеваемость", "show": True},
    {"field": "Фамилия", "table": "Студенты", "show": True},
    {"field": "Имя", "table": "Студенты", "show": True},
    {"field": "Семестр", "table": "Успеваемость", "show": True},
    {"field": "Дисциплины", "table": "Успеваемость", "show": True},
    {"field": "Оценка", "table": "Успеваемость", "show": True},
], "Успеваемость студентов"))
stud_map = {s[0]: s for s in STUDENTS}
multi_rows = []
for d, t, z, s, o, di, f in PERF:
    st = stud_map.get(z)
    if st:
        multi_rows.append([st[4], z, st[1], st[2], s, di, o, t])
save("q_multi_res", datasheet(
    ["Группа", "№Зачетки", "Фамилия", "Имя", "Семестр", "Дисциплины", "Оценка", "Преподаватель"],
    multi_rows,
    selected=2,
))
save("q_xtab", query_grid([
    {"field": "Дисциплины", "table": "Успеваемость студ…", "total": "Группировка", "xtab": "Заголовки строк", "show": True},
    {"field": "Фамилия", "table": "Успеваемость студ…", "total": "Группировка", "xtab": "Заголовки столбцов", "show": True},
    {"field": "Оценка", "table": "Успеваемость студ…", "total": "First", "xtab": "Значение", "show": True},
], "перекрестный"))
fams = sorted({stud_map[z][1] for _, _, z, *_ in PERF if z in stud_map})
discs = sorted({di for *_, di, __ in [(a, b, c, d, e, f, g) for a, b, c, d, e, f, g in PERF]})
cell = {}
for d0, t, z, s, o, di, f0 in PERF:
    st = stud_map.get(z)
    if st:
        cell[(di, st[1])] = o
xtab_rows = [[di] + [cell.get((di, fam), "") for fam in fams] for di in discs]
save("q_xtab_res", datasheet(["Дисциплины"] + fams, xtab_rows, selected=0, show_plus=False))

from collections import Counter
cnt = Counter(s[4] for s in STUDENTS)
qg = query_grid([
    {"field": "Группа", "table": "Группы", "total": "Группировка", "show": True},
    {"field": "№Зачетки", "table": "Студенты", "total": "Count", "show": True},
], "Кол-во студентов")
qr = datasheet(["Группа", "Count-№Зачетки"], [[g, str(c)] for g, c in sorted(cnt.items())], selected=-1, show_plus=False)
combo = Image.new("RGB", (max(qg.width, qr.width), qg.height + qr.height + 6), "#c0c0c0")
combo.paste(qg, (0, 0))
combo.paste(qr, (0, qg.height + 6))
save("q_group", combo)

save("q_date", query_grid([
    {"field": "№Зачетки", "table": "Студенты", "show": True},
    {"field": "Фамилия", "table": "Студенты", "show": True},
    {"field": "Имя", "table": "Студенты", "show": True},
    {"field": "Рожден", "table": "Студенты", "criteria": ">=#01.01.1995# And <=#01.01.2006#", "show": True},
    {"field": "Группа", "table": "Студенты", "show": True},
], "Студенты по дате"))
save("q_fio", query_grid([
    {"field": 'ФИО: [Фамилия] & " " & Left([Имя];1) & "."', "table": "", "sort": "По возрастанию", "show": True},
    {"field": "Группа", "table": "Студенты", "show": True},
], "ФИО"))
save("q_group_students", query_grid([
    {"field": "Группа", "table": "Студенты", "criteria": "=[Forms]![Управляющая]![Выберите группу]", "show": True},
    {"field": "№Зачетки", "table": "Студенты", "show": True},
    {"field": "Фамилия", "table": "Студенты", "sort": "По возрастанию", "show": True},
    {"field": "Имя", "table": "Студенты", "show": True},
    {"field": "Отчество", "table": "Студенты", "show": True},
], "Студенты группы"))

save("f_stud", form_snip("stud"))
save("f_perf", form_snip("perf"))
save("f_ctrl", form_snip("ctrl"))
save("r_stud", report_snip())
save("r_perf", datasheet(
    ["Группа", "Фамилия", "Имя", "Семестр", "Дисциплины", "Оценка", "Преподаватель"],
    [[r[0], r[2], r[3], r[4], r[5], r[6], r[7]] for r in multi_rows],
    selected=1,
    title="Отчет: Успеваемость студентов",
))

print("DONE", len(list(OUT.glob('*.png'))))
