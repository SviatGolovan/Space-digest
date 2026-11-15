"""
Перенос данных 3.0 в единую базу 4.0 (выполняется один раз, повторный запуск безопасен).

Источники: встроенные + свои из settings.json + Telegram-каналы (из настроек и из news.db).
Публикации:
  • telegram/news.db — все посты (самый полный источник для Telegram);
  • jobs/*.json, tg/*.json, weeks/*/articles.json — всё, что когда-либо выгружалось.
Старые файлы не удаляются и не изменяются. Импорт только добавляет: уже собранное
в 4.0 не перезаписывается архивным (в 3.0 текст обрезался до 500 символов).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from ..connectors.telegram import title_from_text
from ..core.db import Database
from ..core.timeutil import now_iso, parse_any
from ..domain.models import IngestStats, RawItem, Source
from ..telegram_service import normalize_channel
from .ingest import ingest
from .sources import SourceRepo

log = logging.getLogger(__name__)
META_KEY = "import30"
_TG_URL = re.compile(r"^https?://t\.me/(?:s/)?([A-Za-z0-9_]{3,})/(\d+)")


def _json_articles(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [a for a in data if isinstance(a, dict)]
    arts = data.get("articles") if isinstance(data, dict) else None
    return [a for a in arts if isinstance(a, dict)] if isinstance(arts, list) else []


class LegacyImporter:
    def __init__(self, db: Database, repo: SourceRepo, data_dir: Path, settings, builtin_sources,
                 log_fn: Optional[Callable[[str], None]] = None):
        self.db, self.repo, self.dir = db, repo, Path(data_dir)
        self.settings, self.builtin = settings, builtin_sources
        self.say = log_fn or (lambda m: log.info(m))
        self._by_name: dict[str, Source] = {}

    # ─── источники ───────────────────────────────────────────────────────────
    def import_sources(self) -> dict:
        added = self.repo.sync_builtin(self.builtin, self.settings.get("sources", "overrides") or {})
        custom = 0
        for s in self.settings.get("sources", "custom") or []:
            if not s.get("url") or self.repo.by_key(s.get("id", "")):
                continue
            try:
                self.repo.add_rss(s.get("name", s["url"]), s["url"], s.get("category", "Свои"),
                                  s.get("region", ""), bool(s.get("enabled", True)), key=s.get("id"))
                custom += 1
            except ValueError:
                pass
        channels = list(self.settings.get("telegram", "channels") or [])
        news_db = self.dir / "telegram" / "news.db"
        if news_db.exists():
            try:
                c = sqlite3.connect(news_db)
                channels += [r[0] for r in c.execute("SELECT DISTINCT channel FROM posts") if r[0]]
                c.close()
            except sqlite3.Error:
                pass
        tg = 0
        for ch in dict.fromkeys(normalize_channel(c) for c in channels):
            if ch and not self.repo.by_key("tg:" + ch.lower()):
                self.repo.ensure_telegram(ch)
                tg += 1
        return {"builtin": added, "custom": custom, "telegram": tg}

    def _site_source(self, a: dict) -> Source:
        sid = (a.get("source_id") or "").strip()
        if sid:
            s = self.repo.by_key(sid)
            if s:
                return s
        name = (a.get("source_name") or "").strip() or "Неизвестный источник"
        if not self._by_name:
            self._by_name = {s.name.lower(): s for s in self.repo.list()}
        s = self._by_name.get(name.lower())
        if s is None:
            s = self.repo.ensure_legacy(name, "rss")
            self._by_name[name.lower()] = s
        return s

    # ─── публикации ──────────────────────────────────────────────────────────
    def import_news_db(self, path: Optional[Path] = None) -> IngestStats:
        path = Path(path) if path else self.dir / "telegram" / "news.db"
        total = IngestStats()
        if not path.exists():
            return total
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        groups: dict[str, list[RawItem]] = defaultdict(list)
        try:
            for r in c.execute("SELECT channel, message_id, date, text, link FROM posts"):
                text = (r["text"] or "").strip()
                if not text or not r["channel"]:
                    continue
                groups[normalize_channel(r["channel"])].append(RawItem(
                    external_id=str(r["message_id"]), title=title_from_text(text), body=text,
                    url=r["link"] or "", published_at=parse_any(r["date"])))
        finally:
            c.close()
        for ch, items in groups.items():
            src = self.repo.ensure_telegram(ch)
            total = total + ingest(self.db, src, items, origin="import30", update_existing=False)
        return total

    def _article_to_raw(self, a: dict) -> tuple[Source, RawItem] | None:
        url = (a.get("url") or "").strip()
        name = (a.get("source_name") or "").strip()
        title = a.get("title") or ""
        text = a.get("summary") or ""
        pub = parse_any(a.get("published_at"))
        m = _TG_URL.match(url)
        is_tg = a.get("set_kind") == "tg" or name.startswith("@") or bool(m)
        if is_tg:
            ch = m.group(1) if m else normalize_channel(name)
            if not ch or not text.strip():          # фото без подписи («(без текста)» в 3.0)
                return None
            src = self.repo.ensure_telegram(ch)
            ext = m.group(2) if m else "h:" + hashlib.sha1(f"{text}|{pub}".encode()).hexdigest()
            return src, RawItem(external_id=ext, title=title_from_text(text) or title, body=text,
                                url=url, published_at=pub)
        src = self._site_source(a)
        ext = url or "h:" + hashlib.sha1(f"{name}|{title}|{a.get('published_at')}".encode()).hexdigest()
        return src, RawItem(external_id=ext, title=title, summary=text, url=url, published_at=pub)

    def import_json_history(self) -> tuple[IngestStats, int]:
        files: list[Path] = []
        for sub in ("jobs", "tg"):
            files += sorted((self.dir / sub).glob("*.json"))
        files += sorted((self.dir / "weeks").glob("*/articles.json"))
        groups: dict[int, tuple[Source, dict[str, RawItem]]] = {}
        for f in files:
            for a in _json_articles(f):
                res = self._article_to_raw(a)
                if not res:
                    continue
                src, raw = res
                bucket = groups.setdefault(src.id, (src, {}))[1]
                bucket.setdefault(raw.external_id, raw)       # одна запись на публикацию
        total = IngestStats()
        for src, items in groups.values():
            total = total + ingest(self.db, src, items.values(), origin="import30",
                                   update_existing=False)
        return total, len(files)

    # ─── всё вместе ──────────────────────────────────────────────────────────
    def has_legacy_data(self) -> bool:
        return any([(self.dir / "telegram" / "news.db").exists(),
                    any((self.dir / "jobs").glob("*.json")),
                    any((self.dir / "tg").glob("*.json")),
                    any((self.dir / "weeks").glob("*/articles.json"))])

    def run(self) -> dict:
        self.say("Перенос данных 3.0 в единую базу…")
        src = self.import_sources()
        tg = self.import_news_db()
        hist, nfiles = self.import_json_history()
        report = {
            "at": now_iso(),
            "sources": src,
            "telegram_db": tg.__dict__,
            "history": {**hist.__dict__, "files": nfiles},
            "items_total": self.db.scalar("SELECT COUNT(*) FROM items", default=0),
        }
        self.db.set_meta(META_KEY, json.dumps(report, ensure_ascii=False))
        self.say(f"Перенос завершён: публикаций в базе {report['items_total']}")
        return report


def import_if_needed(db: Database, repo: SourceRepo, data_dir: Path, settings, builtin) -> Optional[dict]:
    """Выполнить перенос, если он ещё не делался. Возвращает отчёт или None."""
    if db.get_meta(META_KEY):
        # Перенос уже был. Добавляем только встроенные источники, появившиеся в обновлении;
        # свои источники и каналы дальше живут в базе, а не в settings.json.
        repo.sync_builtin(builtin)
        return None
    return LegacyImporter(db, repo, data_dir, settings, builtin).run()
