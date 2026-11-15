import json
from datetime import datetime, timedelta, timezone

import pytest

from spacedigest.core import scheduler as S
from spacedigest.core.scheduler import Scheduler, daily_slot, parse_hhmm
from spacedigest.core.timeutil import to_iso

UTC = timezone.utc


def test_daily_slot_is_moscow_time():
    now = datetime(2026, 11, 15, 5, 0, tzinfo=UTC)                 # 08:00 МСК
    assert daily_slot("09:00", now) == datetime(2026, 11, 15, 6, 0, tzinfo=UTC)
    assert daily_slot("07:30", now) == datetime(2026, 11, 16, 4, 30, tzinfo=UTC)   # уже прошло → завтра
    assert daily_slot("07:30", now, after=False) == datetime(2026, 11, 15, 4, 30, tzinfo=UTC)
    with pytest.raises(ValueError):
        parse_hhmm("25:00")


def _set_now(monkeypatch, dt):
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return dt if tz else dt.replace(tzinfo=None)
    monkeypatch.setattr(S, "datetime", FakeDT)
    monkeypatch.setattr(S, "now_iso", lambda: to_iso(dt))


def test_daily_schedule_fires_once_and_skips_stale_morning(db, queue, monkeypatch):
    sch = Scheduler(db, queue)
    _set_now(monkeypatch, datetime(2026, 11, 15, 5, 0, tzinfo=UTC))           # 08:00 МСК
    sch.ensure_daily("morning_export", "morning_export", "09:00")
    assert sch.tick() == 0
    _set_now(monkeypatch, datetime(2026, 11, 15, 6, 1, tzinfo=UTC))           # 09:01
    assert sch.tick() == 1 and sch.tick() == 0
    row = db.one("SELECT next_run_at FROM schedules WHERE name='morning_export'")
    assert row["next_run_at"] == "2026-11-16T06:00:00Z"

    # компьютер был выключен двое суток, включили в 07:00 — вчерашнюю не делаем, ждём 09:00
    _set_now(monkeypatch, datetime(2026, 11, 18, 4, 0, tzinfo=UTC))
    assert sch.tick() == 0
    assert db.scalar("SELECT next_run_at FROM schedules WHERE name='morning_export'") == "2026-11-18T06:00:00Z"
    # включили в 12:00 — сегодняшнее утро пропущено, делаем сразу
    db.execute("UPDATE schedules SET next_run_at='2026-11-18T06:00:00Z'")
    _set_now(monkeypatch, datetime(2026, 11, 18, 9, 0, tzinfo=UTC))
    assert sch.tick() == 1


def test_changing_time_moves_next_run(db, queue, monkeypatch):
    sch = Scheduler(db, queue)
    _set_now(monkeypatch, datetime(2026, 11, 15, 5, 0, tzinfo=UTC))
    sch.ensure_daily("m", "morning_export", "09:00")
    sch.ensure_daily("m", "morning_export", "08:15")
    assert db.scalar("SELECT next_run_at FROM schedules WHERE name='m'") == "2026-11-15T05:15:00Z"
    sch.ensure_daily("m", "morning_export", "08:15", enabled=False)
    assert db.scalar("SELECT enabled FROM schedules WHERE name='m'") == 0


def test_morning_job_collects_waits_prepares_and_notifies(tmp_path, monkeypatch):
    from spacedigest.core.runtime import Core
    from spacedigest.settings import Settings
    from test_export import add
    st = Settings(tmp_path / "settings.json")
    st.update({"export": {"folder": str(tmp_path / "out")}, "morning": {"enabled": True, "time": "09:00"}})
    core = Core(tmp_path, st, None)
    core.db.migrate()
    src = core.sources.add_rss("Site", "https://s.test/rss")
    add(core.db, src, "a", "Starship flight")
    sent = []
    monkeypatch.setattr("spacedigest.system.notify", lambda t, x: sent.append((t, x)) or True)
    core.apply_schedules()
    assert core.db.scalar("SELECT at_time FROM schedules WHERE name='morning_export'") == "09:00"

    class Ctx:
        logs = []
        def log(self, s): self.logs.append(s)
    res = core._job_morning(Ctx(), wait_seconds=0.1, poll=0.01)
    assert res["rows"] == 1 and "error" not in res
    assert sent and sent[0][0] == "Утренняя выгрузка готова"
    assert core.db.scalar("SELECT COUNT(*) FROM jobs WHERE type='collect_kind'") == 1
    last = core.morning_status()["last"]
    assert last["export_id"] == res["export_id"]
    res2 = core._job_morning(Ctx(), wait_seconds=0.1, poll=0.01)        # новых нет
    assert "нет новых" in res2["error"] and json.loads(core.db.get_meta("morning_last"))["error"]
    core.db.close()
