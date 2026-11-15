"""
Векторы смысловой близости с кэшем в базе.

Нейросеть считает вектор новости один раз; дальше он берётся из таблицы item_vectors.
Если текст новости изменился (обновили статью) — вектор пересчитывается.
Запасной TF-IDF не кэшируется: его словарь строится заново на каждом наборе текстов.
"""
from __future__ import annotations

import hashlib
from typing import Callable, Optional

import numpy as np

from ..core.db import Database
from ..core.timeutil import now_iso

LogFn = Optional[Callable[[str], None]]
NEURAL_MODEL_ID = "multilingual-MiniLM-L12-v2"


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class VectorCache:
    def __init__(self, db: Database, neural: Optional[Callable] = None,
                 tfidf: Optional[Callable] = None, model_id: str = NEURAL_MODEL_ID):
        """neural(texts, log) → нормированная матрица float32; tfidf(texts, log) → матрица.
        По умолчанию — движки из deduplicator (импортируются лениво)."""
        self.db = db
        self._neural = neural
        self._tfidf = tfidf
        self.model_id = model_id

    # ─── движки ──────────────────────────────────────────────────────────────
    def _encode_neural(self, texts: list[str], log: LogFn) -> np.ndarray:
        if self._neural:
            return self._neural(texts, log)
        from .. import deduplicator as D
        emb, _ = D._encode_neural(texts, D.DEFAULT_MODEL, log)
        return emb

    def _encode_tfidf(self, texts: list[str], log: LogFn):
        if self._tfidf:
            return self._tfidf(texts, log)
        from .. import deduplicator as D
        return D._encode_tfidf(texts, log)

    # ─── основной метод ──────────────────────────────────────────────────────
    def encoder(self, engine: str = "auto") -> Callable:
        """Функция для run_deduplication(encoder=...)."""
        def encode(articles: list[dict], texts: list[str], log: LogFn):
            if engine != "tfidf":
                try:
                    return self.neural_vectors(articles, texts, log), "sentence-transformers"
                except Exception as e:                     # нет модели / нет сети
                    if log:
                        log(f"⚠ Нейросетевой движок недоступен ({str(e)[:90]}). Переход на TF-IDF.")
            return self._encode_tfidf(texts, log), "tfidf"
        return encode

    def neural_vectors(self, articles: list[dict], texts: list[str], log: LogFn = None) -> np.ndarray:
        ids = [a.get("_item_id") for a in articles]
        hashes = [_hash(t) for t in texts]
        cached = self.load([i for i in ids if i is not None])
        out: list[Optional[np.ndarray]] = [None] * len(texts)
        missing: list[int] = []
        for pos, (iid, h) in enumerate(zip(ids, hashes)):
            hit = cached.get(iid) if iid is not None else None
            if hit is not None and hit[0] == h:
                out[pos] = hit[1]
            else:
                missing.append(pos)
        if log:
            log(f"Векторы: из кэша {len(texts) - len(missing)}, считаем {len(missing)}.")
        if missing:
            fresh = np.asarray(self._encode_neural([texts[p] for p in missing], log), dtype=np.float32)
            rows = []
            for k, pos in enumerate(missing):
                out[pos] = fresh[k]
                if ids[pos] is not None:
                    rows.append((ids[pos], self.model_id, hashes[pos], fresh[k].tobytes(), now_iso()))
            if rows:
                with self.db.tx():
                    self.db.conn().executemany(
                        "INSERT OR REPLACE INTO item_vectors (item_id, model, text_hash, vec, created_at) "
                        "VALUES (?,?,?,?,?)", rows)
        if not out:
            return np.zeros((0, 1), dtype=np.float32)
        return np.vstack(out).astype(np.float32)

    def load(self, ids: list[int]) -> dict[int, tuple[str, np.ndarray]]:
        res: dict[int, tuple[str, np.ndarray]] = {}
        for k in range(0, len(ids), 500):
            chunk = ids[k:k + 500]
            for r in self.db.query(
                    f"SELECT item_id, text_hash, vec FROM item_vectors WHERE model = ? "
                    f"AND item_id IN ({','.join('?' * len(chunk))})", (self.model_id, *chunk)):
                res[r["item_id"]] = (r["text_hash"], np.frombuffer(r["vec"], dtype=np.float32))
        return res

    def prune(self, keep_days: int = 60) -> int:
        """Убрать векторы старых новостей: сверка смотрит максимум на 30 дней назад."""
        cur = self.db.execute(
            "DELETE FROM item_vectors WHERE item_id IN (SELECT id FROM items WHERE "
            "COALESCE(published_at, fetched_at) < strftime('%Y-%m-%dT%H:%M:%SZ','now',?))",
            (f"-{int(keep_days)} days",))
        return cur.rowcount or 0
