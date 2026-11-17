"""
Сбор: задачи очереди, которые опрашивают источники и складывают новости в базу.

collect_kind   — раздать по задаче на каждый включённый источник нужного типа;
collect_source / collect_telegram — один источник: коннектор → приём в базу →
                 «здоровье» источника (Telegram отдельным типом, по одному за раз).
"""
from __future__ import annotations

import logging

from ..connectors.base import ConnectorError
from ..core.jobs import JobContext, JobQueue, PermanentError
from .ingest import ingest
from .sources import SourceRepo

log = logging.getLogger(__name__)


class Collector:
    def __init__(self, repo: SourceRepo, queue: JobQueue, connectors: dict, fulltext=None):
        self.repo = repo
        self.queue = queue
        self.connectors = connectors                 # kind → коннектор
        self.fulltext = fulltext                     # FullText: дотянуть статьи после сбора ленты

    @staticmethod
    def job_type_for(kind: str) -> str:
        # Telegram — отдельный тип задач: один аккаунт, строго по одному каналу за раз
        return "collect_telegram" if kind == "telegram" else "collect_source"

    def enqueue_source(self, source_id: int, priority: int = 0) -> int:
        src = self.repo.get(source_id)
        kind = src.kind if src else "rss"
        return self.queue.enqueue(self.job_type_for(kind), {"source_id": source_id},
                                  dedupe_key=f"collect:{source_id}", priority=priority,
                                  max_attempts=1)    # повтор — на следующем плановом запуске

    def enqueue_kind(self, kind: str, priority: int = 0) -> list[int]:
        return [self.enqueue_source(s.id, priority) for s in self.repo.list(kind=kind, enabled=True)
                if s.url or s.kind == "telegram"]

    # ─── обработчики задач ───────────────────────────────────────────────────
    def job_collect_kind(self, ctx: JobContext) -> dict:
        kind = ctx.payload.get("kind")
        if kind not in self.connectors:
            raise PermanentError(f"нет коннектора для «{kind}»")
        ids = self.enqueue_kind(kind)
        ctx.log(f"Поставлено в очередь источников: {len(ids)}")
        return {"queued": len(ids)}

    def job_collect_source(self, ctx: JobContext) -> dict:
        src = self.repo.get(int(ctx.payload.get("source_id", 0)))
        if src is None:
            raise PermanentError("источник удалён")
        connector = self.connectors.get(src.kind)
        if connector is None:
            raise PermanentError(f"нет коннектора для «{src.kind}»")
        state = self.repo.state(src.id)
        try:
            res = connector.fetch(src, state, log=ctx.log)
        except ConnectorError as e:
            n = self.repo.record_failure(src.id, str(e))
            ctx.log(f"✗ {src.name}: {e}")
            # Ошибку источника не «повторяем» сразу: следующий плановый запуск и так придёт
            raise PermanentError(f"{src.name}: {e} (неудач подряд: {n})")
        except Exception as e:                                   # noqa: BLE001 — неожиданное
            self.repo.record_failure(src.id, f"{type(e).__name__}: {e}")
            raise
        if res.note:
            ctx.log(res.note)
        if res.not_modified:
            self.repo.record_success(src.id, res.state, 0)
            ctx.log(f"= {src.name}: лента не менялась")
            return {"source": src.key, "new": 0, "not_modified": True}
        first_run = self.repo.db.scalar("SELECT last_ok_at FROM source_state WHERE source_id = ?",
                                        (src.id,)) is None
        stats = ingest(self.repo.db, src, res.items, first_run=first_run)
        self.repo.record_success(src.id, res.state, stats.new)
        if stats.new and src.kind == "rss" and self.fulltext is not None and \
                (self.fulltext.cfg()[0] or src.config.get("html")):
            self.queue.enqueue("fulltext", {"source_id": src.id}, dedupe_key=f"fulltext:{src.id}", max_attempts=1)
        ctx.log(f"✓ {src.name}: новых {stats.new}, обновлено {stats.updated}, "
                f"без изменений {stats.unchanged}")
        return {"source": src.key, "new": stats.new, "updated": stats.updated,
                "unchanged": stats.unchanged, "skipped": stats.skipped}


def job_fulltext(fulltext, ctx: JobContext) -> dict:
    """Дотянуть полный текст: {source_id} — новые статьи источника; {days} — догрузка за N дней."""
    sid = ctx.payload.get("source_id")
    days = int(ctx.payload.get("days") or 3)
    total = {"ok": 0, "same": 0, "failed": 0, "dated": 0}
    while True:
        rows = fulltext.pending(int(sid) if sid else None, days=days)
        if not rows:
            break
        res = fulltext.process(rows, log=ctx.log)
        for k in total:
            total[k] += res.get(k, 0)
        if sid:                       # для одного источника — одна порция за запуск
            break
        ctx.progress(min(95, (total["ok"] + total["same"] + total["failed"]) // 5))
    ctx.log(f"Готово. Полный текст взят для {total['ok']} статей.")
    return total
