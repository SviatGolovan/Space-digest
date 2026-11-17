"""
Ядро 4.0: база, источники, очередь, исполнители, планировщик — в одном месте.

Создаётся один раз при запуске приложения:
    core = Core(data_dir, settings, tg_service); core.start()
Веб-слой и будущие экраны обращаются к сервисам ядра, а не к файлам напрямую.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ..connectors.rss import RssConnector
from ..connectors.telegram import TelegramConnector
from ..services.collect import Collector
from ..services.export import ExportService
from ..services.legacy_import import import_if_needed
from ..services.sources import SourceRepo
from ..sources import SOURCES
from .db import Database
from .jobs import JobQueue, WorkerPool
from .scheduler import Scheduler

log = logging.getLogger(__name__)

DB_NAME = "spacedigest.db"


class Core:
    def __init__(self, data_dir: Path, settings, tg_service=None, *, threads: int = 4):
        self.data_dir = Path(data_dir)
        self.settings = settings
        self.db = Database(self.data_dir / DB_NAME)
        self.db.migrate()
        self.sources = SourceRepo(self.db)
        self.queue = JobQueue(self.db)
        self.workers = WorkerPool(self.queue, threads=threads)
        self.scheduler = Scheduler(self.db, self.queue)
        self.import_report: Optional[dict] = None

        connectors: dict = {"rss": RssConnector(timeout=int(settings.get("fetch", "timeout") or 15))}
        if tg_service is not None:
            connectors["telegram"] = TelegramConnector(
                tg_service, lambda: settings.get("telegram", "lookback_days") or 7)
        from ..services.fulltext import FullText
        self.fulltext = FullText(self.db, settings)
        self.collector = Collector(self.sources, self.queue, connectors, self.fulltext)
        self.exports = ExportService(self.db, settings)
        # Дайджест по РН сверхлёгкого класса: та же база, свои окно дат, предфильтр и промпт
        self.slk = ExportService(self.db, settings, vectors=self.exports.vectors, profile="slk")
        self.fulltext.gate = self.slk.filter.passes
        from ..services.calibrate import Calibrator
        self.calibrator = Calibrator(self.db, settings, self.exports)

        # Обработчики задач и их параллельность
        self.workers.register("collect_kind", self.collector.job_collect_kind, concurrency=2)
        self.workers.register("collect_source", self.collector.job_collect_source, concurrency=4)
        self.workers.register("collect_telegram", self.collector.job_collect_source, concurrency=1)
        self.workers.register("maintenance", self._job_maintenance, concurrency=1)
        self.workers.register("export_prepare", self._job_export, concurrency=1)
        self.workers.register("morning_export", self._job_morning, concurrency=1)
        from ..services.collect import job_fulltext
        self.workers.register("fulltext", lambda ctx: job_fulltext(self.fulltext, ctx), concurrency=3)

    # ─── запуск / остановка ──────────────────────────────────────────────────
    def prepare(self) -> None:
        """Перенос 3.0 (один раз) и расписания. Без запуска фоновых потоков."""
        self.import_report = import_if_needed(self.db, self.sources, self.data_dir,
                                              self.settings, SOURCES)
        from ..slk_sources import SLK_SOURCES, SLK_TELEGRAM
        try:
            n = self.sources.sync_slk(SLK_SOURCES, SLK_TELEGRAM)
            if n:
                log.info("Источники СЛК: добавлено %s", n)
        except Exception as e:                                   # noqa: BLE001 — не мешаем запуску
            log.warning("Источники СЛК не синхронизированы: %s", e)
        self.migrate_legacy_settings()
        self.apply_schedules()

    def apply_schedules(self) -> None:
        c = self.settings.get("collect") or {}
        self.scheduler.ensure("collect_sites", "collect_kind", int(c.get("sites_minutes", 60)),
                              enabled=bool(c.get("sites_auto", True)), payload={"kind": "rss"},
                              first_run_delay_minutes=1)
        self.scheduler.ensure("collect_telegram", "collect_kind", int(c.get("telegram_minutes", 30)),
                              enabled=bool(c.get("telegram_auto", False)), payload={"kind": "telegram"},
                              first_run_delay_minutes=2)
        self.scheduler.ensure("maintenance", "maintenance", 24 * 60, first_run_delay_minutes=10)
        m = self.settings.get("morning") or {}
        self.scheduler.ensure_daily("morning_export", "morning_export", m.get("time") or "09:00",
                                    enabled=bool(m.get("enabled")))

    def start(self) -> None:
        self.prepare()
        self.workers.start()
        self.scheduler.start()
        log.info("Ядро запущено: %s", self.db.path)

    def stop(self) -> None:
        self.scheduler.stop()
        self.workers.stop()
        self.db.close()

    def _job_export(self, ctx) -> dict:
        from .jobs import PermanentError
        p = ctx.payload
        svc = self.slk if p.get("profile") == "slk" else self.exports
        try:
            e = svc.prepare(mode=p.get("mode") or ("window" if svc.slk else "since_last"),
                            date_from=p.get("date_from", ""),
                                     date_to=p.get("date_to", ""), kinds=p.get("kinds") or ("rss", "telegram"),
                                     dedupe=p.get("dedupe"), log=ctx.log)
        except ValueError as ex:                      # «нет новостей» и т. п. — не повторять
            raise PermanentError(str(ex))
        return {"export_id": e["id"]}

    # ─── Telegram поверх единой базы ─────────────────────────────────────────
    def migrate_legacy_settings(self) -> None:
        """Один раз: настройки автосбора Telegram 3.0 → расписание ядра, старый цикл выключить."""
        if self.db.get_meta("tg_on_core"):
            return
        tg = self.settings.get("telegram") or {}
        self.settings.update({"collect": {"telegram_auto": bool(tg.get("auto_collect")),
                                          "telegram_minutes": int(tg.get("poll_minutes") or 30)},
                              "telegram": {"auto_collect": False}})
        for ch in tg.get("channels") or []:
            try:
                self.sources.ensure_telegram(ch)
            except ValueError:
                pass
        self.db.set_meta("tg_on_core", "1")

    def tg_channels(self) -> dict:
        rows = self.sources.health("telegram")
        return {"channels": [r["url"] for r in rows if r["enabled"]],
                "db_channels": [r["url"] for r in rows if r["items_total"]]}

    def tg_stats(self) -> dict:
        r = self.db.one("SELECT COUNT(*) AS n, MAX(i.published_at) AS last FROM items i "
                        "JOIN sources s ON s.id = i.source_id WHERE s.kind = 'telegram'")
        from ..services.export import local_dt
        last = local_dt(r["last"]) if r and r["last"] else None
        return {"ok": True, "total": r["n"] if r else 0,
                "last_date": last.strftime("%Y-%m-%d %H:%M") if last else ""}

    def query_items(self, kind: str, date_from: str = "", date_to: str = "",
                    channels: Optional[list] = None, limit: int = 20000) -> list[dict]:
        from ..services.export import local_day_bounds
        from ..telegram_service import normalize_channel
        where, params = ["s.kind = ?"], [kind]
        if date_from or date_to:
            lo, hi = local_day_bounds(date_from or "1970-01-01", date_to or "2999-12-31")
            where += ["i.published_at >= ?", "i.published_at < ?"]
            params += [lo, hi]
        chans = [normalize_channel(c).lower() for c in (channels or []) if normalize_channel(c)]
        if chans:
            where.append(f"lower(s.url) IN ({','.join('?' * len(chans))})")
            params += chans
        return self.db.query(f"""
            SELECT i.*, s.name AS source_name, s.url AS source_url, s.kind AS kind
            FROM items i JOIN sources s ON s.id = i.source_id
            WHERE {' AND '.join(where)} ORDER BY i.published_at DESC LIMIT ?
        """, params + [limit])

    def refresh_kind(self, kind: str) -> list[int]:
        """Собрать прямо сейчас (кнопка «Обновить»): задачи вперёд плановых."""
        return self.collector.enqueue_kind(kind, priority=5)

    def jobs_summary(self, ids: list[int]) -> dict:
        if not ids:
            return {"status": "none"}
        jobs = [self.queue.get(i) for i in ids]
        jobs = [j for j in jobs if j]
        active = [j for j in jobs if j["status"] in ("queued", "running")]
        finished = len(jobs) - len(active)
        added = sum((j.get("result") or {}).get("new", 0) for j in jobs
                    if j["status"] == "done" and isinstance(j.get("result"), dict))
        errors = [j["error"] for j in jobs if j["status"] == "failed" and j.get("error")]
        log = [ln for j in jobs for ln in (j.get("log") or "").splitlines() if ln]
        status = "running" if active else ("error" if errors and len(errors) == len(jobs) else "done")
        res = {"ok": status != "error", "added": added, "errors": errors}
        if status == "error":
            res["error"] = errors[0]
        return {"status": status, "progress": int(finished / max(len(jobs), 1) * 100),
                "log": log + [f"Готово. Новых публикаций: {added}."] * (status != "running"),
                "result": res}

    def import_news_db(self, path: Path) -> int:
        from ..services.legacy_import import LegacyImporter
        imp = LegacyImporter(self.db, self.sources, self.data_dir, self.settings, SOURCES)
        return imp.import_news_db(Path(path)).new

    # ─── служебное ───────────────────────────────────────────────────────────
    COLLECT_TYPES = ("collect_kind", "collect_source", "collect_telegram", "fulltext")

    def _job_morning(self, ctx, wait_seconds: float = 25 * 60, poll: float = 5.0) -> dict:
        """Утренняя выгрузка: собрать всё → дождаться (с полными текстами) → подготовить CSV → уведомить."""
        import json
        import time as _time
        from ..system import notify
        kinds = [k for k in ("rss", "telegram") if k in self.collector.connectors
                 and self.sources.list(kind=k, enabled=True)]
        for k in kinds:
            self.queue.enqueue("collect_kind", {"kind": k}, dedupe_key=f"morning:{k}", priority=8)
        ctx.log(f"Сбор: {', '.join({'rss': 'сайты', 'telegram': 'Telegram'}[k] for k in kinds) or 'нет источников'}")
        _time.sleep(min(poll, 2))
        end = _time.monotonic() + wait_seconds
        while _time.monotonic() < end:
            busy = self.db.scalar(
                f"SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') AND type IN "
                f"({','.join('?' * len(self.COLLECT_TYPES))})", self.COLLECT_TYPES)
            if not busy:
                break
            _time.sleep(poll)
        else:
            ctx.log("Сбор идёт дольше 25 минут — готовлю выгрузку из того, что уже есть")
        result: dict = {"at": self.db.scalar("SELECT strftime('%Y-%m-%dT%H:%M:%SZ','now')")}
        try:
            e = self.exports.prepare(mode="since_last", log=ctx.log)
            result.update(export_id=e["id"], rows=e["items_exported"], period_from=e["period_from"],
                          period_to=e["period_to"])
            title, text = "Утренняя выгрузка готова", (
                f"{e['items_exported']} строк для ChatGPT · период {e['period_from']}"
                + ("" if e["period_from"] == e["period_to"] else f" – {e['period_to']}")
                + ". Промпт и CSV — на экране «Выгрузка».")
        except ValueError as err:
            result["error"] = str(err)
            title, text = "Утренняя выгрузка", f"Не подготовлена: {err}."
        self.db.set_meta("morning_last", json.dumps(result, ensure_ascii=False))
        ctx.log(f"{title}: {text}")
        if (self.settings.get("morning") or {}).get("notify", True):
            notify(title, text)
        return result

    def morning_status(self) -> dict:
        import json
        sch = self.db.one("SELECT enabled, at_time, next_run_at, last_run_at FROM schedules WHERE name='morning_export'")
        last = self.db.get_meta("morning_last")
        return {"schedule": sch, "last": json.loads(last) if last else None}

    def _job_maintenance(self, ctx) -> dict:
        removed = self.queue.cleanup(keep_days=30)
        vectors = self.exports.vectors.prune(keep_days=60)
        self.db.execute("PRAGMA optimize")
        ctx.log(f"Удалено старых задач: {removed}, векторов старых новостей: {vectors}")
        return {"jobs_removed": removed, "vectors_removed": vectors}

    def status(self) -> dict:
        db = self.db
        return {
            "db": str(db.path),
            "schema_version": db.version(),
            "items": db.scalar("SELECT COUNT(*) FROM items", default=0),
            "items_by_kind": {r["kind"]: r["n"] for r in db.query(
                "SELECT s.kind, COUNT(*) AS n FROM items i JOIN sources s ON s.id = i.source_id "
                "GROUP BY s.kind")},
            "items_last_24h": db.scalar("SELECT COUNT(*) FROM items WHERE fetched_at >= "
                                        "strftime('%Y-%m-%dT%H:%M:%SZ','now','-1 day') "
                                        "AND origin = 'collect'", default=0),
            "sources": db.scalar("SELECT COUNT(*) FROM sources", default=0),
            "problem_sources": [{"name": r["name"], "error": r["last_error"]}
                                for r in self.sources.health() if r["problem"]],
            "jobs": {r["status"]: r["n"] for r in db.query(
                "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")},
            "schedules": self.scheduler.list(),
            "import30": db.get_meta("import30"),
        }
