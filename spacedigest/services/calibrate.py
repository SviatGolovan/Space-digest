"""
Подбор порога дедупликации по вашим данным.

Программа берёт свежие новости, находит пары «на грани» (близость около текущего порога)
и показывает их по одной: «одно событие» или «разные». По ответам выбирается порог,
при котором ошибок меньше всего. Ошибочное объединение считается дороже пропущенного
повтора: «уже было» убирает новость из CSV целиком.

Ответы копятся (таблица dedup_labels) — повторная калибровка уточняет порог, а не начинает заново.
У нейросети и TF-IDF разные шкалы близости, поэтому ответы хранятся отдельно для каждого движка.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..core.db import Database
from ..core.timeutil import iso_after, now_iso
from .export import ExportService, full_text, local_dt

MAX_ITEMS = 600            # сколько свежих новостей сравнивать
FALSE_MERGE_COST = 1.5     # ошибочно «одно событие» — дороже, чем пропущенный повтор
MIN_LABELS = 8


def _brief(r: dict) -> dict:
    d = local_dt(r["published_at"])
    return {"id": r["id"], "title": r["title"], "source": r["source_name"], "kind": r["kind"],
            "url": r["url"], "published": d.strftime("%d.%m %H:%M") if d else "",
            "text": full_text(r)[:420]}


def best_threshold(labels: list[tuple[float, bool]], cost: float = FALSE_MERGE_COST) -> Optional[dict]:
    """labels: [(близость, одно_событие)]. → {threshold, errors, accuracy} или None, если мало данных."""
    if len(labels) < MIN_LABELS or len({s for _, s in labels}) < 2:
        return None
    sims = sorted({round(x, 4) for x, _ in labels})
    cands = [sims[0] - 0.01] + [(a + b) / 2 for a, b in zip(sims, sims[1:])] + [sims[-1] + 0.01]

    def score(t):
        fm = sum(1 for x, same in labels if x >= t and not same)        # объединили разные
        miss = sum(1 for x, same in labels if x < t and same)           # пропустили повтор
        return fm * cost + miss, fm, miss
    best = min(cands, key=lambda t: (score(t)[0], -t))                  # при равенстве — строже
    _, fm, miss = score(best)
    return {"threshold": round(float(best), 3), "false_merges": fm, "missed": miss,
            "accuracy": round(1 - (fm + miss) / len(labels), 3), "labels": len(labels)}


class Calibrator:
    def __init__(self, db: Database, settings, exports: ExportService):
        self.db = db
        self.settings = settings
        self.exports = exports

    def threshold(self) -> float:
        return float((self.settings.get("dedup") or {}).get("threshold", 0.82))

    def _rows(self, days: int) -> list[dict]:
        return self.db.query("""
            SELECT i.id, i.title, i.summary, i.body, i.url, i.published_at, s.name AS source_name, s.kind AS kind
            FROM items i JOIN sources s ON s.id = i.source_id
            WHERE i.origin IN ('collect', 'import30') AND COALESCE(i.published_at, i.fetched_at) >= ?
            ORDER BY COALESCE(i.published_at, i.fetched_at) DESC LIMIT ?""",
            (iso_after(minutes=-days * 1440), MAX_ITEMS))

    def pairs(self, n: int = 20, days: int = 7, log=None) -> dict:
        rows = self._rows(days)
        if len(rows) < 2:
            rows = self._rows(60)
        if len(rows) < 2:
            raise ValueError("мало новостей для сравнения — соберите новости и попробуйте снова")
        arts = [self.exports._article(r) for r in rows]
        from ..deduplicator import build_text
        engine = (self.settings.get("dedup") or {}).get("engine", "auto")
        emb, backend = self.exports.vectors.encoder(engine)(arts, [build_text(a) for a in arts], log)
        sim = emb @ emb.T
        sim = sim.toarray() if hasattr(sim, "toarray") else np.asarray(sim)
        thr = self.threshold()
        lo, hi = thr - 0.15, min(0.99, thr + 0.10)
        done = {(r["a"], r["b"]) for r in self.db.query("SELECT a, b FROM dedup_labels WHERE backend = ?", (backend,))}
        iu = np.triu_indices(len(rows), k=1)
        vals = sim[iu]
        mask = (vals >= lo) & (vals <= hi)
        cand = [(float(vals[k]), int(iu[0][k]), int(iu[1][k])) for k in np.nonzero(mask)[0]]
        cand = [c for c in cand if (min(rows[c[1]]["id"], rows[c[2]]["id"]),
                                    max(rows[c[1]]["id"], rows[c[2]]["id"])) not in done]
        # равномерно по шкале близости: корзины по 0.025, берём по кругу из каждой
        bins: dict[int, list] = {}
        for c in sorted(cand, key=lambda c: -c[0]):
            bins.setdefault(int((c[0] - lo) / 0.025), []).append(c)
        picked, used = [], set()
        while len(picked) < n and any(bins.values()):
            for key in sorted(bins):
                while bins[key]:
                    s, i, j = bins[key].pop()
                    if i in used or j in used:              # одна новость — в одной паре
                        continue
                    used.update((i, j)); picked.append((s, i, j))
                    break
                if len(picked) >= n:
                    break
        picked.sort(key=lambda c: np.random.random())
        return {"backend": backend, "threshold": thr, "range": [round(lo, 3), round(hi, 3)],
                "pairs": [{"similarity": round(s, 4), "a": _brief(rows[i]), "b": _brief(rows[j])} for s, i, j in picked],
                "summary": self.result(backend)}

    def label(self, a: int, b: int, same: bool, similarity: float, backend: str) -> dict:
        a, b = min(a, b), max(a, b)
        self.db.execute("INSERT OR REPLACE INTO dedup_labels (a, b, backend, similarity, same, created_at) "
                        "VALUES (?,?,?,?,?,?)", (a, b, backend, float(similarity), int(bool(same)), now_iso()))
        return self.result(backend)

    def result(self, backend: str) -> dict:
        labels = [(r["similarity"], bool(r["same"])) for r in
                  self.db.query("SELECT similarity, same FROM dedup_labels WHERE backend = ?", (backend,))]
        thr = self.threshold()
        cur_fm = sum(1 for x, s in labels if x >= thr and not s)
        cur_miss = sum(1 for x, s in labels if x < thr and s)
        return {"backend": backend, "labels": len(labels), "same": sum(1 for _, s in labels if s),
                "current": {"threshold": thr, "false_merges": cur_fm, "missed": cur_miss},
                "best": best_threshold(labels), "need": max(0, MIN_LABELS - len(labels))}

    def apply(self, threshold: float) -> float:
        t = round(min(0.97, max(0.3, float(threshold))), 3)
        self.settings.update({"dedup": {"threshold": t}})
        return t

    def reset(self, backend: Optional[str] = None) -> int:
        cur = self.db.execute("DELETE FROM dedup_labels" + (" WHERE backend = ?" if backend else ""),
                              (backend,) if backend else ())
        return cur.rowcount or 0
