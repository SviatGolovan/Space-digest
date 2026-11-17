"""
Приём публикаций в базу: нормализация → проверка на повтор → запись.

* Повтор внутри источника определяется по (source, external_id), а если лента
  поменяла guid — по канонической ссылке. Изменённый текст обновляет запись.
* Вся пачка пишется одной транзакцией: либо всё, либо ничего.
* Склейка одинаковых новостей из *разных* источников — следующий шаг конвейера
  (сюжеты), здесь она не делается.
* Дата. Если источник даты не дал, новость НЕ становится «сегодняшней» молча: в поле
  date_status пишется 'none' (дата не подтверждена, published_at = когда впервые
  замечена), а при самом первом сборе источника — 'baseline': это архив сайта, и в
  выгрузки он не идёт. Дата из карточки на странице сайта помечается 'card' и потом
  сверяется со страницей статьи (services/fulltext.py).
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
        "date_status": raw.date_from if raw.published_at else None,
    }


def ingest(db: Database, source: Source, raw_items: Iterable[RawItem],
           origin: str = "collect", update_existing: bool = True,
           first_run: bool = False) -> IngestStats:
    """update_existing=False — только добавлять (импорт архива не должен затирать
    свежесобранный полный текст своим обрезанным).
    first_run=True — первый удачный сбор источника: новости без даты считаются архивом."""
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
                status = it["date_status"]
                if not it["published_at"]:
                    status = "baseline" if first_run else "none"
                db.execute("""
                    INSERT INTO items (source_id, external_id, url, url_canonical, title, summary,
                        body, author, published_at, fetched_at, content_hash, origin, date_status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (source.id, it["external_id"], it["url"], it["url_canonical"], it["title"],
                      it["summary"], it["body"], it["author"], it["published_at"] or now, now,
                      it["content_hash"], origin, status))
                stats.new += 1
            elif update_existing and row["content_hash"] != it["content_hash"]:
                db.execute("""
                    UPDATE items SET title = ?, summary = ?, body = ?, author = ?, url = ?,
                        url_canonical = ?, content_hash = ?, updated_at = ?, stage = 'new', fulltext_status = NULL,
                        published_at = CASE WHEN ? IS NOT NULL AND COALESCE(date_status, '') <> 'page'
                                            THEN ? ELSE published_at END,
                        date_status = CASE WHEN ? IS NOT NULL AND COALESCE(date_status, '') <> 'page'
                                           THEN ? ELSE date_status END
                    WHERE id = ?
                """, (it["title"], it["summary"], it["body"], it["author"], it["url"],
                      it["url_canonical"], it["content_hash"], now,
                      it["published_at"], it["published_at"], it["published_at"], it["date_status"],
                      row["id"]))
                stats.updated += 1
            else:
                stats.unchanged += 1
    return stats
