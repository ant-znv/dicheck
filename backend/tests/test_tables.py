"""Починка склеенных markdown-таблиц и рендер таблиц в docx."""
from __future__ import annotations

import io

from docx import Document

from backend.app.main import (
    _markdown_into_docx,
    _parse_table_block,
    _repair_markdown_tables,
)

GLUED = (
    "| № | Вердикт | Цитата из ДИ (дословно) | Норма / критерий | Комментарий | "
    "|---|---|---|---|---:| "
    "| 0.1 | Соответствует | «разрабатывать технологию» | Обычные требования к ЛНА | "
    "Явных ошибок не выявлено. | "
    "| 0.2 | Риск | «подчиняется руководителю ИТ-отдела» | Единство терминологии | "
    "Проверить соответствие невозможно. |"
)

PROPER = """\
| № | Вердикт | Цитата | Норма | Комментарий |
|---|---|---|---|---|
| **Блок 0. Гигиена документа** |
| 0.1 | Соответствует | «цитата» | ГОСТ Р 7.0.97-2025 | Ошибок не выявлено. |
"""


def rows_of(md: str) -> list[list[str]]:
    """Строки первой таблицы в markdown-блоке (по разделителю '---')."""
    lines = [ln for ln in md.split("\n") if ln.strip().startswith("|")]
    assert len(lines) >= 2
    parsed = []
    for ln in lines:
        parsed.append([c.strip() for c in ln.strip().strip("|").split("|")])
    return parsed


def test_glued_single_line_repaired():
    out = _repair_markdown_tables(GLUED)
    r = rows_of(out)
    assert r[0] == ["№", "Вердикт", "Цитата из ДИ (дословно)", "Норма / критерий", "Комментарий"]
    assert r[1] == ["---", "---", "---", "---", "---:"]
    assert r[2][0] == "0.1" and r[2][-1] == "Явных ошибок не выявлено."
    assert r[3][0] == "0.2" and len(r[3]) == 5
    # каждая строка таблицы — на своей физической строке
    assert out.count("\n") == 3


def test_glued_survives_report_with_headings():
    report = "## 2. Таблица проверок\n\n" + GLUED + "\n\n## 3. Точки риска\n\nТекст после."
    out = _repair_markdown_tables(report)
    assert "## 2. Таблица проверок" in out and "## 3. Точки риска" in out
    assert out.count("\n") > report.count("\n")
    assert rows_of(out)[1][0] == "---"


def test_proper_table_unchanged():
    assert _repair_markdown_tables(PROPER) == PROPER


def test_plain_text_unchanged():
    text = "Заголовок\n\nОбычный текст со | знаками piping, но не таблица.\n"
    assert _repair_markdown_tables(text) == text


def test_ambiguous_block_untouched():
    # шапка не равна числу колонок-разделителей — не трогаем
    bad = "| А | Б |\n|---|---|---|\n| 1 | 2 | 3 |"
    assert _repair_markdown_tables(bad) == bad
    # данные не кратны числу колонок — не трогаем
    bad2 = "| А | Б |\n|---|---|\n| 1 | 2 | 3 |"
    assert _repair_markdown_tables(bad2) == bad2
    # строка-сепаратор с одной ячейкой внутри 5-колоночной таблицы — не трогаем
    assert _repair_markdown_tables(PROPER) == PROPER


def test_idempotent():
    once = _repair_markdown_tables(GLUED)
    assert _repair_markdown_tables(once) == once


def test_parse_table_block():
    lines = PROPER.split("\n")
    parsed = _parse_table_block(lines, 0)
    assert parsed is not None
    rows, nxt = parsed
    # шапка + строка-сепаратор + строка 0.1 (разделитель '---' — метаданные, не строка)
    assert len(rows) == 3 and rows[0][0] == "№" and rows[1][0] == "**Блок 0. Гигиена документа**"
    assert nxt == len(lines) - 1  # хвостовая пустая строка остаётся за таблицей


def test_parse_table_block_requires_delimiter():
    lines = ["| А | Б |", "| 1 | 2 |"]
    assert _parse_table_block(lines, 0) is None


def test_docx_export_renders_real_table():
    doc = Document()
    _markdown_into_docx(doc, "Отчёт\n\n" + PROPER + "\n\nКонец.")
    tables = doc.tables
    assert len(tables) == 1
    t = tables[0]
    assert len(t.rows) == 3 and len(t.columns) == 5
    assert t.rows[0].cells[0].text == "№"
    assert t.rows[1].cells[0].text == "Блок 0. Гигиена документа"
    assert t.rows[2].cells[0].text == "0.1"
    # шапка полужирная, данные — нет
    assert all(run.bold for p in t.rows[0].cells[0].paragraphs for run in p.runs)
    assert not any(run.bold for p in t.rows[2].cells[1].paragraphs for run in p.runs)


def test_docx_export_roundtrip_bytes():
    doc = Document()
    _markdown_into_docx(doc, GLUED.replace("|---|---|---|---|---:|", "|---|---|---|---|---:|"))
    buf = io.BytesIO()
    doc.save(buf)
    assert len(buf.getvalue()) > 0
