#!/usr/bin/env python3
"""Generate Access-like HTML mock pages from real lab3.accdb data."""
from pathlib import Path
import html

OUT = Path(__file__).parent
CSS = (OUT / "access_theme.css").read_text(encoding="utf-8")

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
    ("1э/2013", "Федоров", "Федор", "Федорыч", "1224", "01.07.1996", "89489438945"),
    ("9\\2982", "Крапивко", "Ольга", "Александравна", "1761", "14.04.2009", "85989478838"),
    ("1ю/2013", "Гирявенко", "Александра", "Ивановна", "СП13Ю-24", "28.09.2000", "8959499440"),
    ("10\\2818", "Миров", "Андрей", "Валерьевич", "СП13Ю-25В", "12.03.2006", "896956956"),
    ("57\\1339", "Валентинов", "Валентин", "Валентинович", "2763", "06.06.2006", "89696999934"),
    ("16\\201", "Тыщенко", "Валерия", "Артёмовна", "СП13Э-21", "19.03.2003", "8937827189"),
    ("ИС-251", "Новикова", "Анна", "Сергеевна", "ИС1-251-ОТ", "15.05.2005", "89001234567"),
]
PERF = [
    ("05.05.2007", 4, "9\\2982", 6, "незачтено", "Философия", "Экзамен"),
    ("07.09.2008", 4, "1ю/2013", 4, "неявка", "ИТ в юридической деятельности", "Экзамен"),
    ("02.12.2001", 1, "57\\1339", 5, "3", "Логика", "Экзамен"),
    ("19.08.2013", 1, "10\\2818", 1, "2", "Информатика", "ДифЗачет"),
    ("29.09.2009", 2, "16\\201", 2, "5", "Иностранный язык в сфере юриспруденции", "Зачет"),
    ("20.08.2010", 3, "1э/2013", 3, "зачтено", "История отеч. государства и права", "Зачет"),
    ("20.12.2024", 1, "ИС-251", 1, "5", "Информатика", "Экзамен"),
]
TEACH = {c: n for c, n in TEACHERS}


def esc(x):
    return html.escape(str(x))


def shell(title, nav_active, body, extra_nav=None):
    objs = {
        "Таблицы": ["Группы", "Дисциплины", "Формы контроля", "Возможные оценки",
                    "Преподаватели", "Студенты", "Успеваемость"],
        "Запросы": ["Список студентов", "Список Студентов1", "Группы без студентов",
                    "Повторы Успеваемость", "Успеваемость студентов",
                    "Успеваемость студентов_перекрестный", "Кол-во студентов",
                    "Студенты по дате", "ФИО студентов", "Студенты группы"],
        "Формы": ["Студенты", "Успеваемость", "Управляющая"],
        "Отчеты": ["Студенты", "Успеваемость студентов"],
    }
    if extra_nav:
        for k, v in extra_nav.items():
            objs[k] = v
    nav = []
    for sec, items in objs.items():
        nav.append(f"<h4>{esc(sec)}</h4>")
        for it in items:
            cls = "obj active" if it == nav_active else "obj"
            nav.append(f'<div class="{cls}">{esc(it)}</div>')
    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<title>{esc(title)}</title><style>{CSS}</style></head><body>
<div class="access-window">
  <div class="titlebar"><span>Microsoft Access — Успеваемость студентов : База данных (Access 2010)</span>
    <span class="btns"><span>_</span><span>□</span><span>×</span></span></div>
  <div class="ribbon">
    <div class="tabs">
      <span class="tab">Файл</span>
      <span class="tab active">Главная</span>
      <span class="tab">Создание</span>
      <span class="tab">Внешние данные</span>
      <span class="tab">Работа с базами данных</span>
    </div>
    <div class="group">Буфер обмена</div>
    <div class="group">Сортировка и фильтр</div>
    <div class="group">Записи</div>
  </div>
  <div class="workspace">
    <div class="nav">{''.join(nav)}</div>
    <div class="main">{body}</div>
  </div>
</div></body></html>"""


def datasheet(name, headers, rows, selected=0):
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = []
    for i, r in enumerate(rows):
        cls = ' class="selected"' if i == selected else ""
        cells = "".join(f"<td>{esc(c)}</td>" for c in r)
        trs.append(f'<tr{cls}><td class="rownum">{i+1}</td>{cells}</tr>')
    return f"""
    <div class="caption">{esc(name)}</div>
    <table class="datasheet"><tr><th class="rownum"></th>{th}</tr>{''.join(trs)}</table>
    <div class="note">Записей: {len(rows)}</div>"""


def ctor(name, fields):
    # fields: list of (name, type, size, key)
    rows = []
    for fname, ftype, size, key in fields:
        k = "🔑" if key else ""
        rows.append(f"<tr><td class='keycell'>{k}</td><td>{esc(fname)}</td><td>{esc(ftype)}</td><td>{esc(size)}</td></tr>")
    return f"""
    <div class="caption">{esc(name)} — Конструктор</div>
    <table class="ctor">
      <tr><th></th><th>Имя поля</th><th>Тип данных</th><th>Описание</th></tr>
      {''.join(rows)}
    </table>
    <div class="props"><div class="ph">Свойства поля</div>
      <table><tr><td>Размер поля</td><td>{esc(fields[0][2] if fields else '')}</td></tr>
      <tr><td>Обязательное поле</td><td>Да</td></tr>
      <tr><td>Индексированное поле</td><td>Да (Совпадения не допускаются)</td></tr></table>
    </div>"""


def query_design(title, tables, columns):
    # tables: [(name, fields, key)]
    # columns: [(field, table, sort, show, criteria, total, crosstab)]
    boxes = []
    for tname, fields, key in tables:
        fl = "".join(
            f"<div class='field{' key' if f==key else ''}'>{esc(f)}</div>" for f in fields
        )
        boxes.append(f"<div class='table-box'><div class='thead'>{esc(tname)}</div>{fl}</div>")
    labels = ["Поле", "Имя таблицы", "Сортировка", "Вывод на экран", "Условие отбора"]
    extras = []
    if any(c[5] for c in columns):
        labels.insert(2, "Групповая операция")
        extras.append("total")
    if any(c[6] for c in columns):
        labels.append("Перекрестная таблица")
        extras.append("xtab")
    head = "".join(f"<th>{esc(h)}</th>" for h in [" "] + [c[0] for c in columns])
    rows_html = []
    row_defs = [
        ("Поле", lambda c: c[0]),
        ("Имя таблицы", lambda c: c[1]),
    ]
    if "total" in extras:
        row_defs.append(("Групповая операция", lambda c: c[5] or ""))
    row_defs += [
        ("Сортировка", lambda c: c[2] or ""),
        ("Вывод на экран", lambda c: "☑" if c[3] else "☐"),
        ("Условие отбора", lambda c: c[4] or ""),
    ]
    if "xtab" in extras:
        row_defs.append(("Перекрестная таблица", lambda c: c[6] or ""))
    for label, fn in row_defs:
        cells = "".join(f"<td>{esc(fn(c))}</td>" for c in columns)
        rows_html.append(f"<tr><th>{esc(label)}</th>{cells}</tr>")
    return f"""
    <div class="caption">{esc(title)} — Конструктор запросов</div>
    <div class="design-area">{''.join(boxes)}</div>
    <table class="design-grid">{''.join(rows_html)}</table>"""


pages = {}

# --- Tables constructor / datasheet ---
pages["t_groups_ctor"] = shell("Группы", "Группы", ctor("Группы", [
    ("Группа", "Текстовый", "10", True),
]))
pages["t_groups"] = shell("Группы", "Группы", datasheet("Группы", ["Группа"], [[g] for g in GROUPS]))

pages["t_disc_ctor"] = shell("Дисциплины", "Дисциплины", ctor("Дисциплины", [
    ("Дисциплина", "Текстовый", "100", True),
]))
pages["t_disc"] = shell("Дисциплины", "Дисциплины", datasheet("Дисциплины", ["Дисциплина"], [[d] for d in DISC]))

pages["t_ctrl_ctor"] = shell("Формы контроля", "Формы контроля", ctor("Формы контроля", [
    ("Контроль", "Текстовый", "20", True),
]))
pages["t_ctrl"] = shell("Формы контроля", "Формы контроля", datasheet("Формы контроля", ["Контроль"], [[c] for c in CTRL]))

pages["t_grades_ctor"] = shell("Возможные оценки", "Возможные оценки", ctor("Возможные оценки", [
    ("Оценка", "Текстовый", "20", True),
]))
pages["t_grades"] = shell("Возможные оценки", "Возможные оценки", datasheet("Возможные оценки", ["Оценка"], [[g] for g in GRADES]))

pages["t_teach_ctor"] = shell("Преподаватели", "Преподаватели", ctor("Преподаватели", [
    ("Код", "Счетчик", "Длинное целое", True),
    ("Преподаватель", "Текстовый", "100", False),
]))
pages["t_teach"] = shell("Преподаватели", "Преподаватели", datasheet(
    "Преподаватели", ["Код", "Преподаватель"], [[c, n] for c, n in TEACHERS]))

pages["t_stud_ctor"] = shell("Студенты", "Студенты", ctor("Студенты", [
    ("№Зачетки", "Текстовый", "255", True),
    ("Фамилия", "Текстовый", "255", False),
    ("Имя", "Текстовый", "255", False),
    ("Отчество", "Текстовый", "255", False),
    ("Группа", "Текстовый (мастер подстановок)", "10", False),
    ("Рожден", "Дата/время", "", False),
    ("Тел", "Текстовый", "255", False),
    ("E-mail", "Гиперссылка", "", False),
    ("Сайт", "Гиперссылка", "", False),
    ("Адрес", "Текстовый", "255", False),
    ("Фото", "Поле объекта OLE", "", False),
]) + """
<div class="props"><div class="ph">Подстановка — поле «Группа»</div>
<table>
<tr><td>Тип элемента управления</td><td>Поле со списком</td></tr>
<tr><td>Тип источника строк</td><td>Таблица/запрос</td></tr>
<tr><td>Источник строк</td><td>SELECT Группы.Группа FROM Группы ORDER BY Группа;</td></tr>
<tr><td>Присоединенный столбец</td><td>1</td></tr>
</table></div>""")

pages["t_stud"] = shell("Студенты", "Студенты", datasheet(
    "Студенты",
    ["№Зачетки", "Фамилия", "Имя", "Отчество", "Группа", "Рожден", "Тел"],
    [list(s) for s in STUDENTS],
))

pages["t_perf_ctor"] = shell("Успеваемость", "Успеваемость", ctor("Успеваемость", [
    ("№Зачетки", "Текстовый (подстановка)", "255", False),
    ("Семестр", "Числовой (список 1–10)", "", False),
    ("Дисциплины", "Текстовый (подстановка)", "100", False),
    ("ФормаКонтроля", "Текстовый (подстановка)", "20", False),
    ("Оценка", "Текстовый (подстановка)", "50", False),
    ("Дата", "Дата/время", "", False),
    ("Преподаватель", "Числовой (подстановка)", "", False),
]))

pages["t_perf"] = shell("Успеваемость", "Успеваемость", datasheet(
    "Успеваемость",
    ["Дата", "Преподаватель", "№Зачетки", "Семестр", "Оценка", "Дисциплины", "ФормаКонтроля"],
    [[d, TEACH[t], z, s, o, di, f] for d, t, z, s, o, di, f in PERF],
))

# Schema
schema_body = """
<div class="caption">Схема данных</div>
<div class="design-area" style="min-height:360px">
  <div class="table-box"><div class="thead">Группы</div><div class="field key">Группа</div></div>
  <div class="table-box"><div class="thead">Студенты</div>
    <div class="field key">№Зачетки</div><div class="field">Фамилия</div><div class="field">Имя</div>
    <div class="field">Отчество</div><div class="field">Группа</div><div class="field">Рожден</div>
  </div>
  <div class="table-box"><div class="thead">Успеваемость</div>
    <div class="field">№Зачетки</div><div class="field">Семестр</div><div class="field">Дисциплины</div>
    <div class="field">ФормаКонтроля</div><div class="field">Оценка</div><div class="field">Дата</div>
    <div class="field">Преподаватель</div>
  </div>
  <div class="table-box"><div class="thead">Дисциплины</div><div class="field key">Дисциплина</div></div>
  <div class="table-box"><div class="thead">Формы контроля</div><div class="field key">Контроль</div></div>
  <div class="table-box"><div class="thead">Возможные оценки</div><div class="field key">Оценка</div></div>
  <div class="table-box"><div class="thead">Преподаватели</div><div class="field key">Код</div><div class="field">Преподаватель</div></div>
  <div class="rel-line">Группы.Группа <span class="badge">1</span> ——— <span class="badge">∞</span> Студенты.Группа (целостность)</div>
  <div class="rel-line">Студенты.№Зачетки <span class="badge">1</span> ——— <span class="badge">∞</span> Успеваемость.№Зачетки (целостность)</div>
  <div class="rel-line">Дисциплины / Формы контроля / Оценки / Преподаватели → Успеваемость (1:∞, целостность)</div>
</div>"""
pages["schema"] = shell("Схема данных", "Группы", schema_body)

pages["rel_edit"] = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><style>""" + CSS + """</style></head>
<body style="background:#c7d3e0;padding:40px">
<div class="dialog"><div class="dh">Изменение связей</div><div class="db">
<div class="row">Таблица/запрос: <b>Группы</b> &nbsp;&nbsp; Связанная таблица: <b>Студенты</b></div>
<div class="row">Группа &nbsp;↔&nbsp; Группа</div>
<div class="row"><label><input type="checkbox" checked> Обеспечение целостности данных</label></div>
<div class="row"><label><input type="checkbox"> каскадное обновление связанных полей</label></div>
<div class="row"><label><input type="checkbox"> каскадное удаление связанных записей</label></div>
<div class="row">Тип отношения: <b>один-ко-многим</b></div>
<div class="actions"><button>ОК</button><button>Отмена</button><button>Применить</button></div>
</div></div></body></html>"""

pages["rel_cascade_upd"] = pages["rel_edit"].replace(
    '> каскадное обновление', ' checked> каскадное обновление')
pages["rel_cascade_del"] = pages["rel_edit"].replace(
    '> каскадное удаление', ' checked> каскадное удаление')

# Queries
pages["q_select"] = shell("Список студентов", "Список студентов", query_design(
    "Список студентов",
    [("Группы", ["Группа"], "Группа"),
     ("Студенты", ["№Зачетки", "Фамилия", "Имя", "Отчество", "Группа"], "№Зачетки")],
    [("Группа", "Группы", "", True, "", "", ""),
     ("№Зачетки", "Студенты", "", True, "", "", ""),
     ("Фамилия", "Студенты", "По возрастанию", True, "", "", ""),
     ("Имя", "Студенты", "", True, "", "", "")],
) + datasheet("Результат", ["Группа", "№Зачетки", "Фамилия", "Имя"],
              [[s[4], s[0], s[1], s[2]] for s in STUDENTS]))

pages["q_param"] = shell("Список Студентов1", "Список Студентов1", query_design(
    "Список Студентов1 (с параметром)",
    [("Группы", ["Группа"], "Группа"),
     ("Студенты", ["№Зачетки", "Фамилия", "Имя", "Группа"], "№Зачетки")],
    [("Группа", "Группы", "", True, "[Введите группу]", "", ""),
     ("№Зачетки", "Студенты", "", True, "", "", ""),
     ("Фамилия", "Студенты", "", True, "", "", ""),
     ("Имя", "Студенты", "", True, "", "", "")],
))

pages["q_param_dialog"] = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><style>""" + CSS + """</style></head>
<body style="background:#c7d3e0;padding:80px">
<div class="dialog"><div class="dh">Введите значение параметра</div><div class="db">
<div class="row">Введите группу</div>
<div class="row"><input style="width:100%;padding:4px" value="ИС1-251-ОТ"></div>
<div class="actions"><button>ОК</button><button>Отмена</button></div>
</div></div></body></html>"""

pages["q_unmatched"] = shell("Группы без студентов", "Группы без студентов", query_design(
    "Группы без студентов",
    [("Группы", ["Группа"], "Группа"),
     ("Студенты", ["№Зачетки", "Группа"], "№Зачетки")],
    [("Группы.*", "Группы", "", True, "", "", ""),
     ("Группа", "Студенты", "", False, "Is Null", "", "")],
) + datasheet("Результат (пример при наличии пустой группы 9999)", ["Группа"], [["9999"]]))

pages["q_dup"] = shell("Повторы Успеваемость", "Повторы Успеваемость",
    datasheet("Поиск повторяющихся записей — Успеваемость",
              ["№Зачетки", "Семестр", "Дисциплины", "Оценка", "Количество"],
              [["—", "—", "—", "—", "повторов не найдено"]]))

pages["q_multi"] = shell("Успеваемость студентов", "Успеваемость студентов", query_design(
    "Успеваемость студентов",
    [("Группы", ["Группа"], "Группа"),
     ("Студенты", ["№Зачетки", "Фамилия", "Имя", "Группа"], "№Зачетки"),
     ("Успеваемость", ["№Зачетки", "Семестр", "Дисциплины", "ФормаКонтроля", "Оценка", "Дата", "Преподаватель"], "")],
    [("Группа", "Группы", "", True, "", "", ""),
     ("№Зачетки", "Успеваемость", "", True, "", "", ""),
     ("Фамилия", "Студенты", "", True, "", "", ""),
     ("Имя", "Студенты", "", True, "", "", ""),
     ("Семестр", "Успеваемость", "", True, "", "", ""),
     ("Дисциплины", "Успеваемость", "", True, "", "", ""),
     ("ФормаКонтроля", "Успеваемость", "", True, "", "", ""),
     ("Оценка", "Успеваемость", "", True, "", "", ""),
     ("Дата", "Успеваемость", "", True, "", "", ""),
     ("Преподаватель", "Успеваемость", "", True, "", "", "")],
))

# Result of multi
stud_map = {s[0]: s for s in STUDENTS}
multi_rows = []
for d, t, z, s, o, di, f in PERF:
    st = stud_map.get(z)
    if st:
        multi_rows.append([st[4], z, st[1], st[2], s, di, f, o, d, TEACH[t]])
pages["q_multi_res"] = shell("Успеваемость студентов", "Успеваемость студентов", datasheet(
    "Успеваемость студентов — режим таблицы",
    ["Группа", "№Зачетки", "Фамилия", "Имя", "Семестр", "Дисциплины", "ФормаКонтроля", "Оценка", "Дата", "Преподаватель"],
    multi_rows,
))

# Crosstab
pages["q_xtab"] = shell("перекрестный", "Успеваемость студентов_перекрестный", query_design(
    "Успеваемость студентов_перекрестный",
    [("Успеваемость студентов", ["Дисциплины", "Фамилия", "Оценка", "Группа"], "")],
    [("Дисциплины", "Успеваемость студентов", "", True, "", "Группировка", "Заголовки строк"),
     ("Фамилия", "Успеваемость студентов", "", True, "", "Группировка", "Заголовки столбцов"),
     ("Оценка", "Успеваемость студентов", "", True, "", "First", "Значение")],
))

# Build crosstab result roughly
fams = sorted({stud_map[z][1] for _, _, z, *_ in PERF if z in stud_map})
discs = sorted({di for *_, di, __ in [(a,b,c,d,e,f,g) for a,b,c,d,e,f,g in PERF]})
# map (disc, fam) -> grade
cell = {}
for d, t, z, s, o, di, f in PERF:
    st = stud_map.get(z)
    if st:
        cell[(di, st[1])] = o
xtab_rows = []
for di in discs:
    xtab_rows.append([di] + [cell.get((di, fam), "") for fam in fams])
pages["q_xtab_res"] = shell("перекрестный", "Успеваемость студентов_перекрестный", datasheet(
    "Перекрестный запрос — результат",
    ["Дисциплины"] + fams,
    xtab_rows,
))

# Grouping
from collections import Counter
cnt = Counter(s[4] for s in STUDENTS)
pages["q_group"] = shell("Кол-во студентов", "Кол-во студентов", query_design(
    "Количество студентов в группах",
    [("Группы", ["Группа"], "Группа"), ("Студенты", ["№Зачетки", "Группа"], "№Зачетки")],
    [("Группа", "Группы", "", True, "", "Группировка", ""),
     ("№Зачетки", "Студенты", "", True, "", "Count", "")],
) + datasheet("Результат", ["Группа", "Count-№Зачетки"], [[g, c] for g, c in sorted(cnt.items())]))

pages["q_date"] = shell("Студенты по дате", "Студенты по дате", query_design(
    "Студенты по дате рождения",
    [("Студенты", ["№Зачетки", "Фамилия", "Имя", "Рожден", "Группа"], "№Зачетки")],
    [("№Зачетки", "Студенты", "", True, "", "", ""),
     ("Фамилия", "Студенты", "", True, "", "", ""),
     ("Имя", "Студенты", "", True, "", "", ""),
     ("Рожден", "Студенты", "", True, ">=#01.01.1995# And <=#01.01.2006#", "", ""),
     ("Группа", "Студенты", "", True, "", "", "")],
))

pages["q_fio"] = shell("ФИО студентов", "ФИО студентов", query_design(
    "ФИО (вычисляемое поле)",
    [("Студенты", ["Фамилия", "Имя", "Отчество", "Группа"], "№Зачетки")],
    [('ФИО: [Фамилия] & " " & Left([Имя];1) & "." & Left([Отчество];1) & "."', "Студенты", "По возрастанию", True, "", "", ""),
     ("Группа", "Студенты", "", True, "", "", "")],
) + datasheet("Результат", ["ФИО", "Группа"],
              [[f"{s[1]} {s[2][0]}.{s[3][0]}.", s[4]] for s in STUDENTS]))

pages["q_group_students"] = shell("Студенты группы", "Студенты группы", query_design(
    "Студенты группы",
    [("Студенты", ["Группа", "№Зачетки", "Фамилия", "Имя", "Отчество"], "№Зачетки")],
    [("Группа", "Студенты", "", True, "=[Forms]![Управляющая]![Выберите группу]", "", ""),
     ("№Зачетки", "Студенты", "", True, "", "", ""),
     ("Фамилия", "Студенты", "По возрастанию", True, "", "", ""),
     ("Имя", "Студенты", "", True, "", "", ""),
     ("Отчество", "Студенты", "", True, "", "", "")],
))

# Forms
form_stud = """
<div class="caption">Форма «Студенты»</div>
<div class="form-ui">
  <div><label>№Зачетки</label><input value="ИС-251"></div>
  <div><label>Фамилия</label><input value="Новикова"></div>
  <div><label>Имя</label><input value="Анна"></div>
  <div><label>Отчество</label><input value="Сергеевна"></div>
  <div><label>Группа</label><select><option>ИС1-251-ОТ</option></select></div>
  <div><label>Рожден</label><input value="15.05.2005"></div>
  <div><label>Тел</label><input value="89001234567"></div>
  <div style="margin-top:10px;width:140px;height:160px;border:1px solid #888;background:#ddd;display:inline-block;text-align:center;line-height:160px;color:#666">Фото</div>
  <div><span class="btn">◀</span><span class="btn">▶</span><span class="btn">Новая запись</span></div>
</div>"""
pages["f_stud"] = shell("Форма Студенты", "Студенты", form_stud)

form_perf = """
<div class="caption">Форма «Успеваемость» (главная + подчиненные)</div>
<div class="form-ui" style="max-width:900px">
  <div><label>Группа</label><select><option>ИС1-251-ОТ</option><option>1224</option></select></div>
  <fieldset style="margin-top:10px;border:1px solid #999;padding:10px">
    <legend>Студенты группы</legend>
    <table class="datasheet"><tr><th>№Зачетки</th><th>Фамилия</th><th>Имя</th></tr>
    <tr class="selected"><td>ИС-251</td><td>Новикова</td><td>Анна</td></tr></table>
  </fieldset>
  <fieldset style="margin-top:10px;border:1px solid #999;padding:10px">
    <legend>Успеваемость студента</legend>
    <table class="datasheet"><tr><th>Семестр</th><th>Дисциплины</th><th>Форма</th><th>Оценка</th><th>Дата</th><th>Преподаватель</th></tr>
    <tr><td>1</td><td>Информатика</td><td>Экзамен</td><td>5</td><td>20.12.2024</td><td>Кабанов В.А.</td></tr></table>
  </fieldset>
  <div><span class="btn">Персональные данные студентов</span><span class="btn">Закрыть</span></div>
</div>"""
pages["f_perf"] = shell("Форма Успеваемость", "Успеваемость", form_perf)

form_ctrl = """
<div class="caption">Управляющая форма</div>
<div class="form-ui" style="background:linear-gradient(#e8f0ff,#d5e4f5);max-width:520px">
  <h3 style="margin-top:0;text-align:center">Успеваемость студентов</h3>
  <div><label>Группа</label><select id="g"><option>Выберите группу</option>
  """ + "".join(f"<option>{esc(g)}</option>" for g in GROUPS) + """</select></div>
  <div style="margin-top:14px">
    <span class="btn">Студенты группы</span>
    <span class="btn">Форма Студенты</span>
    <span class="btn">Форма Успеваемость</span>
  </div>
  <div style="margin-top:8px">
    <span class="btn">Отчет Студенты</span>
    <span class="btn">Отчет Успеваемость</span>
    <span class="btn">Выход</span>
  </div>
  <div class="note">Поле со списком: имя = «Выберите группу». Условие в запросе:
  =[Forms]![Управляющая]![Выберите группу]</div>
</div>"""
pages["f_ctrl"] = shell("Управляющая", "Управляющая", form_ctrl)

# Reports
rep_stud = """
<div class="caption">Отчет «Студенты» — предварительный просмотр</div>
<div class="report-preview">
  <h2>Студенты</h2>
"""
for g, c in sorted(cnt.items()):
    rep_stud += f'<div class="group-h">Группа: {esc(g)}</div>'
    i = 0
    for s in STUDENTS:
        if s[4] == g:
            i += 1
            rep_stud += f"<div>{i}. {esc(s[0])} — {esc(s[1])} {esc(s[2])} {esc(s[3])}</div>"
    rep_stud += f'<div class="group-f">Количество студентов в группе: {c}</div>'
rep_stud += f'<div class="group-f" style="margin-top:12px;font-weight:700">Всего студентов: {len(STUDENTS)}</div></div>'
pages["r_stud"] = shell("Отчет Студенты", "Студенты", rep_stud)

rep_perf = """
<div class="caption">Отчет «Успеваемость студентов»</div>
<div class="report-preview"><h2>Успеваемость студентов</h2>
"""
for row in multi_rows:
    rep_perf += (f"<div><b>{esc(row[0])}</b> | {esc(row[2])} {esc(row[3])} | сем.{esc(row[4])} | "
                 f"{esc(row[5])} | {esc(row[6])} | <b>{esc(row[7])}</b> | {esc(row[9])}</div>")
rep_perf += "</div>"
pages["r_perf"] = shell("Отчет Успеваемость", "Успеваемость студентов", rep_perf)

# Sort / filter
pages["sort_filter"] = shell("Студенты", "Студенты", datasheet(
    "Студенты — сортировка по Фамилия, Имя, Отчество (А→Я)",
    ["№Зачетки", "Фамилия", "Имя", "Отчество", "Группа"],
    [list(s[:5]) for s in sorted(STUDENTS, key=lambda x: (x[1], x[2], x[3]))],
) + datasheet(
    "Фильтр: №Зачетки Like \"*э*\"",
    ["№Зачетки", "Фамилия", "Имя", "Группа"],
    [[s[0], s[1], s[2], s[4]] for s in STUDENTS if "э" in s[0].lower() or "э" in s[0]],
))

for name, content in pages.items():
    path = OUT / f"{name}.html"
    path.write_text(content, encoding="utf-8")
    print("wrote", path.name)

print("TOTAL", len(pages))
