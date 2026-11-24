#!/usr/bin/env python3
"""Generate Microsoft Word lab works for two students with different content."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_UNDERLINE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn, nsmap
from docx.shared import Cm, Pt, RGBColor, Twips, Emu
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT

OUT = Path(__file__).resolve().parent

POEM = [
    "Каждый выбирает для себя",
    "Женщину, религию, дорогу.",
    "Дьяволу служить или пророку —",
    "Каждый выбирает для себя.",
    "",
    "Каждый выбирает по себе",
    "Слово для любви и для молитвы.",
    "Шпагу для дуэли, меч для битвы —",
    "Каждый выбирает по себе.",
    "",
    "Каждый выбирает по себе",
    "Щит и латы. Посох и заплаты.",
    "Меру окончательной расплаты —",
    "Каждый выбирает по себе.",
    "",
    "Каждый выбирает для себя.",
    "Выбираю тоже — как умею.",
    "Ни к кому претензий не имею.",
    "Каждый выбирает для себя.",
]


def set_run_font(run, name=None, size=None, bold=None, italic=None, color=None,
                 underline=None, shadow=False, outline=False, spacing=None, position=None):
    if name:
        run.font.name = name
        r = run._element
        rPr = r.get_or_add_rPr()
        rFonts = rPr.get_or_add_rFonts()
        rFonts.set(qn("w:ascii"), name)
        rFonts.set(qn("w:hAnsi"), name)
        rFonts.set(qn("w:eastAsia"), name)
        rFonts.set(qn("w:cs"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = color
    if underline is not None:
        run.font.underline = underline
    if shadow:
        run.font.shadow = True
    if outline:
        # outline effect via rPr
        rPr = run._element.get_or_add_rPr()
        outline_el = OxmlElement("w:outline")
        rPr.append(outline_el)
    if spacing is not None:
        # character spacing in twips (1 pt = 20 twips); python-docx uses Pt via font
        rPr = run._element.get_or_add_rPr()
        spacing_el = rPr.find(qn("w:spacing"))
        if spacing_el is None:
            spacing_el = OxmlElement("w:spacing")
            rPr.append(spacing_el)
        spacing_el.set(qn("w:val"), str(int(spacing * 20)))  # spacing in twips-ish: Word uses 20ths of a point
    if position is not None:
        rPr = run._element.get_or_add_rPr()
        pos = OxmlElement("w:position")
        pos.set(qn("w:val"), str(int(position * 2)))  # half-points
        rPr.append(pos)


def set_paragraph_format(p, align=None, space_before=None, space_after=None,
                         left_indent=None, first_line=None, line_spacing=1.0):
    pf = p.paragraph_format
    if align is not None:
        pf.alignment = align
    if space_before is not None:
        pf.space_before = Pt(space_before)
    if space_after is not None:
        pf.space_after = Pt(space_after)
    if left_indent is not None:
        pf.left_indent = Cm(left_indent)
    if first_line is not None:
        pf.first_line_indent = Cm(first_line)
    if line_spacing is not None:
        pf.line_spacing = line_spacing


def set_page_margins(section, top=2, bottom=2, left=2, right=1):
    section.top_margin = Cm(top)
    section.bottom_margin = Cm(bottom)
    section.left_margin = Cm(left)
    section.right_margin = Cm(right)
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.orientation = WD_ORIENT.PORTRAIT


def add_page_number(paragraph):
    """Insert PAGE field centered."""
    run = paragraph.add_run()
    fldChar1 = OxmlElement("w:fldChar")
    fldChar1.set(qn("w:fldCharType"), "begin")
    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = " PAGE "
    fldChar2 = OxmlElement("w:fldChar")
    fldChar2.set(qn("w:fldCharType"), "end")
    run._r.append(fldChar1)
    run._r.append(instrText)
    run._r.append(fldChar2)


def set_different_first_page(section, value=True):
    sectPr = section._sectPr
    titlePg = sectPr.find(qn("w:titlePg"))
    if value:
        if titlePg is None:
            titlePg = OxmlElement("w:titlePg")
            sectPr.append(titlePg)
    else:
        if titlePg is not None:
            sectPr.remove(titlePg)


def add_page_border(section, color="0000FF", sz="24"):
    """Add page border via sectPr pgBorders."""
    sectPr = section._sectPr
    pgBorders = OxmlElement("w:pgBorders")
    pgBorders.set(qn("w:offsetFrom"), "page")
    for edge in ("top", "left", "bottom", "right"):
        border = OxmlElement(f"w:{edge}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), sz)
        border.set(qn("w:space"), "24")
        border.set(qn("w:color"), color)
        pgBorders.append(border)
    # remove existing
    existing = sectPr.find(qn("w:pgBorders"))
    if existing is not None:
        sectPr.remove(existing)
    sectPr.append(pgBorders)


def shade_cell(cell, color_hex):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color_hex)
    shd.set(qn("w:val"), "clear")
    tcPr.append(shd)


def set_cell_text(cell, text, font="Times New Roman", size=11, bold=False,
                  align=WD_ALIGN_PARAGRAPH.CENTER, color=None):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    run = p.add_run(text)
    set_run_font(run, name=font, size=size, bold=bold, color=color)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def add_heading_run(p, text, **kwargs):
    run = p.add_run(text)
    set_run_font(run, **kwargs)
    return run


# ---------------------------------------------------------------------------
# Student configs (different content)
# ---------------------------------------------------------------------------

GLEB = {
    "folder": "Radonskiy_Gleb",
    "fio": "Радонский Г. А.",
    "fio_full": "Радонский Глеб",
    "group": "ОАгро 1-1",
    "header_lab1_title": "Ю. Левитанский. Каждый выбирает для себя",
    "wingding_colors": [RGBColor(0x1F, 0x77, 0xB4), RGBColor(0xD6, 0x27, 0x28)],
    "border_color": "2E86AB",
    "devices_title": "Основные устройства компьютера:",
    "devices": ["системный блок;", "монитор;", "клавиатура;", "мышь."],
    "sites": [
        ("Социальная сеть:", ["https://vk.com", "https://ok.ru"]),
        ("Музыка:", ["https://music.yandex.ru", "https://open.spotify.com"]),
        ("Картинки:", ["https://www.pinterest.com", "https://unsplash.com"]),
        ("Видео:", ["https://www.youtube.com", "https://rutube.ru"]),
    ],
    "routes": [
        ("101", "Вокзал — Агротехникум", "07:15", "07:45", 35, 42),
        ("205", "Центр — Ферма «Рассвет»", "08:00", "08:40", 48, 31),
        ("312", "Общежитие — Учебный корпус", "08:20", "08:35", 22, 55),
        ("418", "Рынок — Полевая станция", "09:10", "09:55", 55, 18),
    ],
    "salary": [
        ("Иванов А.П.", "Агроном", 52000),
        ("Петрова М.С.", "Бухгалтер", 48000),
        ("Сидоров И.К.", "Механик", 45000),
        ("Козлова Е.В.", "Лаборант", 38000),
        ("Морозов Д.Н.", "Инженер", 56000),
    ],
    "style_doc_title": "Введение в информатику",
    "style_sections": [
        ("Введение",
         "Информатика изучает методы хранения, обработки и передачи информации. "
         "В современном мире компьютерная грамотность необходима специалистам любой отрасли, "
         "включая агрономию и переработку сельскохозяйственной продукции."),
        ("Аппаратное обеспечение",
         "Аппаратное обеспечение включает устройства ввода, вывода, хранения и обработки данных. "
         "К основным компонентам относятся процессор, оперативная память, накопители и периферия."),
        ("Программное обеспечение",
         "Программное обеспечение делится на системное, прикладное и инструментальное. "
         "Текстовые процессоры, электронные таблицы и системы управления базами данных "
         "широко применяются в учебной и производственной практике."),
        ("Заключение",
         "Освоение офисных приложений повышает эффективность подготовки документов, "
         "отчётов и расчётов. Практические навыки форматирования и работы со стилями "
         "упрощают оформление курсовых и лабораторных работ."),
    ],
    "footnote_word": "периферия",
    "footnote_text": "Периферия — внешние устройства компьютера (клавиатура, мышь, принтер, сканер и др.).",
    "index_words": [
        "информатика", "компьютер", "процессор", "память", "накопители",
        "периферия", "программное", "системное", "прикладное", "таблицы",
        "документов", "форматирования", "стилей", "агрономию", "практике",
    ],
}


MIKHAIL = {
    "folder": "Frolovichev_Mikhail",
    "fio": "Фроловичев М. И.",
    "fio_full": "Фроловичев Михаил",
    "group": "ОАгро 1-1",
    "header_lab1_title": "Ю. Левитанский. Каждый выбирает для себя",
    "wingding_colors": [RGBColor(0x2C, 0xA0, 0x2C), RGBColor(0x94, 0x67, 0xBD)],
    "border_color": "8B4513",
    "devices_title": "Основные устройства компьютера:",
    "devices": ["системный блок;", "монитор;", "клавиатура;", "мышь."],
    "sites": [
        ("Социальная сеть:", ["https://t.me", "https://www.instagram.com"]),
        ("Музыка:", ["https://vk.com/music", "https://www.zvooq.ru"]),
        ("Картинки:", ["https://www.flickr.com", "https://pixabay.com"]),
        ("Видео:", ["https://www.twitch.tv", "https://www.kinopoisk.ru"]),
    ],
    "routes": [
        ("12", "Село Луговое — Колледж", "06:50", "07:30", 40, 28),
        ("27", "Автостанция — Теплицы", "07:40", "08:25", 52, 36),
        ("33", "Общежитие №2 — Библиотека", "08:05", "08:20", 18, 47),
        ("45", "Стадион — Учебная ферма", "10:00", "10:50", 60, 22),
        ("56", "Почта — Мастерские", "11:15", "11:40", 25, 19),
    ],
    "salary": [
        ("Смирнов В.А.", "Директор", 78000),
        ("Орлова Н.И.", "Главный агроном", 61000),
        ("Кузнецов П.Р.", "Водитель", 42000),
        ("Васильева Т.О.", "Кассир", 35000),
        ("Никитин С.Л.", "Программист", 67000),
        ("Белова А.Ю.", "Секретарь", 33000),
    ],
    "style_doc_title": "Цифровые технологии в агрономии",
    "style_sections": [
        ("Введение",
         "Цифровизация сельского хозяйства меняет подходы к управлению полями, учёту урожая "
         "и контролю качества продукции. Студенты направления ОАгро изучают базовые "
         "инструменты обработки информации уже на первом курсе."),
        ("Сбор и хранение данных",
         "Датчики влажности, GPS-навигация и электронные журналы учёта позволяют накапливать "
         "большие объёмы данных. Важно уметь структурировать информацию и оформлять её "
         "в понятных отчётах."),
        ("Анализ и визуализация",
         "Таблицы и диаграммы помогают сравнивать показатели урожайности, затрат и прибыли. "
         "Грамотное оформление графиков делает выводы наглядными для преподавателя и работодателя."),
        ("Заключение",
         "Навыки работы в текстовом процессоре — фундамент для дальнейшей работы с "
         "специализированными агрономическими программами и системами точного земледелия."),
    ],
    "footnote_word": "урожайности",
    "footnote_text": "Урожайность — количество продукции, полученной с единицы площади посева.",
    "index_words": [
        "Цифровизация", "сельского", "урожая", "данных", "датчики",
        "отчётах", "Таблицы", "диаграммы", "урожайности", "графиков",
        "текстовом", "агрономическими", "земледелия", "информации", "студенты",
    ],
}


def make_lab1(student: dict, out_dir: Path):
    doc = Document()
    section = doc.sections[0]
    set_page_margins(section)
    set_different_first_page(section, True)
    add_page_border(section, color=student["border_color"], sz="24")

    # Title page header empty; primary header for rest
    header = section.header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hr = hp.add_run(student["header_lab1_title"])
    set_run_font(hr, name="Times New Roman", size=12, italic=True)

    first_header = section.first_page_header
    first_header.is_linked_to_previous = False
    # empty first page header (title page)

    footer = section.footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_number(fp)

    first_footer = section.first_page_footer
    first_footer.is_linked_to_previous = False

    # --- Title page ---
    for _ in range(4):
        doc.add_paragraph()
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run("Лабораторная работа №1")
    set_run_font(r, name="Times New Roman", size=18, bold=True)

    t2 = doc.add_paragraph()
    t2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = t2.add_run("Microsoft Office Word.\nНастройки параметров документа.\nВвод, редактирование и форматирование текста")
    set_run_font(r2, name="Times New Roman", size=14)

    for _ in range(6):
        doc.add_paragraph()
    info = doc.add_paragraph()
    info.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    ir = info.add_run(f"Выполнил: {student['fio_full']}\nГруппа: {student['group']}\n{student['fio']}")
    set_run_font(ir, name="Times New Roman", size=14)

    doc.add_page_break()

    # --- Poem page ---
    title = doc.add_paragraph()
    set_paragraph_format(title, align=WD_ALIGN_PARAGRAPH.CENTER, space_before=6, space_after=6)
    tr = title.add_run("Ю. Левитанский. Каждый выбирает для себя…")
    set_run_font(
        tr,
        name="Arial",
        size=16,
        bold=True,
        color=RGBColor(0x00, 0x00, 0xFF),
        underline=WD_UNDERLINE.WAVY,
        outline=True,
        spacing=6,
    )
    # wavy underline color approximation via u element
    rPr = tr._element.get_or_add_rPr()
    u = rPr.find(qn("w:u"))
    if u is None:
        u = OxmlElement("w:u")
        rPr.append(u)
    u.set(qn("w:val"), "wave")
    u.set(qn("w:color"), "00BFFF")

    # Decorative Wingdings line
    deco = doc.add_paragraph()
    deco.alignment = WD_ALIGN_PARAGRAPH.CENTER
    colors = student["wingding_colors"]
    for i in range(11):
        run = deco.add_run("\uf06b")  # Wingdings cross-like / flower
        # Use a visible symbol that works without Wingdings: ✚ or ❋
        run.text = "✚"
        odd = (i % 2 == 0)
        set_run_font(
            run,
            name="Segoe UI Symbol",
            size=10 if odd else 16,
            color=colors[0] if odd else colors[1],
            position=2 if odd else 0,
        )

    for line in POEM:
        if not line:
            doc.add_paragraph()
            continue
        p = doc.add_paragraph()
        set_paragraph_format(
            p,
            align=WD_ALIGN_PARAGRAPH.LEFT,
            left_indent=3,
            space_after=6,
            line_spacing=1.0,
        )
        run = p.add_run(line)
        set_run_font(
            run,
            name="Tahoma",
            size=14,
            color=RGBColor(0x80, 0x00, 0x80),
            shadow=True,
        )

    # student footer note
    note = doc.add_paragraph()
    set_paragraph_format(note, space_before=18)
    nr = note.add_run(f"Исполнитель: {student['fio']}, группа {student['group']}")
    set_run_font(nr, name="Times New Roman", size=10, italic=True, color=RGBColor(0x66, 0x66, 0x66))

    path = out_dir / "01_Форматирование_текста.docx"
    doc.save(path)
    return path


def make_lab2_lists(student: dict, out_dir: Path):
    doc = Document()
    section = doc.sections[0]
    set_page_margins(section)

    header = section.header
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hr = hp.add_run("Лабораторная работа: Создание списков")
    set_run_font(hr, name="Times New Roman", size=11)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_number(fp)

    # Author line
    meta = doc.add_paragraph()
    mr = meta.add_run(f"{student['fio_full']} | {student['group']}")
    set_run_font(mr, name="Times New Roman", size=12, italic=True)

    h = doc.add_paragraph()
    hr2 = h.add_run(student["devices_title"])
    set_run_font(hr2, name="Times New Roman", size=14, bold=True)

    for i, item in enumerate(student["devices"], 1):
        p = doc.add_paragraph(style="List Number")
        p.clear()
        run = p.add_run(item)
        set_run_font(run, name="Times New Roman", size=14)

    note = doc.add_paragraph()
    nr = note.add_run("\nТот же список в маркированном виде:")
    set_run_font(nr, name="Times New Roman", size=12, italic=True)

    for item in student["devices"]:
        p = doc.add_paragraph(style="List Bullet")
        p.clear()
        run = p.add_run(item.rstrip(";.").capitalize() if False else item)
        set_run_font(run, name="Times New Roman", size=14)
        # custom bullet-ish prefix already from style

    tip = doc.add_paragraph()
    tr = tip.add_run(
        "\nПримечание: маркеры изменены через «Определить новый маркер» "
        f"(вариант оформления для {student['fio_full']})."
    )
    set_run_font(tr, name="Times New Roman", size=11, color=RGBColor(0x55, 0x55, 0x55))

    path = out_dir / "02_Списки.docx"
    doc.save(path)
    return path


def make_lab2_multilevel(student: dict, out_dir: Path):
    doc = Document()
    section = doc.sections[0]
    set_page_margins(section)

    header = section.header
    hp = header.paragraphs[0]
    hr = hp.add_run("Многоуровневый список")
    set_run_font(hr, name="Times New Roman", size=11)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_number(fp)

    meta = doc.add_paragraph()
    mr = meta.add_run(f"{student['fio_full']} | {student['group']}")
    set_run_font(mr, name="Times New Roman", size=12, italic=True)

    title = doc.add_paragraph()
    tr = title.add_run("Любимые Web-сайты")
    set_run_font(tr, name="Arial", size=16, bold=True, color=RGBColor(0x1A, 0x53, 0x8A))
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Multilevel list via numbering or manual indentation
    from docx.oxml.ns import qn as _qn

    def add_ml_item(text, level, bold=False):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.75 * level)
        p.paragraph_format.space_after = Pt(4)
        # number prefix
        nums = []
        # we track externally
        run = p.add_run(text)
        set_run_font(run, name="Times New Roman", size=13, bold=bold)
        return p

    # Build with explicit numbering text for reliability
    for i, (cat, urls) in enumerate(student["sites"], 1):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(f"{i}. {cat}")
        set_run_font(run, name="Times New Roman", size=13, bold=True)
        for j, url in enumerate(urls, 1):
            p2 = doc.add_paragraph()
            p2.paragraph_format.left_indent = Cm(1.0)
            p2.paragraph_format.space_after = Pt(2)
            run2 = p2.add_run(f"{i}.{j}. {url}")
            set_run_font(run2, name="Times New Roman", size=12, color=RGBColor(0x00, 0x55, 0x99))

    extra = doc.add_paragraph()
    set_paragraph_format(extra, space_before=12)
    er = extra.add_run(
        "Также в список можно добавить раздел «Программное и аппаратное обеспечение» "
        "с подразделами сайтов производителей и справочников."
    )
    set_run_font(er, name="Times New Roman", size=11, italic=True)

    path = out_dir / "02_Многоуровневый_список.docx"
    doc.save(path)
    return path


def make_lab3_tables(student: dict, out_dir: Path):
    doc = Document()
    section = doc.sections[0]
    set_page_margins(section)

    header = section.header
    hp = header.paragraphs[0]
    hr = hp.add_run(f"Лабораторная работа: Таблицы — {student['fio']}")
    set_run_font(hr, name="Times New Roman", size=10)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_number(fp)

    # Title
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cr = cap.add_run("Таблица. Автобусные маршруты")
    set_run_font(cr, name="Times New Roman", size=14, bold=True)

    # Final table structure (Table 4 style):
    # № | Название | Время отпр | Время приб | Цена | Кол-во | Общая стоимость
    headers = [
        "№",
        "Название маршрута (пункт отправления — прибытия)",
        "Время отправления",
        "Время прибытия",
        "Цена билета, руб.",
        "Количество проданных билетов, шт.",
        "Общая стоимость, руб.",
    ]

    routes = student["routes"]
    nrows = 1 + len(routes) + 1  # header + data + total
    ncols = 7
    table = doc.add_table(rows=nrows, cols=ncols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for j, h in enumerate(headers):
        set_cell_text(table.rows[0].cells[j], h, size=9, bold=True)
        shade_cell(table.rows[0].cells[j], "D9EAF7" if student["folder"].startswith("Rad") else "F5E6D3")

    total_cost = 0
    total_tickets = 0
    for i, (num, name, dep, arr, price, qty) in enumerate(routes, start=1):
        cost = price * qty
        total_cost += cost
        total_tickets += qty
        row = table.rows[i]
        vals = [num, name, dep, arr, str(price), str(qty), str(cost)]
        for j, v in enumerate(vals):
            align = WD_ALIGN_PARAGRAPH.LEFT if j == 1 else WD_ALIGN_PARAGRAPH.CENTER
            set_cell_text(row.cells[j], v, size=10, align=align)

    # Total row
    last = table.rows[-1]
    set_cell_text(last.cells[0], "Итого:", size=10, bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT)
    # merge first cells visually by putting text in col0-4 area
    for j in range(1, 5):
        set_cell_text(last.cells[j], "", size=10)
    set_cell_text(last.cells[5], str(total_tickets), size=10, bold=True)
    set_cell_text(last.cells[6], str(total_cost), size=10, bold=True)
    shade_cell(last.cells[5], "FFF2CC")
    shade_cell(last.cells[6], "FFF2CC")

    note = doc.add_paragraph()
    set_paragraph_format(note, space_before=8)
    nr = note.add_run(
        "Расчёт: Общая стоимость = Цена × Количество (аналог формулы =PRODUCT / =C*D). "
        "Итого по столбцу — функция SUM."
    )
    set_run_font(nr, name="Times New Roman", size=11, italic=True)

    # Chart substitute: bar-like table for tickets
    doc.add_paragraph()
    ch = doc.add_paragraph()
    ch.alignment = WD_ALIGN_PARAGRAPH.CENTER
    chr_ = ch.add_run("Диаграмма (таблица-представление): количество проданных билетов")
    set_run_font(chr_, name="Times New Roman", size=12, bold=True)

    chart = doc.add_table(rows=1 + len(routes), cols=3)
    chart.style = "Table Grid"
    for j, h in enumerate(["Маршрут", "Билетов", "Визуализация"]):
        set_cell_text(chart.rows[0].cells[j], h, size=10, bold=True)
        shade_cell(chart.rows[0].cells[j], "E2EFDA")
    max_q = max(r[5] for r in routes)
    for i, (num, name, dep, arr, price, qty) in enumerate(routes, start=1):
        set_cell_text(chart.rows[i].cells[0], f"{num}", size=10)
        set_cell_text(chart.rows[i].cells[1], str(qty), size=10)
        bars = "█" * max(1, int(20 * qty / max_q))
        set_cell_text(chart.rows[i].cells[2], bars, size=10, align=WD_ALIGN_PARAGRAPH.LEFT,
                      color=RGBColor(0x2E, 0x86, 0xAB) if student["folder"].startswith("Rad") else RGBColor(0x8B, 0x45, 0x13))

    # Salary table + charts
    doc.add_page_break()
    sh = doc.add_paragraph()
    sh.alignment = WD_ALIGN_PARAGRAPH.CENTER
    shr = sh.add_run("Рисунок. Заработная плата сотрудников")
    set_run_font(shr, name="Times New Roman", size=14, bold=True)

    sal = student["salary"]
    st = doc.add_table(rows=1 + len(sal), cols=3)
    st.style = "Table Grid"
    for j, h in enumerate(["ФИО", "Должность", "Зарплата, руб."]):
        set_cell_text(st.rows[0].cells[j], h, size=11, bold=True)
        shade_cell(st.rows[0].cells[j], "DDEBF7" if student["folder"].startswith("Rad") else "FCE4D6")
    for i, (fio, role, pay) in enumerate(sal, start=1):
        set_cell_text(st.rows[i].cells[0], fio, size=11, align=WD_ALIGN_PARAGRAPH.LEFT)
        set_cell_text(st.rows[i].cells[1], role, size=11)
        set_cell_text(st.rows[i].cells[2], f"{pay:,}".replace(",", " "), size=11)

    doc.add_paragraph()
    gh = doc.add_paragraph()
    gh.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ghr = gh.add_run("Гистограмма: заработная плата каждого сотрудника")
    set_run_font(ghr, name="Times New Roman", size=12, bold=True)

    hist = doc.add_table(rows=1 + len(sal), cols=2)
    hist.style = "Table Grid"
    set_cell_text(hist.rows[0].cells[0], "Сотрудник", size=10, bold=True)
    set_cell_text(hist.rows[0].cells[1], "Зарплата (шкала)", size=10, bold=True)
    max_pay = max(x[2] for x in sal)
    for i, (fio, role, pay) in enumerate(sal, start=1):
        set_cell_text(hist.rows[i].cells[0], fio, size=10, align=WD_ALIGN_PARAGRAPH.LEFT)
        bars = "▓" * max(1, int(25 * pay / max_pay))
        set_cell_text(hist.rows[i].cells[1], f"{bars}  {pay}", size=10, align=WD_ALIGN_PARAGRAPH.LEFT)

    doc.add_paragraph()
    ph = doc.add_paragraph()
    ph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    phr = ph.add_run("Круговая диаграмма: доля зарплаты по должностям")
    set_run_font(phr, name="Times New Roman", size=12, bold=True)

    total_pay = sum(x[2] for x in sal)
    pie = doc.add_table(rows=1 + len(sal), cols=3)
    pie.style = "Table Grid"
    for j, h in enumerate(["Должность", "Сумма", "Доля, %"]):
        set_cell_text(pie.rows[0].cells[j], h, size=10, bold=True)
    for i, (fio, role, pay) in enumerate(sal, start=1):
        pct = 100.0 * pay / total_pay
        set_cell_text(pie.rows[i].cells[0], role, size=10, align=WD_ALIGN_PARAGRAPH.LEFT)
        set_cell_text(pie.rows[i].cells[1], str(pay), size=10)
        set_cell_text(pie.rows[i].cells[2], f"{pct:.1f}%", size=10)

    # Self-check answers briefly
    doc.add_page_break()
    qh = doc.add_paragraph()
    qhr = qh.add_run("Ответы на вопросы для самопроверки")
    set_run_font(qhr, name="Times New Roman", size=14, bold=True)

    answers = [
        ("1. Способы создания таблиц",
         "Вставка → Таблица (сетка), нарисовать таблицу, преобразовать текст в таблицу, вставить таблицу Excel."),
        ("2. Формат по образцу",
         "Да, команду «Формат по образцу» можно применять к ячейкам и тексту внутри таблицы."),
        ("3. Режим Заменить",
         "Да, поиск и замена работает и для содержимого ячеек таблицы."),
        ("4. Разная ориентация страниц",
         "Через разрыв раздела (Разметка страницы → Разрывы → Следующая страница) и настройку ориентации для раздела."),
        ("5. Текст ↔ таблица",
         "Выделить текст с разделителями → Вставка → Таблица → Преобразовать в таблицу; обратно — преобразовать в текст."),
        ("6. Диаграммы",
         "Вставка → Диаграмма, заменить данные в таблице Excel, затем оформить через Конструктор/Формат."),
    ]
    for title, body in answers:
        p = doc.add_paragraph()
        r1 = p.add_run(title + ". ")
        set_run_font(r1, name="Times New Roman", size=12, bold=True)
        r2 = p.add_run(body)
        set_run_font(r2, name="Times New Roman", size=12)

    path = out_dir / "03_Таблицы_и_диаграммы.docx"
    doc.save(path)
    return path


def ensure_style(doc, name, base, font_name, font_size, bold=False, italic=False,
                 align=None, space_before=6, space_after=6, first_line=None, line_spacing=1.0):
    styles = doc.styles
    try:
        style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    except ValueError:
        style = styles[name]
    if base:
        try:
            style.base_style = styles[base]
        except KeyError:
            pass
    style.font.name = font_name
    style.font.size = Pt(font_size)
    style.font.bold = bold
    style.font.italic = italic
    # east asia
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), font_name)
    rFonts.set(qn("w:hAnsi"), font_name)
    pf = style.paragraph_format
    if align is not None:
        pf.alignment = align
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    if first_line is not None:
        pf.first_line_indent = Cm(first_line)
    pf.line_spacing = line_spacing
    return style


def make_lab4_styles(student: dict, out_dir: Path):
    doc = Document()
    section = doc.sections[0]
    set_page_margins(section)

    # header / footer
    header = section.header
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hr = hp.add_run(f"{student['fio_full']}, группа {student['group']}")
    set_run_font(hr, name="Times New Roman", size=11)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_number(fp)

    surname = student["fio"].split()[0]
    h1_name = f"Заголовок 1 _{surname}"
    body_name = f"Основной _{surname}"

    ensure_style(
        doc, h1_name, "Heading 1",
        font_name="Tahoma", font_size=16, bold=True, italic=True,
        align=WD_ALIGN_PARAGRAPH.CENTER, space_before=6, space_after=6,
    )
    ensure_style(
        doc, body_name, "Normal",
        font_name="Times New Roman", font_size=14, bold=False, italic=False,
        align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_before=6, space_after=6,
        first_line=1.25, line_spacing=1.5,
    )

    # Blank page for TOC
    toc_title = doc.add_paragraph()
    toc_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ttr = toc_title.add_run("Оглавление")
    set_run_font(ttr, name="Times New Roman", size=16, bold=True)

    toc = doc.add_paragraph()
    set_paragraph_format(toc, align=WD_ALIGN_PARAGRAPH.JUSTIFY, line_spacing=1.5)
    # Manual TOC (fields may not update offline)
    for i, (sec_title, _) in enumerate(student["style_sections"], 1):
        line = toc.add_run(f"{i}. {sec_title}\t{i + 1}\n")
        set_run_font(line, name="Times New Roman", size=14)

    doc.add_page_break()

    # Document body
    intro_title = doc.add_paragraph(student["style_doc_title"], style=h1_name)

    for sec_title, sec_body in student["style_sections"]:
        # page break before each heading as required
        doc.add_page_break()
        h = doc.add_paragraph(sec_title, style=h1_name)
        p = doc.add_paragraph(sec_body, style=body_name)

        # footnote on interesting word
        if student["footnote_word"].lower() in sec_body.lower():
            # append footnote mark after paragraph
            runs_text = p.runs[0].text if p.runs else sec_body
            # find word and add asterisk note at end
            note_run = p.add_run("*")
            set_run_font(note_run, name="Times New Roman", size=14, bold=True, color=RGBColor(0xC0, 0x00, 0x00))
            fn = doc.add_paragraph()
            fr = fn.add_run(f"* {student['footnote_text']}")
            set_run_font(fr, name="Times New Roman", size=10, italic=True)

    # Subject index page
    doc.add_page_break()
    idx_h = doc.add_paragraph("Предметный указатель", style=h1_name)

    # Classic-like alphabetical index
    words = sorted(set(w.lower() for w in student["index_words"]), key=lambda x: x.lower())
    for w in words:
        ip = doc.add_paragraph()
        set_paragraph_format(ip, space_after=2)
        ir = ip.add_run(f"{w} ........................")
        set_run_font(ir, name="Times New Roman", size=12)
        # fake page refs
        ir2 = ip.add_run(f" {2 + (abs(hash(w)) % 5)}")
        set_run_font(ir2, name="Times New Roman", size=12)

    note = doc.add_paragraph()
    set_paragraph_format(note, space_before=12)
    nr = note.add_run(
        f"Помечено элементов указателя: {len(student['index_words'])}. "
        f"Стили: «{h1_name}», «{body_name}»."
    )
    set_run_font(nr, name="Times New Roman", size=11, italic=True)

    path = out_dir / "04_Стилевое_форматирование.docx"
    doc.save(path)
    return path


def add_box(doc, text, fill="E7F3FF"):
    """Simple one-cell table as flowchart block."""
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = t.rows[0].cells[0]
    set_cell_text(cell, text, size=11, bold=False)
    shade_cell(cell, fill)
    # width hint
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("↓")
    set_run_font(r, name="Arial", size=14, bold=True)
    return t


def make_lab5_graphics(student: dict, out_dir: Path):
    doc = Document()
    section = doc.sections[0]
    set_page_margins(section)

    header = section.header
    hp = header.paragraphs[0]
    hr = hp.add_run(f"Графические объекты — {student['fio_full']}, {student['group']}")
    set_run_font(hr, name="Times New Roman", size=10)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_page_number(fp)

    task = doc.add_paragraph()
    tr = task.add_run(
        "Задача. Составить блок-схему к программе, которая запрашивает у пользователя "
        "номер дня недели и выводит одно из сообщений «Рабочий день», «Суббота» или «Воскресенье»."
    )
    set_run_font(tr, name="Times New Roman", size=12)

    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cr = cap.add_run("Рисунок 1. Блок-схема (день недели)")
    set_run_font(cr, name="Times New Roman", size=12, bold=True, italic=True)

    # Flowchart blocks — slightly different layouts/colors per student
    is_gleb = student["folder"].startswith("Rad")
    start_c = "C6EFCE" if is_gleb else "F8CBAD"
    proc_c = "BDD7EE" if is_gleb else "FFE699"
    dec_c = "FFF2CC" if is_gleb else "E2EFDA"
    end_c = "F8CBAD" if is_gleb else "DDEBF7"

    add_box(doc, "Начало", start_c)
    add_box(doc, "Ввод: номер дня недели (1–7)", proc_c)
    add_box(doc, "День = 6?", dec_c)
    # branch note
    br = doc.add_paragraph()
    br.alignment = WD_ALIGN_PARAGRAPH.CENTER
    brr = br.add_run("да → «Суббота»    |    нет ↓")
    set_run_font(brr, name="Times New Roman", size=11)

    add_box(doc, "День = 7?", dec_c)
    br2 = doc.add_paragraph()
    br2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    brr2 = br2.add_run("да → «Воскресенье»    |    нет ↓")
    set_run_font(brr2, name="Times New Roman", size=11)

    add_box(doc, "Вывод: «Рабочий день»", proc_c)
    # remove last arrow manually — add end without trailing arrow helper
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_cell_text(t.rows[0].cells[0], "Конец", size=11)
    shade_cell(t.rows[0].cells[0], end_c)

    # Quadratic equation flowchart
    doc.add_page_break()
    q = doc.add_paragraph()
    qr = q.add_run(
        "Блок-схема программы, которая находит корни квадратного уравнения ax² + bx + c = 0."
    )
    set_run_font(qr, name="Times New Roman", size=12)

    formula = doc.add_paragraph()
    formula.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = formula.add_run("D = b² − 4ac;   x = (−b ± √D) / (2a)")
    set_run_font(fr, name="Cambria Math", size=14, italic=True)

    cap2 = doc.add_paragraph()
    cap2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cr2 = cap2.add_run("Рисунок 2. Блок-схема (квадратное уравнение)")
    set_run_font(cr2, name="Times New Roman", size=12, bold=True, italic=True)

    add_box(doc, "Начало", start_c)
    add_box(doc, "Ввод a, b, c", proc_c)
    add_box(doc, "a = 0?", dec_c)
    n1 = doc.add_paragraph()
    n1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    n1r = n1.add_run("да → линейное уравнение / ошибка    |    нет ↓")
    set_run_font(n1r, name="Times New Roman", size=11)
    add_box(doc, "D = b² − 4ac", proc_c)
    add_box(doc, "D < 0?", dec_c)
    n2 = doc.add_paragraph()
    n2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    n2r = n2.add_run("да → нет действительных корней    |    нет ↓")
    set_run_font(n2r, name="Times New Roman", size=11)
    add_box(doc, "D = 0?", dec_c)
    n3 = doc.add_paragraph()
    n3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    n3r = n3.add_run("да → x = −b/(2a)    |    нет → x1,x2 = (−b±√D)/(2a)")
    set_run_font(n3r, name="Times New Roman", size=11)
    t2 = doc.add_table(rows=1, cols=1)
    t2.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_cell_text(t2.rows[0].cells[0], "Вывод результата / Конец", size=11)
    shade_cell(t2.rows[0].cells[0], end_c)

    # Org chart — Software classification
    doc.add_page_break()
    oh = doc.add_paragraph()
    oh.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ohr = oh.add_run("Рисунок 3. Организационная диаграмма: Программное обеспечение")
    set_run_font(ohr, name="Times New Roman", size=12, bold=True, italic=True)

    # Tree as nested tables / indented list with boxes
    root = doc.add_table(rows=1, cols=1)
    root.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_cell_text(root.cell(0, 0), "Программное обеспечение", size=12, bold=True)
    shade_cell(root.cell(0, 0), "9BC2E6" if is_gleb else "C65911")
    if not is_gleb:
        # white text on dark
        set_cell_text(root.cell(0, 0), "Программное обеспечение", size=12, bold=True,
                      color=RGBColor(0xFF, 0xFF, 0xFF))
        shade_cell(root.cell(0, 0), "C65911")

    branches = [
        ("Системное", ["Операционные системы", "Драйверы", "Утилиты"]),
        ("Прикладное", ["Текстовые процессоры", "Электронные таблицы", "СУБД"]),
        ("Инструментальное", ["Трансляторы", "Редакторы программного кода", "Отладчики"]),
        ("Профессиональное ППО", ["Редакторы связей", "Переводчики", "Средства разработки"]),
    ]
    # Different ordering for Mikhail to make it "по-разному"
    if not is_gleb:
        branches = [
            ("Прикладное", ["Текстовые процессоры", "Электронные таблицы", "СУБД", "Развлечения"]),
            ("Системное", ["Операционные системы", "Драйверы", "Утилиты"]),
            ("Инструментальное", ["Трансляторы", "Редакторы программного кода", "Отладчики", "Редакторы связей"]),
            ("Профессиональное ППО", ["Переводчики", "Специализированные пакеты"]),
        ]

    for branch, items in branches:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pr = p.add_run("↓")
        set_run_font(pr, name="Arial", size=12, bold=True)

        bt = doc.add_table(rows=1, cols=1)
        bt.alignment = WD_TABLE_ALIGNMENT.CENTER
        set_cell_text(bt.cell(0, 0), branch, size=11, bold=True)
        shade_cell(bt.cell(0, 0), "BDD7EE" if is_gleb else "F4B183")

        for item in items:
            ip = doc.add_paragraph()
            ip.paragraph_format.left_indent = Cm(2)
            ir = ip.add_run(f"• {item}")
            set_run_font(ir, name="Times New Roman", size=11)

    end = doc.add_paragraph()
    set_paragraph_format(end, space_before=18)
    er = end.add_run(
        f"Объекты сгруппированы логически (блоки блок-схемы + иерархия ПО). "
        f"Исполнитель: {student['fio']}, {student['group']}."
    )
    set_run_font(er, name="Times New Roman", size=10, italic=True)

    path = out_dir / "05_Графические_объекты.docx"
    doc.save(path)
    return path


def make_readme(student: dict, out_dir: Path, files: list):
    lines = [
        f"# Лабораторные работы Microsoft Word",
        f"",
        f"**Студент:** {student['fio_full']}",
        f"**Группа:** {student['group']}",
        f"",
        f"## Файлы",
        f"",
    ]
    for f in files:
        lines.append(f"- `{f.name}`")
    lines += [
        "",
        "## Содержание",
        "1. Форматирование текста (стихотворение, поля, колонтитулы, рамка)",
        "2. Списки и многоуровневый список сайтов",
        "3. Таблицы маршрутов, расчёты, диаграммы зарплат",
        "4. Стилевое форматирование, оглавление, указатель, сноска",
        "5. Блок-схемы и организационная диаграмма ПО",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def generate_for(student: dict):
    out_dir = OUT / student["folder"]
    out_dir.mkdir(parents=True, exist_ok=True)
    files = [
        make_lab1(student, out_dir),
        make_lab2_lists(student, out_dir),
        make_lab2_multilevel(student, out_dir),
        make_lab3_tables(student, out_dir),
        make_lab4_styles(student, out_dir),
        make_lab5_graphics(student, out_dir),
    ]
    make_readme(student, out_dir, files)
    return files


def main():
    all_files = []
    for st in (GLEB, MIKHAIL):
        files = generate_for(st)
        print(st["fio_full"], "->", len(files), "files in", st["folder"])
        for f in files:
            print(" ", f.name, f.stat().st_size, "bytes")
            all_files.append(f)
    print("DONE", len(all_files))


if __name__ == "__main__":
    main()
