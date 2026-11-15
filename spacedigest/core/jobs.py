"""
Очередь фоновых задач в той же базе SQLite.

* enqueue() с dedupe_key не создаёт вторую такую же задачу, пока первая в очереди/в работе.
* Исполнители (потоки) берут задачу атомарно; у каждого типа задач свой лимит
  одновременных запусков (например, Telegram — строго по одной).
* Ошибка → повтор с нарастающей паузой (1 → 5 → 30 мин), затем статус failed.
* Задачи, «зависшие» в running после аварийного закрытия, при старте возвращаются в очередь.
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .db import Database
from .timeutil import iso_after, now_iso

log = logging.getLogger(__name__)

BACKOFF_SECONDS = (60, 300, 1800)
MAX_LOG_CHARS = 20_000


class JobQueue:
    def __init__(self, db: Database):
        self.db = db
        self.wakeup = threading.Event()

    def enqueue(self, type: str, payload: Optional[dict] = None, *, dedupe_key: Optional[str] = None,
                priority: int = 0, delay_seconds: float = 0, max_attempts: int = 3) -> int:
        """Поставить задачу. Если такая (по dedupe_key) уже ждёт или идёт — вернуть её id."""
        with self.db.tx():
            if dedupe_key:
                row = self.db.one("SELECT id FROM jobs WHERE dedupe_key = ? AND status IN "
                                  "('queued','running')", (dedupe_key,))
                if row:
                    return int(row["id"])
            cur = self.db.execute(
                "INSERT INTO jobs (type, payload, dedupe_key, priority, max_attempts, run_after, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (type, json.dumps(payload or {}, ensure_ascii=False), dedupe_key, priority,
                 max_attempts, iso_after(seconds=delay_seconds), now_iso()))
        self.wakeup.set()
        return int(cur.lastrowid)

    def claim(self, worker: str, limits: dict[str, int]) -> Optional[dict]:
        """Взять следующую задачу из разрешённых типов с учётом лимитов параллельности."""
        with self.db.tx():
            running = {r["type"]: r["n"] for r in self.db.query(
                "SELECT type, COUNT(*) AS n FROM jobs WHERE status='running' GROUP BY type")}
            allowed = [t for t, lim in limits.items() if running.get(t, 0) < lim]
            if not allowed:
                return None
            marks = ",".join("?" * len(allowed))
            row = self.db.one(
                f"SELECT * FROM jobs WHERE status='queued' AND run_after <= ? AND type IN ({marks}) "
                f"ORDER BY priority DESC, id LIMIT 1", [now_iso(), *allowed])
            if not row:
                return None
            self.db.execute("UPDATE jobs SET status='running', started_at=?, worker=?, "
                            "attempts = attempts + 1 WHERE id=?", (now_iso(), worker, row["id"]))
            row["attempts"] += 1
            return row

    def complete(self, job_id: int, result: Any = None) -> None:
        self.db.execute("UPDATE jobs SET status='done', finished_at=?, progress=100, result=?, "
                        "error=NULL WHERE id=?",
                        (now_iso(), json.dumps(result, ensure_ascii=False, default=str), job_id))

    def fail(self, job_id: int, error: str, retry: bool = True) -> str:
        row = self.db.one("SELECT attempts, max_attempts FROM jobs WHERE id=?", (job_id,))
        if row and retry and row["attempts"] < row["max_attempts"]:
            pause = BACKOFF_SECONDS[min(row["attempts"] - 1, len(BACKOFF_SECONDS) - 1)]
            self.db.execute("UPDATE jobs SET status='queued', run_after=?, error=?, worker=NULL "
                            "WHERE id=?", (iso_after(seconds=pause), error[:2000], job_id))
            return "queued"
        self.db.execute("UPDATE jobs SET status='failed', finished_at=?, error=? WHERE id=?",
                        (now_iso(), error[:2000], job_id))
        return "failed"

    def cancel(self, job_id: int) -> bool:
        cur = self.db.execute("UPDATE jobs SET status='cancelled', finished_at=? "
                              "WHERE id=? AND status='queued'", (now_iso(), job_id))
        return cur.rowcount > 0

    def append_log(self, job_id: int, line: str) -> None:
        self.db.execute("UPDATE jobs SET log = substr(log || ? || char(10), -?) WHERE id=?",
                        (line, MAX_LOG_CHARS, job_id))

    def set_progress(self, job_id: int, pct: int) -> None:
        self.db.execute("UPDATE jobs SET progress=? WHERE id=?", (max(0, min(100, int(pct))), job_id))

    def get(self, job_id: int) -> Optional[dict]:
        row = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if row:
            for k in ("payload", "result"):
                if row.get(k):
                    try:
                        row[k] = json.loads(row[k])
                    except ValueError:
                        pass
        return row

    def requeue_stale(self) -> int:
        """После аварийного закрытия: running → queued (попытка не засчитывается)."""
        cur = self.db.execute("UPDATE jobs SET status='queued', worker=NULL, "
                              "attempts = MAX(attempts - 1, 0) WHERE status='running'")
        return cur.rowcount

    def cleanup(self, keep_days: int = 30) -> int:
        cur = self.db.execute("DELETE FROM jobs WHERE status IN ('done','failed','cancelled') "
                              "AND finished_at < ?", (iso_after(minutes=-keep_days * 1440),))
        return cur.rowcount


@dataclass
class JobContext:
    """То, что получает обработчик задачи."""
    id: int
    type: str
    payload: dict
    attempt: int
    queue: JobQueue

    def log(self, line: str) -> None:
        self.queue.append_log(self.id, line)

    def progress(self, pct: int) -> None:
        self.queue.set_progress(self.id, pct)


class PermanentError(Exception):
    """Ошибка, которую бессмысленно повторять (неверные данные задачи и т. п.)."""


@dataclass
class Handler:
    fn: Callable[[JobContext], Any]
    concurrency: int = 1


class WorkerPool:
    def __init__(self, queue: JobQueue, threads: int = 4, poll_seconds: float = 2.0):
        self.queue = queue
        self.handlers: dict[str, Handler] = {}
        self.threads_n = threads
        self.poll = poll_seconds
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.name = f"{socket.gethostname()}-{id(self) & 0xffff:x}"

    def register(self, type: str, fn: Callable[[JobContext], Any], concurrency: int = 1) -> None:
        self.handlers[type] = Handler(fn, concurrency)

    def run_one(self, worker: str) -> bool:
        """Взять и выполнить одну задачу. True — если что-то выполнили (удобно в тестах)."""
        limits = {t: h.concurrency for t, h in self.handlers.items()}
        job = self.queue.claim(worker, limits)
        if not job:
            return False
        handler = self.handlers[job["type"]]
        try:
            payload = json.loads(job["payload"] or "{}")
        except ValueError:
            payload = {}
        ctx = JobContext(job["id"], job["type"], payload, job["attempts"], self.queue)
        try:
            result = handler.fn(ctx)
            self.queue.complete(job["id"], result)
        except PermanentError as e:
            self.queue.fail(job["id"], str(e), retry=False)
        except Exception as e:                                   # noqa: BLE001
            log.warning("Задача %s #%s: %s", job["type"], job["id"], e)
            status = self.queue.fail(job["id"], f"{type(e).__name__}: {e}")
            if status == "failed":
                log.debug(traceback.format_exc())
        return True

    def _loop(self, n: int) -> None:
        worker = f"{self.name}/{n}"
        while not self._stop.is_set():
            try:
                did = self.run_one(worker)
            except Exception:                                    # noqa: BLE001 — сбой базы и т. п.
                log.exception("Сбой исполнителя задач")
                did = False
            if not did:
                self.queue.wakeup.wait(self.poll)
                self.queue.wakeup.clear()

    def start(self) -> None:
        self.queue.requeue_stale()
        self._stop.clear()
        for n in range(self.threads_n):
            t = threading.Thread(target=self._loop, args=(n,), name=f"worker-{n}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 5) -> None:
        self._stop.set()
        self.queue.wakeup.set()
        for t in self._threads:
            t.join(timeout)
        self._threads.clear()
