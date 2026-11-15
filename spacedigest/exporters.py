"""
Exporters — выгрузка новостей в разные форматы: CSV, XLSX, Markdown.
Все форматы используют один и тот же набор колонок:
    Дата · Источник · Заголовок · Новость · Ссылка
Параметр lang:
    "ru"   → переведённый текст (title_ru/summary_ru), если он есть, иначе оригинал;
    "orig" → всегда оригинал.
"""
from __future__ import annotations

import csv
import io

COLUMNS = ["Дата", "Источник", "Заголовок", "Новость", "Ссылка"]


def _fields(a: dict, lang: str) -> tuple:
    """Возвращает (дата, источник, заголовок, новость, ссылка) с учётом языка."""
    if lang == "ru":
        title = a.get("title_ru") or a.get("title", "")
        summary = a.get("summary_ru") or a.get("summary", "")
    else:
        title = a.get("title", "")
        summary = a.get("summary", "")
    return (
        a.get("published_at", ""),
        a.get("source_name", ""),
        title,
        summary,
        a.get("url", ""),
    )


# ─── CSV ───────────────────────────────────────────────────────────────────────

def articles_to_csv(articles: list[dict], lang: str = "orig") -> str:
    """QUOTE_ALL, с BOM — корректно открывается в Excel."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(COLUMNS)
    for a in articles:
        writer.writerow(_fields(a, lang))
    return "\ufeff" + output.getvalue()


# ─── XLSX ──────────────────────────────────────────────────────────────────────

def articles_to_xlsx(articles: list[dict], lang: str = "orig") -> bytes:
    """Лист с шапкой, автошириной колонок и переносом текста. Возвращает байты."""
    from openpyxl import Workbook  # ленивый импорт
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Новости"

    header_fill = PatternFill("solid", fgColor="111623")
    header_font = Font(color="9FB4D0", bold=True)
    for col, name in enumerate(COLUMNS, start=1):
        c = ws.cell(row=1, column=col, value=name)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"

    for r, a in enumerate(articles, start=2):
        date, src, title, summary, url = _fields(a, lang)
        ws.cell(row=r, column=1, value=date)
        ws.cell(row=r, column=2, value=src)
        ws.cell(row=r, column=3, value=title)
        ws.cell(row=r, column=4, value=summary).alignment = Alignment(wrap_text=True, vertical="top")
        link_cell = ws.cell(row=r, column=5, value=url)
        if url:
            link_cell.hyperlink = url
            link_cell.font = Font(color="4F9CF9", underline="single")

    widths = [20, 22, 50, 60, 40]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─── Markdown (дайджест) ─────────────────────────────────────────────────────

def articles_to_markdown(articles: list[dict], lang: str = "orig",
                         title: str = "Космические новости") -> str:
    """Дайджест: новости сгруппированы по источникам."""
    groups: dict[str, list] = {}
    for a in articles:
        date, src, t, summary, url = _fields(a, lang)
        groups.setdefault(src or "—", []).append((date, t, summary, url))

    lines = [f"# {title}", "", f"Всего новостей: **{len(articles)}**", ""]
    for src in sorted(groups):
        lines.append(f"## {src}")
        lines.append("")
        for date, t, summary, url in groups[src]:
            head = f"[{t}]({url})" if url else t
            lines.append(f"- **{head}**" + (f"  \n  _{date}_" if date else ""))
            if summary:
                lines.append(f"  \n  {summary}")
        lines.append("")
    return "\n".join(lines)
