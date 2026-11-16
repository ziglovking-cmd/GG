#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract verbatim answers from pathophys source for each credit question."""

from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
import html

SOURCE = Path("/tmp/source_patfiz.txt").read_text(encoding="utf-8")
LINES = SOURCE.split("\n")

Q_TITLES = {
    1: "Патологическая физиология как фундаментальная наука и учебная дисциплина, её предмет, задачи и методы. Понятие о клинической патофизиологии. Основные исторические этапы развития патологической физиологии (А.М. Филомафитский, К. Бернар, В.В. Пашутин, А.А. Богомолец).",
    2: "Методологические и методические принципы в патологии. Экспериментальное моделирование основных стоматологических заболеваний.",
    3: "Основные понятия общей нозологии: патологическая реакция, патологический рефлекс, патологический процесс, патологическая функция, патологическое состояние, болезнь. Принципы классификации болезней (ВОЗ).",
    4: "Общее учение о болезни. Понятие «болезнь», «предболезнь». Биологический, социальный, философский и медицинский аспекты происхождения болезней. Болезнь как диалектическое единство повреждения и защитно-приспособительных процессов. Периоды и исходы болезней. Рецидивы.",
    5: "Роль реактивности и резистентности организма в патологии. Патологическая реактивность организма. Эволюционные аспекты реактивности. Барьерные функции организма и их нарушения. Гематосаливарный барьер.",
    6: "Общая этиология. Принцип детерминизма в патологии. Критический анализ монокаузализма, кондиционализма, конституционализма, генетического детерминизма и др. представлений общей этиологии.",
    7: "Болезнетворное действие механических, физических, химических, биологических, психогенных факторов и их значение в челюстно-лицевой патологии. Экологические аспекты общей этиологии.",
    8: "Общий патогенез. Раздражение и повреждение как начальное звено патогенеза. Уровни повреждения. Системный подход в патологии (И.М. Сеченов, И.П. Павлов). Патология раневого процесса.",
    9: "Причинно-следственные отношения в патогенезе, «порочные круги» в патогенезе. Местные и общие реакции на повреждения, первичные и вторичные повреждения, их взаимосвязь.",
    10: "Ведущие звенья патогенеза: нейрогенные, гуморальные, метаболические, патоиммунные и генетические механизмы заболеваний.",
    11: "Общий саногенез. Защитные, приспособительные, компенсаторные и восстановительные механизмы выздоровления. Принципы лечения болезней.",
    12: "Лихорадка: определение понятия, стадии; типы лихорадочных реакций, их общая характеристика.",
    13: "Этиология лихорадки. Пирогенные вещества, классификация, источники образования. Механизмы действия пирогенов. Зависимость развития лихорадки от свойств пирогенов и реактивности организма. Отличия лихорадки от экзогенной и других видов гипертермий.",
    14: "Патофизиологические механизмы развития лихорадки: клеточные, рефлекторные, центральные и гуморальные (С.П.Боткин, И.П.Павлов).",
    15: "Изменение обмена веществ и физиологических систем при лихорадке. Биологическое значение лихорадки. Изменение функций слюнных желёз и состояния слизистой ротовой полости при лихорадке. Патофизиологические принципы жаропонижающей терапии и пиротерапии.",
    16: "Гипоксия: определение понятия, классификация. Компенсаторно-приспособительные реакции при гипоксии, их механизмы. Роль гипоксии в патогенезе различных патологических процессов и болезней. Экспериментальные модели различных типов гипоксий.",
    17: "Гипоксическая, циркуляторная и гемическая гипоксии. Причины и механизмы развития. Газовый состав артериальной и венозной крови при различных видах гипоксий.",
    18: "Тканевая гипоксия. Абсолютная и относительная недостаточность биологического окисления, разобщение окисления и фосфорилирования, дефицит субстратов окисления. Причины и механизмы развития.",
    19: "Нарушения обмена веществ и функций органов и систем при острой и хронической гипоксии, влияние гипер- и гипокапнии. Патофизиологические основы профилактики и терапии.",
    20: "Воспаление: определение понятия, общие и местные явления. Этиология и нейрогуморальные механизмы развития воспаления.",
    21: "Воспаление: первичная и вторичная альтерация. Медиаторы воспаления. Изменение обмена веществ в тканях при воспалении. Понятие о противовоспалительных медиаторах.",
    22: "Роль реактивности в развитии воспаления. Классификация воспаления. Развитие воспаления в онтогенезе. Особенности воспалительных процессов в челюстно-лицевой области. Биологическое значение воспаления и принципы противовоспалительной терапии.",
    23: "Расстройства кровообращения и микроциркуляции в тканях при воспалении. Изменения реологических свойств крови в очаге воспаления, белкового состава и физико-химических свойств плазмы.",
    24: "Экссудация и эмиграция лейкоцитов, механизмы развития, виды экссудатов.",
    25: "Аллергия: определение понятия, классификация, общая характеристика. Экзо- и эндоаллергены, их виды. Патофизиологические основы методов выявления аллергии. Аллергические реакции в стоматологической практике. Псевдоаллергия; отличие от истинной аллергии.",
    26: "Аллергия замедленного типа: контактная и бактериальная аллергия. Природа аллергенов. Патоиммунные, патохимические и патофизиологические механизмы развития. Значение для проблемы пересадки органов и тканей.",
    27: "Аллергия немедленного типа: природа аллергенов, патоиммунные и патохимические механизмы развития. Механизмы гипосенсибилизации при аллергии.",
    28: "Аллергия немедленного типа: атопические болезни, анафилактические реакции, лекарственная и пищевая аллергия, патофизиологические механизмы развития.",
    29: "Аутоаллергия: аутоаллергены, механизмы нарушения иммунной толерантности и возникновения иммунной аутоагрессии. Принципы выявления и терапии аутоиммунных заболеваний.",
    30: "Патофизиология боли. Определение понятия, виды боли. Каузалгия; фантомные боли; таламический синдром. Этиология боли. Биологическое значение боли. Понятие о «физиологической» и «патологической» боли. Патофизиологические основы обезболивания.",
    31: "Боль как интегративная реакция организма на повреждающие воздействия. Рецепторный, проводниковый и центральный механизмы боли. Гуморальные факторы боли; роль кининов и нейропептидов. Боль как результат повреждения антиноцицептивной системы.",
    32: "Местные нарушения кровообращения: артериальная и венозная гиперемия, ишемия, стаз; определение, виды, причины и механизмы развития. Изменения в тканях при гиперемии. Ишемический токсикоз. Компенсаторные процессы. «Слайдж»-феномен. Капиллярный (истинный) стаз. Капиллярно-трофическая недостаточность.",
}


def take(a: int, b: int) -> str:
    return "\n".join(LINES[a:b]).strip("\n").strip()


# Explicit ranges [start, end) verified against source
RANGES: dict[int, list[tuple[int, int]]] = {
    1: [(0, 39)],
    2: [(39, 73)],
    3: [(73, 94)],
    4: [(94, 151)],
    # reactivity core + barriers from sanogenesis
    5: [(229, 266), (475, 477)],
    6: [(151, 167)],
    7: [(167, 184)],
    # includes systemic approach paragraphs that begin near causal-relations heading
    8: [(184, 209)],
    # causal relations + порочный круг / местные-общие / первичные-вторичные
    9: [(204, 209), (222, 229)],
    10: [(209, 222)],
    11: [(469, 518)],
    12: [(1125, 1137)],
    # etiology/pyrogens + hyperthermia distinction
    13: [(1137, 1152), (1206, 1208)],
    14: [(1152, 1167)],
    15: [(1167, 1199)],
    16: [(1991, 2024)],
    17: [(2024, 2041)],
    18: [(2041, 2053)],
    19: [(2053, 2078)],
    20: [(942, 985)],
    21: [(985, 1073)],
    # + leukocyte features in maxillofacial inflammation from later source section
    22: [(1090, 1110), (2801, 2803)],
    23: [(1073, 1085)],  # до Экссудация — уточним ниже
    24: [(1085, 1090)],
    25: [(1297, 1337)],
    26: [(1337, 1352)],
    27: [(1352, 1384)],
    28: [(1384, 1406)],
    29: [(1406, 1427)],
    30: [(2472, 2489)],
    31: [(2489, 2501)],
    # hyperemia + ischemia/stasis + sludge/capillary
    32: [(822, 854), (854, 906), (767, 811)],
}

# Fix Q23/Q24 split by finding "Экссудация" line
for i in range(1073, 1091):
    if LINES[i].strip().startswith("Экссудация"):
        RANGES[23] = [(1073, i)]
        RANGES[24] = [(i, 1090)]
        break

# Fix Q31 end: include humoral/antinociceptive paragraphs
for i in range(2489, 2520):
    if LINES[i].strip().startswith("Нарушения системы эритроцитов"):
        RANGES[31] = [(2489, i)]
        break

# Fix Q29 end before next topic
for i in range(1406, 1435):
    if LINES[i].strip().startswith("Нарушение механизмов переваривания"):
        RANGES[29] = [(1406, i)]
        break

# Fix Q32 ischemia end before thrombosis
for i in range(854, 930):
    if LINES[i].strip().startswith("Тромбоз как причина"):
        RANGES[32] = [(822, 854), (854, i), (767, 811)]
        break


def build_answer(n: int) -> str:
    parts = [take(a, b) for a, b in RANGES[n]]
    return "\n\n".join(p for p in parts if p).strip()


answers = {n: build_answer(n) for n in range(1, 33)}
for n in range(1, 33):
    print(f"Q{n}: {len(answers[n])} chars")


def write_md(path: Path):
    parts = [
        "# Ответы на вопросы к зачёту по патологической физиологии\n\n",
        "> Ответы приведены **дословно** из файла «патфиз экз» (без перефразирования).\n",
    ]
    for n in range(1, 33):
        parts.append(f"\n## {n}. {Q_TITLES[n]}\n\n")
        parts.append(answers[n] + "\n")
    path.write_text("".join(parts), encoding="utf-8")


def write_docx(path: Path):
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2)
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    h = doc.add_heading("Ответы на вопросы к зачёту по патологической физиологии", 0)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph(
        "Ответы приведены дословно из файла «патфиз экз» (без перефразирования)."
    )
    p.runs[0].italic = True
    for n in range(1, 33):
        doc.add_heading(f"{n}. {Q_TITLES[n]}", level=1)
        for para in answers[n].split("\n"):
            if para.strip() == "":
                continue
            doc.add_paragraph(para)
    doc.save(path)


def write_site(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    write_md(out_dir / "otvety_zachet_patfiz.md")
    write_docx(out_dir / "otvety_zachet_patfiz.docx")
    write_md(Path("/workspace/answers/otvety_zachet_patfiz.md"))
    write_docx(Path("/workspace/answers/otvety_zachet_patfiz.docx"))

    nav = " ".join(f'<a href="#q{i}">{i}</a>' for i in range(1, 33))
    blocks = []
    for n in range(1, 33):
        title = html.escape(Q_TITLES[n])
        body = html.escape(answers[n]).replace("\n", "<br/>\n")
        blocks.append(
            f'<section id="q{n}"><h2>{n}. {title}</h2><div class="ans">{body}</div></section>'
        )
    page = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Ответы к зачёту по патофизиологии</title>
<style>
:root {{ --bg:#f7f4ef; --ink:#1c1917; --muted:#57534e; --card:#fffdf9; --line:#e7e0d5; --accent:#0f766e; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif; background:linear-gradient(180deg,#fbf8f3 0%,var(--bg) 100%); color:var(--ink); line-height:1.55; }}
.wrap {{ max-width:960px; margin:0 auto; padding:28px 18px 64px; }}
.hero {{ background:var(--card); border:1px solid var(--line); padding:28px 24px; margin-bottom:22px; }}
.hero h1 {{ margin:0 0 10px; font-size:clamp(1.5rem,3vw,2.1rem); }}
.hero p {{ margin:0 0 16px; color:var(--muted); }}
.actions {{ display:flex; flex-wrap:wrap; gap:10px; }}
a.btn {{ display:inline-block; text-decoration:none; background:var(--accent); color:white; padding:10px 14px; font-family:ui-sans-serif,system-ui,sans-serif; }}
a.btn.secondary {{ background:transparent; color:var(--accent); border:1px solid var(--accent); }}
.nav {{ position:sticky; top:0; z-index:2; background:rgba(251,248,243,.94); border:1px solid var(--line); padding:10px 12px; margin-bottom:18px; font-family:ui-sans-serif,system-ui,sans-serif; font-size:.85rem; line-height:1.9; }}
.nav a {{ color:var(--accent); text-decoration:none; margin-right:8px; }}
.content {{ background:var(--card); border:1px solid var(--line); padding:8px 22px 28px; }}
h2 {{ margin-top:1.7em; border-top:1px solid var(--line); padding-top:1em; font-size:1.15rem; }}
.ans {{ font-size:1rem; }}
</style>
</head>
<body>
<div class="wrap">
  <section class="hero">
    <h1>Ответы к зачёту по патофизиологии</h1>
    <p>Ответы приведены дословно из файла «патфиз экз». Скачайте Word или Markdown.</p>
    <div class="actions">
      <a class="btn" href="./otvety_zachet_patfiz.docx" download>Скачать Word (.docx)</a>
      <a class="btn secondary" href="./otvety_zachet_patfiz.md" download>Скачать Markdown (.md)</a>
    </div>
  </section>
  <nav class="nav">{nav}</nav>
  <article class="content">
{''.join(blocks)}
  </article>
</div>
</body>
</html>"""
    (out_dir / "index.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    write_site(Path("/workspace/patfiz-zachet"))
    # quick integrity: first line of each answer should come from source
    for n in range(1, 33):
        first = answers[n].split("\n", 1)[0][:60]
        assert first in SOURCE or first.lstrip("\u200b ").strip()[:40] in SOURCE, (n, first)
    print("DONE OK")
