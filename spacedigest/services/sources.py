"""Источники: список, добавление, изменение и «здоровье» — всё через таблицу sources."""
from __future__ import annotations

import json
import uuid
from typing import Iterable, Optional

from ..core.db import Database
from ..core.timeutil import now_iso
from ..domain.models import SOURCE_KINDS, Source, SourceState
from ..telegram_service import normalize_channel

# После стольких неудач подряд источник считается «проблемным»
PROBLEM_AFTER = 5


class SourceRepo:
    def __init__(self, db: Database):
        self.db = db

    # ─── чтение ──────────────────────────────────────────────────────────────
    def get(self, source_id: int) -> Optional[Source]:
        r = self.db.one("SELECT * FROM sources WHERE id = ?", (source_id,))
        return Source.from_row(r) if r else None

    def by_key(self, key: str) -> Optional[Source]:
        r = self.db.one("SELECT * FROM sources WHERE key = ?", (key,))
        return Source.from_row(r) if r else None

    def list(self, kind: Optional[str] = None, enabled: Optional[bool] = None) -> list[Source]:
        where, params = [], []
        if kind:
            where.append("kind = ?"); params.append(kind)
        if enabled is not None:
            where.append("enabled = ?"); params.append(int(enabled))
        sql = "SELECT * FROM sources" + (" WHERE " + " AND ".join(where) if where else "") + \
              " ORDER BY kind, builtin DESC, name COLLATE NOCASE"
        return [Source.from_row(r) for r in self.db.query(sql, params)]

    def health(self, kind: Optional[str] = None) -> list[dict]:
        """Источники вместе с состоянием сбора и количеством собранного."""
        sql = """
            SELECT s.*, st.last_attempt_at, st.last_ok_at, st.last_new_at, st.last_error,
                   COALESCE(st.consecutive_failures, 0) AS consecutive_failures,
                   COALESCE(st.last_new_items, 0)       AS last_new_items,
                   (SELECT COUNT(*) FROM items i WHERE i.source_id = s.id) AS items_total,
                   (SELECT MAX(published_at) FROM items i WHERE i.source_id = s.id) AS last_item_at
            FROM sources s LEFT JOIN source_state st ON st.source_id = s.id
        """ + (" WHERE s.kind = ?" if kind else "") + " ORDER BY s.kind, s.name COLLATE NOCASE"
        rows = self.db.query(sql, (kind,) if kind else ())
        for r in rows:
            r["problem"] = r["consecutive_failures"] >= PROBLEM_AFTER
        return rows

    # ─── изменение ───────────────────────────────────────────────────────────
    def _insert(self, *, key: str, kind: str, name: str, url: str = "", category: str = "",
                region: str = "", builtin: bool = False, enabled: bool = True,
                priority: int = 0, config: Optional[dict] = None, scope: str = "all") -> int:
        assert kind in SOURCE_KINDS, kind
        cur = self.db.execute(
            "INSERT INTO sources (key, kind, name, url, category, region, builtin, enabled, "
            "priority, config, created_at, scope) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, kind, name, url, category, region, int(builtin), int(enabled), priority,
             json.dumps(config or {}, ensure_ascii=False), now_iso(), scope))
        return int(cur.lastrowid)

    # Ключи config, которыми владеет встроенный список СЛК (остальное — выбор пользователя)
    SLK_KEYS = ("html", "item_selector", "slk_trusted", "general", "fulltext")

    def sync_slk(self, slk: Iterable[dict], telegram: Iterable[dict] = ()) -> int:
        """Источники СЛК: добавить недостающие (scope = slk), обновить описание встроенных.
        Telegram-каналы компаний добавляются один раз: удалённый пользователем не вернётся."""
        added = 0
        with self.db.tx():
            for s in slk:
                row = self.db.one("SELECT id, url, config FROM sources WHERE key = ?", (s["id"],))
                if row is None:
                    if self.db.one("SELECT 1 FROM sources WHERE kind='rss' AND url = ?", (s["url"],)):
                        continue                       # такой сайт уже добавлен пользователем
                    self._insert(key=s["id"], kind="rss", name=s["name"], url=s["url"],
                                 category=s.get("category", ""), region=s.get("region", ""),
                                 builtin=True, enabled=bool(s.get("enabled", True)),
                                 config=s.get("config") or {}, scope="slk")
                    added += 1
                    continue
                cfg = json.loads(row["config"] or "{}")
                override = cfg.get("url_override")          # адрес, исправленный в старом парсере
                keep_html = cfg.get("html") if override else None
                for k in self.SLK_KEYS:
                    cfg.pop(k, None)
                cfg.update(s.get("config") or {})
                if override:
                    cfg["html"] = bool(keep_html)
                url = override or s["url"]
                self.db.execute("UPDATE sources SET name=?, url=?, category=?, region=?, builtin=1, config=? "
                                "WHERE id=?", (s["name"], url, s.get("category", ""),
                                               s.get("region", ""), json.dumps(cfg, ensure_ascii=False),
                                               row["id"]))
                if row["url"] != url:
                    self.reset_state(row["id"])
        for t in telegram:
            flag = f"slk_tg:{t['channel']}"
            if self.db.get_meta(flag):
                continue
            src = self.ensure_telegram(t["channel"])
            cfg = dict(src.config)
            if t.get("trusted"):
                cfg["slk_trusted"] = True
            self.update(src.id, config=cfg, name=t.get("name") or src.name)
            self.db.set_meta(flag, "1")
            added += 1
        return added

    def sync_builtin(self, builtin: Iterable[dict], overrides: Optional[dict] = None) -> int:
        """Добавить недостающие встроенные RSS-источники и обновить их описание.
        Флаг enabled у существующих не трогаем — это выбор пользователя."""
        overrides = overrides or {}
        added = 0
        with self.db.tx():
            for s in builtin:
                row = self.db.one("SELECT id, url FROM sources WHERE key = ?", (s["id"],))
                if row is None:
                    self._insert(key=s["id"], kind="rss", name=s["name"], url=s["url"],
                                 category=s.get("category", ""), region=s.get("region", ""),
                                 builtin=True,
                                 enabled=bool(overrides.get(s["id"], s.get("enabled", True))))
                    added += 1
                else:
                    self.db.execute("UPDATE sources SET name=?, url=?, category=?, region=?, builtin=1 "
                                    "WHERE id=?", (s["name"], s["url"], s.get("category", ""),
                                                   s.get("region", ""), row["id"]))
                    if row["url"] != s["url"]:
                        self.reset_state(row["id"])
                        if s.get("space_only"):          # адрес сменился на ленту с примесью — сразу фильтр
                            self.db.execute("UPDATE sources SET space_only=1 WHERE id=?", (row["id"],))
                if row is None and s.get("space_only"):
                    self.db.execute("UPDATE sources SET space_only=1 WHERE key=?", (s["id"],))
        return added

    def add_rss(self, name: str, url: str, category: str = "Свои", region: str = "",
                enabled: bool = True, key: Optional[str] = None) -> Source:
        name, url = name.strip(), url.strip()
        if not name or not url:
            raise ValueError("укажите название и адрес ленты")
        if not url.startswith(("http://", "https://")):
            raise ValueError("адрес должен начинаться с http:// или https://")
        if self.db.one("SELECT 1 FROM sources WHERE kind='rss' AND url = ?", (url,)):
            raise ValueError("источник с таким адресом уже есть")
        sid = self._insert(key=key or "custom_" + uuid.uuid4().hex[:8], kind="rss", name=name,
                           url=url, category=category or "Свои", region=region or "",
                           enabled=enabled)
        return self.get(sid)                                      # type: ignore[return-value]

    def ensure_telegram(self, channel: str, enabled: bool = True) -> Source:
        ch = normalize_channel(channel)
        if not ch:
            raise ValueError("укажите канал: @имя или ссылку t.me/имя")
        key = "tg:" + ch.lower()
        existing = self.by_key(key)
        if existing:
            return existing
        sid = self._insert(key=key, kind="telegram", name="@" + ch, url=ch,
                           category="Telegram", enabled=enabled)
        return self.get(sid)                                      # type: ignore[return-value]

    def ensure_legacy(self, name: str, kind: str = "rss") -> Source:
        """Источник, известный только по имени из старых выгрузок (адрес неизвестен)."""
        import re
        slug = re.sub(r"[^a-z0-9а-яё]+", "-", name.lower()).strip("-")[:60] or "unknown"
        key = f"legacy:{kind}:{slug}"
        s = self.by_key(key)
        if s:
            return s
        sid = self._insert(key=key, kind=kind, name=name, enabled=False,
                           category="Из архива 3.0")
        return self.get(sid)                                      # type: ignore[return-value]

    def update(self, source_id: int, **fields) -> Source:
        allowed = {"name", "url", "category", "region", "enabled", "priority", "config", "space_only",
                   "scope"}
        src = self.get(source_id)
        if not src:
            raise ValueError("источник не найден")
        sets, params = [], []
        for k, v in fields.items():
            if k not in allowed or v is None:
                continue
            if src.builtin and k in ("name", "url"):
                continue                          # описание встроенных задаётся кодом
            if k == "config":
                v = json.dumps(v, ensure_ascii=False)
            if k in ("enabled", "space_only"):
                v = int(bool(v))
            if k == "scope" and v not in ("all", "space", "slk"):
                continue
            sets.append(f"{k} = ?"); params.append(v)
        if sets:
            with self.db.tx():
                self.db.execute(f"UPDATE sources SET {', '.join(sets)} WHERE id = ?",
                                params + [source_id])
                if "url" in fields and fields["url"] != src.url and not src.builtin:
                    self.reset_state(source_id)
        return self.get(source_id)                                # type: ignore[return-value]

    def delete(self, source_id: int, with_items: bool = False) -> None:
        src = self.get(source_id)
        if not src:
            raise ValueError("источник не найден")
        if src.builtin:
            raise ValueError("встроенный источник нельзя удалить — его можно выключить")
        n = self.db.scalar("SELECT COUNT(*) FROM items WHERE source_id = ?", (source_id,), 0)
        if n and not with_items:
            # Собранные новости важнее источника: выключаем, а не удаляем
            self.update(source_id, enabled=False)
            return
        self.db.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    # ─── состояние сбора ─────────────────────────────────────────────────────
    def state(self, source_id: int) -> SourceState:
        r = self.db.one("SELECT etag, last_modified, resolved_url, cursor FROM source_state "
                        "WHERE source_id = ?", (source_id,))
        return SourceState(**r) if r else SourceState()

    def reset_state(self, source_id: int) -> None:
        self.db.execute("UPDATE source_state SET etag=NULL, last_modified=NULL, resolved_url=NULL "
                        "WHERE source_id = ?", (source_id,))

    def record_success(self, source_id: int, state: SourceState, new_items: int) -> None:
        now = now_iso()
        self.db.execute("""
            INSERT INTO source_state (source_id, etag, last_modified, resolved_url, cursor,
                last_attempt_at, last_ok_at, last_new_at, last_error, consecutive_failures, last_new_items)
            VALUES (?,?,?,?,?,?,?,?,NULL,0,?)
            ON CONFLICT (source_id) DO UPDATE SET
                etag = excluded.etag, last_modified = excluded.last_modified,
                resolved_url = COALESCE(excluded.resolved_url, source_state.resolved_url),
                cursor = COALESCE(excluded.cursor, source_state.cursor),
                last_attempt_at = excluded.last_attempt_at, last_ok_at = excluded.last_ok_at,
                last_new_at = COALESCE(excluded.last_new_at, source_state.last_new_at),
                last_error = NULL, consecutive_failures = 0,
                last_new_items = excluded.last_new_items
        """, (source_id, state.etag, state.last_modified, state.resolved_url, state.cursor,
              now, now, now if new_items else None, new_items))

    def record_failure(self, source_id: int, error: str) -> int:
        now = now_iso()
        self.db.execute("""
            INSERT INTO source_state (source_id, last_attempt_at, last_error, consecutive_failures)
            VALUES (?,?,?,1)
            ON CONFLICT (source_id) DO UPDATE SET
                last_attempt_at = excluded.last_attempt_at, last_error = excluded.last_error,
                consecutive_failures = source_state.consecutive_failures + 1
        """, (source_id, now, error[:500]))
        return int(self.db.scalar("SELECT consecutive_failures FROM source_state WHERE source_id=?",
                                  (source_id,), 0))
