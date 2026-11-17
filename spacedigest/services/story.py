"""
«Один сюжет»: какие основные строки выгрузки рассказывают о разных частях одного события.

Склейка (deduplicator.py) отвечает на вопрос «это тот же факт?» и ошибаться не должна.
Здесь вопрос мягче — «это одна история?»: анонс пуска, сам пуск, авария и разбор аварии.
Такие строки не склеиваются, а получают в CSV столбец «Связанные строки» с номерами
соседей — ChatGPT по промпту решает, объединять ли их. Ошибка здесь безвредна.

Правила (замер bench/, ноябрь 2026): та же модель, что у склейки (MiniLM, заголовок + начало
текста, векторы из её кэша), но порог ниже — 0,76 против 0,82; окно по датам и сверка номеров
как у склейки, не больше 5 соседей на строку. Отдельная модель e5-small на тех же данных
находила меньше (76 против 97 пар при той же доле ошибок) — поэтому её нет.
Без нейросети (TF-IDF) столбец не заполняется: у TF-IDF другая шкала близости.
"""
from __future__ import annotations

import json
from typing import Callable, Optional

import numpy as np

from ..core.db import Database
from ..deduplicator import may_merge

LogFn = Optional[Callable[[str], None]]
MAX_NEIGHBOURS = 5


class StoryLinker:
    def __init__(self, db: Database, settings, encode: Optional[Callable] = None,
                 vectors=None, article: Optional[Callable] = None):
        self.db = db
        self.settings = settings
        self._encode = encode                      # для тестов: encode(texts, log) → векторы
        self._vectors = vectors                    # VectorCache склейки (MiniLM + кэш в базе)
        self._article = article                    # строка выгрузки → статья для дедупликатора

    def cfg(self) -> dict:
        return self.settings.get("dedup") or {}

    def enabled(self) -> bool:
        return bool(self.cfg().get("related", True)) and self.cfg().get("engine") != "tfidf"

    def vectors(self, rows: list[dict], log: LogFn = None) -> np.ndarray:
        from ..deduplicator import build_text
        arts = [self._article(r) if self._article else {"_item_id": r["id"], "title": r.get("title") or "",
                                                        "summary": r.get("summary") or ""} for r in rows]
        texts = [build_text(a) for a in arts]
        if self._encode is not None:
            return self._encode(texts, log)
        if self._vectors is None:
            raise RuntimeError("нет кэша векторов")
        return self._vectors.neural_vectors(arts, texts, log)   # обычно всё уже посчитано при склейке

    def link(self, rows: list[dict], log: LogFn = None) -> dict[int, list[int]]:
        """rows — основные строки выгрузки → {item_id: [item_id соседей по сюжету]}."""
        if len(rows) < 2 or not self.enabled():
            return {}
        cfg = self.cfg()
        thr = float(cfg.get("story_threshold", 0.76))
        window = float(cfg.get("window_days", 4) or 0) or None
        guard = bool(cfg.get("number_guard", True))
        try:
            emb = self.vectors(rows, log)
        except Exception as e:                                       # noqa: BLE001 — выгрузка важнее
            if log:
                log(f"⚠ Связанные строки не определены: нейросеть недоступна ({str(e)[:100]})")
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


def related_json(ids: list[int]) -> Optional[str]:
    return json.dumps(ids) if ids else None
