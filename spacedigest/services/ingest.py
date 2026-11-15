"""
Приём публикаций в базу: нормализация → проверка на повтор → запись.

* Повтор внутри источника определяется по (source, external_id), а если лента
  поменяла guid — по канонической ссылке. Изменённый текст обновляет запись.
* Вся пачка пишется одной транзакцией: либо всё, либо ничего.
* Склейка одинаковых новостей из *разных* источников — следующий шаг конвейера
  (сюжеты), здесь она не делается.
"""
from __future__ import annotations

from typing import Iterable

from ..core.db import Database
from ..core.timeutil import now_iso, to_iso
from ..domain.models import IngestStats, RawItem, Source
from ..domain.text import canonical_url, content_hash, fix_mojibake, html_to_text, one_line

MAX_TEXT = 200_000          # защита от «лент», внутри которых целые книги


def normalize(raw: RawItem) -> dict:
    title = fix_mojibake(one_line(raw.title))[:1000]
    summary = fix_mojibake(html_to_text(raw.summary))[:MAX_TEXT]
    body = fix_mojibake(html_to_text(raw.body))[:MAX_TEXT]
    if body and body == summary:
        body = ""                             # лента продублировала анонс в полный текст
    return {
        "external_id": raw.external_id.strip(),
        "url": (raw.url or "").strip(),
        "url_canonical": canonical_url(raw.url),
        "title": title,
        "summary": summary,
        "body": body,
        "author": one_line(raw.author)[:300],
        "published_at": to_iso(raw.published_at),
        "content_hash": content_hash(title, body or summary),
    }


def ingest(db: Database, source: Source, raw_items: Iterable[RawItem],
           origin: str = "collect", update_existing: bool = True) -> IngestStats:
    """update_existing=False — только добавлять (импорт архива не должен затирать
    свежесобранный полный текст своим обрезанным)."""
    stats = IngestStats()
    now = now_iso()
    with db.tx():
        for raw in raw_items:
            it = normalize(raw)
            if not it["external_id"] or not (it["title"] or it["summary"] or it["body"]):
                stats.skipped += 1
                continue
            row = db.one("SELECT id, content_hash FROM items WHERE source_id = ? AND external_id = ?",
                         (source.id, it["external_id"]))
            if row is None and it["url_canonical"]:
                row = db.one("SELECT id, content_hash FROM items WHERE source_id = ? "
                             "AND url_canonical = ?", (source.id, it["url_canonical"]))
            if row is None:
                db.execute("""
                    INSERT INTO items (source_id, external_id, url, url_canonical, title, summary,
                        body, author, published_at, fetched_at, content_hash, origin)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (source.id, it["external_id"], it["url"], it["url_canonical"], it["title"],
                      it["summary"], it["body"], it["author"], it["published_at"] or now, now,
                      it["content_hash"], origin))
                stats.new += 1
            elif update_existing and row["content_hash"] != it["content_hash"]:
                db.execute("""
                    UPDATE items SET title = ?, summary = ?, body = ?, author = ?, url = ?,
                        url_canonical = ?, content_hash = ?, updated_at = ?, stage = 'new', fulltext_status = NULL,
                        published_at = COALESCE(?, published_at)
                    WHERE id = ?
                """, (it["title"], it["summary"], it["body"], it["author"], it["url"],
                      it["url_canonical"], it["content_hash"], now, it["published_at"], row["id"]))
                stats.updated += 1
            else:
                stats.unchanged += 1
    return stats
