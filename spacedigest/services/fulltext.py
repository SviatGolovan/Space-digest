"""
Полный текст статей.

Многие RSS-ленты отдают только анонс (в архиве — около 200 символов на новость), и ChatGPT
не может извлечь факты, которых нет в CSV. После сбора программа открывает страницы таких
статей и достаёт основной текст (trafilatura: убирает меню, рекламу, комментарии).

* Берём только «короткие» новости (меньше collect.fulltext_min символов) и только сайты.
* Текст со страницы заменяет анонс, если он заметно длиннее; content_hash не меняется —
  поэтому следующий сбор той же ленты не затирает полный текст анонсом.
  Если статья в ленте реально изменилась, ingest сбрасывает fulltext_status и текст
  будет взят заново.
* Вежливо: по одной странице за раз на источник, пауза между запросами, таймаут.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from ..core.db import Database
from ..core.timeutil import iso_after, now_iso

LogFn = Optional[Callable[[str], None]]
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
BATCH = 40              # статей за один запуск задачи на источник
PAUSE = 0.8             # секунд между страницами одного источника
GAIN = 120              # насколько текст страницы должен быть длиннее анонса


def extract_text(html: str, url: str = "") -> str:
    """Основной текст статьи из HTML ('' — если не получилось)."""
    import trafilatura
    try:
        text = trafilatura.extract(html, url=url or None, include_comments=False, include_tables=False,
                                   include_images=False, favor_recall=True, deduplicate=True) or ""
    except Exception:                                                        # noqa: BLE001
        return ""
    return text.strip()


class FullText:
    def __init__(self, db: Database, settings, http_get: Optional[Callable] = None, sleep=time.sleep):
        self.db = db
        self.settings = settings
        self._get = http_get
        self._sleep = sleep

    def cfg(self) -> tuple[bool, int]:
        c = self.settings.get("collect") or {}
        return bool(c.get("fulltext", True)), int(c.get("fulltext_min") or 600)

    def http_get(self, url: str):
        if self._get:
            return self._get(url)
        import requests
        return requests.get(url, timeout=15, headers={"User-Agent": BROWSER_UA,
                                                        "Accept-Language": "ru,en;q=0.8"})

    def pending(self, source_id: Optional[int] = None, days: int = 3, limit: int = BATCH) -> list[dict]:
        """Короткие новости сайтов за последние N дней, которые ещё не пробовали дотянуть."""
        _, min_chars = self.cfg()
        args: list = [min_chars, iso_after(minutes=-days * 1440)]
        sql = """
            SELECT i.id, i.source_id, i.url, i.title, i.summary, i.body
            FROM items i JOIN sources s ON s.id = i.source_id
            WHERE s.kind = 'rss' AND i.fulltext_status IS NULL AND i.url LIKE 'http%'
              AND length(COALESCE(i.body, '')) < ?
              AND COALESCE(i.published_at, i.fetched_at) >= ?"""
        if source_id is not None:
            sql += " AND i.source_id = ?"
            args.append(source_id)
        sql += " ORDER BY COALESCE(i.published_at, i.fetched_at) DESC LIMIT ?"
        args.append(limit)
        return self.db.query(sql, tuple(args))

    def process(self, rows: list[dict], log: LogFn = None, should_stop: Callable[[], bool] = lambda: False) -> dict:
        got = same = failed = 0
        for k, r in enumerate(rows):
            if should_stop():
                break
            if k:
                self._sleep(PAUSE)
            old = max(len(r.get("body") or ""), len(r.get("summary") or ""))
            status, text = "failed", ""
            try:
                resp = self.http_get(r["url"])
                code = getattr(resp, "status_code", 200)
                ctype = (getattr(resp, "headers", {}) or {}).get("Content-Type", "text/html")
                if code < 400 and "html" in ctype.lower():
                    text = extract_text(resp.text, r["url"])
                    status = "ok" if len(text) >= old + GAIN and len(text) >= 300 else "same"
            except Exception:                                                # noqa: BLE001
                status = "failed"
            with self.db.tx():
                if status == "ok":
                    self.db.execute("UPDATE items SET body = ?, fulltext_status = 'ok', fulltext_at = ? WHERE id = ?",
                                    (text, now_iso(), r["id"]))
                else:
                    self.db.execute("UPDATE items SET fulltext_status = ?, fulltext_at = ? WHERE id = ?",
                                    (status, now_iso(), r["id"]))
            got += status == "ok"; same += status == "same"; failed += status == "failed"
        if log and rows:
            log(f"Полный текст: взято {got}, на странице не больше анонса {same}, не открылось {failed}")
        return {"ok": got, "same": same, "failed": failed}

    def stats(self, days: int = 7) -> dict:
        """Для настроек: сколько новостей сайтов короткие и сколько дотянуто."""
        _, min_chars = self.cfg()
        r = self.db.one("""
            SELECT COUNT(*) AS total,
                   SUM(length(COALESCE(i.body, '')) < ?) AS short,
                   SUM(i.fulltext_status = 'ok') AS ok,
                   SUM(i.fulltext_status = 'failed') AS failed,
                   SUM(i.fulltext_status IS NULL AND length(COALESCE(i.body, '')) < ?) AS pending
            FROM items i JOIN sources s ON s.id = i.source_id
            WHERE s.kind = 'rss' AND COALESCE(i.published_at, i.fetched_at) >= ?""",
            (min_chars, min_chars, iso_after(minutes=-days * 1440)))
        return {k: int(r[k] or 0) for k in ("total", "short", "ok", "failed", "pending")}
