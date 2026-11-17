"""
«Один сюжет»: какие основные строки выгрузки рассказывают о разных частях одного события.

Склейка (deduplicator.py) отвечает на вопрос «это тот же факт?» и ошибаться не должна.
Здесь вопрос мягче — «это одна история?»: анонс пуска, сам пуск, авария и разбор аварии.
Такие строки не склеиваются, а получают в CSV столбец «Связанные строки» с номерами
соседей — ChatGPT по промпту решает, объединять ли их. Ошибка здесь безвредна.

Правила (замер bench/, ноябрь 2026): модель e5-small по заголовкам, порог 0,92,
окно по датам и сверка номеров как у склейки, не больше 5 соседей на строку.
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable, Optional

import numpy as np

from ..core.db import Database
from ..core.timeutil import now_iso
from ..deduplicator import may_merge
from ..domain.text import fix_mojibake

LogFn = Optional[Callable[[str], None]]
MAX_NEIGHBOURS = 5


def _hash(t: str) -> str:
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:16]


class StoryLinker:
    def __init__(self, db: Database, settings, encode: Optional[Callable] = None):
        self.db = db
        self.settings = settings
        self._encode = encode                      # для тестов; по умолчанию story_model.encode

    def cfg(self) -> dict:
        return self.settings.get("dedup") or {}

    def enabled(self) -> bool:
        return bool(self.cfg().get("related", True))

    def vectors(self, rows: list[dict], log: LogFn = None) -> np.ndarray:
        texts = [fix_mojibake(r.get("title") or "") for r in rows]
        hashes = [_hash(t) for t in texts]
        ids = [r["id"] for r in rows]
        cached = {}
        for k in range(0, len(ids), 500):
            part = ids[k:k + 500]
            for r in self.db.query(f"SELECT item_id, text_hash, vec FROM story_vectors "
                                   f"WHERE item_id IN ({','.join('?' * len(part))})", tuple(part)):
                cached[r["item_id"]] = (r["text_hash"], np.frombuffer(r["vec"], dtype=np.float32))
        out: list = [None] * len(rows)
        missing = []
        for pos, (iid, h) in enumerate(zip(ids, hashes)):
            hit = cached.get(iid)
            if hit and hit[0] == h:
                out[pos] = hit[1]
            else:
                missing.append(pos)
        if missing:
            enc = self._encode
            if enc is None:
                from ..story_model import encode as enc
            new = enc([texts[p] for p in missing], log)
            now = now_iso()
            with self.db.tx():
                for p, vec in zip(missing, new):
                    out[p] = vec
                    self.db.execute("INSERT OR REPLACE INTO story_vectors (item_id, text_hash, vec, created_at) "
                                    "VALUES (?,?,?,?)", (ids[p], hashes[p], vec.astype(np.float32).tobytes(), now))
        return np.vstack(out) if out else np.zeros((0, 384), dtype=np.float32)

    def link(self, rows: list[dict], log: LogFn = None) -> dict[int, list[int]]:
        """rows — основные строки выгрузки → {item_id: [item_id соседей по сюжету]}."""
        if len(rows) < 2 or not self.enabled():
            return {}
        cfg = self.cfg()
        thr = float(cfg.get("related_threshold", 0.92))
        window = float(cfg.get("window_days", 4) or 0) or None
        guard = bool(cfg.get("number_guard", True))
        try:
            emb = self.vectors(rows, log)
        except Exception as e:                                       # noqa: BLE001 — выгрузка важнее
            if log:
                log(f"⚠ Связанные строки не определены: модель сюжетов недоступна ({str(e)[:100]})")
            return {}
        sims = emb @ emb.T
        arts = [{"title": r.get("title") or "", "published_at": (r.get("published_at") or "")[:16].replace("T", " ")}
                for r in rows]
        out: dict[int, list[int]] = {}
        for i in range(len(rows)):
            order = np.argsort(-sims[i])
            near = []
            for j in order:
                j = int(j)
                if j == i:
                    continue
                if float(sims[i, j]) < thr or len(near) >= MAX_NEIGHBOURS:
                    break
                if may_merge(arts[i], arts[j], window, guard):
                    near.append(rows[j]["id"])
            if near:
                out[rows[i]["id"]] = near
        if log:
            log(f"Один сюжет, разные части события: связано строк {len(out)}")
        return out

    def prune(self, keep_days: int = 60) -> int:
        cur = self.db.execute(
            "DELETE FROM story_vectors WHERE item_id IN (SELECT id FROM items WHERE "
            "COALESCE(published_at, fetched_at) < strftime('%Y-%m-%dT%H:%M:%SZ','now',?))",
            (f"-{int(keep_days)} days",))
        return cur.rowcount or 0


def related_json(ids: list[int]) -> Optional[str]:
    return json.dumps(ids) if ids else None
