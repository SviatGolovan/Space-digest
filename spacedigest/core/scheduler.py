"""
Планировщик: раз в несколько секунд ставит в очередь задачи, которым пора.

Если компьютер спал или программа была закрыта, пропущенный запуск выполняется
один раз, а не столько раз, сколько было пропущено.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import Database
from .jobs import JobQueue
from .timeutil import from_iso, iso_after, now_iso, to_iso

log = logging.getLogger(__name__)

# Москва живёт по UTC+3 без перехода на летнее время (с 2014 года), поэтому фиксированное
# смещение надёжнее базы часовых поясов: на Windows её у Python может не быть.
MSK = timezone(timedelta(hours=3), "MSK")


def parse_hhmm(value: str) -> tuple[int, int]:
    h, m = (int(x) for x in str(value).strip().split(":"))
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError("время в формате ЧЧ:ММ")
    return h, m


def daily_slot(at: str, now: Optional[datetime] = None, *, after: bool = True) -> datetime:
    """Ближайшее (after=True) или сегодняшнее (after=False) время ЧЧ:ММ по Москве, в UTC."""
    h, m = parse_hhmm(at)
    now = (now or datetime.now(timezone.utc)).astimezone(MSK)
    slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if after and slot <= now:
        slot += timedelta(days=1)
    return slot.astimezone(timezone.utc)


class Scheduler:
    def __init__(self, db: Database, queue: JobQueue, tick_seconds: float = 15):
        self.db = db
        self.queue = queue
        self.tick_seconds = tick_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def ensure(self, name: str, job_type: str, interval_minutes: int, *, enabled: bool = True,
               payload: Optional[dict] = None, first_run_delay_minutes: float = 0) -> None:
        """Создать или обновить расписание. Время последнего запуска сохраняется."""
        interval_minutes = max(1, int(interval_minutes))
        with self.db.tx():
            row = self.db.one("SELECT last_run_at, interval_minutes FROM schedules WHERE name=?", (name,))
            if row is None:
                self.db.execute(
                    "INSERT INTO schedules (name, job_type, payload, interval_minutes, enabled, next_run_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (name, job_type, json.dumps(payload or {}, ensure_ascii=False), interval_minutes,
                     int(enabled), iso_after(minutes=first_run_delay_minutes)))
            else:
                next_run = None
                if row["interval_minutes"] != interval_minutes and row["last_run_at"]:
                    # новый интервал отсчитывается от последнего запуска
                    next_run = to_iso(from_iso(row["last_run_at"]) + timedelta(minutes=interval_minutes))
                self.db.execute(
                    "UPDATE schedules SET job_type=?, payload=?, interval_minutes=?, enabled=?, "
                    "next_run_at = COALESCE(?, next_run_at) WHERE name=?",
                    (job_type, json.dumps(payload or {}, ensure_ascii=False), interval_minutes,
                     int(enabled), next_run, name))

    def ensure_daily(self, name: str, job_type: str, at: str, *, enabled: bool = True,
                     payload: Optional[dict] = None) -> None:
        """Каждый день в ЧЧ:ММ по Москве. Смена времени сразу переносит ближайший запуск."""
        parse_hhmm(at)
        nxt = to_iso(daily_slot(at))
        with self.db.tx():
            row = self.db.one("SELECT at_time, enabled FROM schedules WHERE name=?", (name,))
            if row is None:
                self.db.execute(
                    "INSERT INTO schedules (name, job_type, payload, interval_minutes, enabled, next_run_at, at_time) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (name, job_type, json.dumps(payload or {}, ensure_ascii=False), 24 * 60, int(enabled), nxt, at))
            else:
                reset = row["at_time"] != at or (enabled and not row["enabled"])
                self.db.execute(
                    "UPDATE schedules SET job_type=?, payload=?, enabled=?, at_time=?, "
                    "next_run_at = CASE WHEN ? THEN ? ELSE next_run_at END WHERE name=?",
                    (job_type, json.dumps(payload or {}, ensure_ascii=False), int(enabled), at,
                     int(reset), nxt, name))

    def set_enabled(self, name: str, enabled: bool) -> None:
        self.db.execute("UPDATE schedules SET enabled=? WHERE name=?", (int(enabled), name))

    def run_now(self, name: str) -> Optional[int]:
        row = self.db.one("SELECT * FROM schedules WHERE name=?", (name,))
        if not row:
            return None
        return self._fire(row)

    def _fire(self, row: dict) -> int:
        job_id = self.queue.enqueue(row["job_type"], json.loads(row["payload"] or "{}"),
                                    dedupe_key=f"schedule:{row['name']}")
        nxt = to_iso(daily_slot(row["at_time"])) if row.get("at_time") else iso_after(minutes=row["interval_minutes"])
        self.db.execute("UPDATE schedules SET last_run_at=?, next_run_at=? WHERE name=?",
                        (now_iso(), nxt, row["name"]))
        return job_id

    def tick(self) -> int:
        """Поставить в очередь всё, чему пора. Возвращает число запусков."""
        due = self.db.query("SELECT * FROM schedules WHERE enabled=1 AND "
                            "(next_run_at IS NULL OR next_run_at <= ?)", (now_iso(),))
        fired = 0
        for row in due:
            try:
                if row.get("at_time") and row["next_run_at"]:
                    # Пропустили вчерашнее утро, а сегодняшнее ещё впереди — ждём сегодняшнего,
                    # не делаем две выгрузки подряд.
                    today = daily_slot(row["at_time"], after=False)
                    if from_iso(row["next_run_at"]) < today and datetime.now(timezone.utc) < today:
                        self.db.execute("UPDATE schedules SET next_run_at=? WHERE name=?", (to_iso(today), row["name"]))
                        continue
                self._fire(row)
                fired += 1
            except Exception:                                     # noqa: BLE001
                log.exception("Не удалось запустить расписание %s", row["name"])
        return fired

    def list(self) -> list[dict]:
        return self.db.query("SELECT * FROM schedules ORDER BY name")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:                                     # noqa: BLE001
                log.exception("Сбой планировщика")
            self._stop.wait(self.tick_seconds)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(5)
