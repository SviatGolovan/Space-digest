import time
from datetime import datetime, timedelta, timezone

import pytest

from conftest import FakeResponse, FakeSession, fixture_bytes
from spacedigest.connectors.base import ConnectorError
from spacedigest.connectors.rss import RssConnector
from spacedigest.connectors.telegram import TelegramConnector, title_from_text
from spacedigest.core.jobs import PermanentError
from spacedigest.core.scheduler import Scheduler
from spacedigest.domain.models import RawItem, SourceState
from spacedigest.services.collect import Collector

FEED = "https://example.com/feed/"


# ─── очередь ──────────────────────────────────────────────────────────────────

def test_enqueue_dedupe(queue):
    a = queue.enqueue("t", {"x": 1}, dedupe_key="k")
    b = queue.enqueue("t", {"x": 2}, dedupe_key="k")
    assert a == b
    assert queue.db.scalar("SELECT COUNT(*) FROM jobs") == 1


def test_claim_respects_concurrency(queue):
    queue.enqueue("tg", {}); queue.enqueue("tg", {})
    first = queue.claim("w1", {"tg": 1})
    assert first is not None
    assert queue.claim("w2", {"tg": 1}) is None          # лимит 1 — второй ждёт
    queue.complete(first["id"])
    assert queue.claim("w2", {"tg": 1}) is not None


def test_retry_with_backoff_then_failed(queue, pool):
    calls = []

    def boom(ctx):
        calls.append(ctx.attempt)
        raise RuntimeError("temporary")
    pool.register("x", boom)
    jid = queue.enqueue("x", {}, max_attempts=2)
    assert pool.run_one("w")
    job = queue.get(jid)
    assert job["status"] == "queued" and job["run_after"] > job["created_at"]
    queue.db.execute("UPDATE jobs SET run_after = created_at WHERE id=?", (jid,))
    assert pool.run_one("w")
    assert queue.get(jid)["status"] == "failed" and calls == [1, 2]


def test_permanent_error_not_retried(queue, pool):
    def bad(ctx):
        raise PermanentError("no")
    pool.register("p", bad)
    jid = queue.enqueue("p", {}, max_attempts=3)
    pool.run_one("w")
    assert queue.get(jid)["status"] == "failed"


def test_success_log_progress_and_stale_requeue(queue, pool):
    def ok(ctx):
        ctx.log("hello"); ctx.progress(50)
        return {"n": 1}
    pool.register("ok", ok)
    jid = queue.enqueue("ok", {})
    pool.run_one("w")
    job = queue.get(jid)
    assert job["status"] == "done" and job["result"] == {"n": 1} and "hello" in job["log"]
    j2 = queue.enqueue("ok", {})
    queue.claim("dead-worker", {"ok": 5})
    assert queue.requeue_stale() == 1 and queue.get(j2)["status"] == "queued"


def test_worker_threads_run_jobs(queue, pool):
    done = []
    pool.register("bg", lambda ctx: done.append(ctx.payload["i"]), concurrency=2)
    pool.poll = 0.05
    pool.start()
    for i in range(5):
        queue.enqueue("bg", {"i": i})
    deadline = time.time() + 5
    while len(done) < 5 and time.time() < deadline:
        time.sleep(0.05)
    pool.stop()
    assert sorted(done) == [0, 1, 2, 3, 4]


# ─── планировщик ──────────────────────────────────────────────────────────────

def test_scheduler_fires_due_once(db, queue):
    sch = Scheduler(db, queue)
    sch.ensure("s", "collect_kind", 60, payload={"kind": "rss"})
    # «компьютер спал 5 часов» — пропущенный запуск выполняется один раз
    db.execute("UPDATE schedules SET next_run_at='2020-01-01T00:00:00Z'")
    assert sch.tick() == 1
    assert sch.tick() == 0
    assert db.scalar("SELECT COUNT(*) FROM jobs WHERE type='collect_kind'") == 1
    sch.set_enabled("s", False)
    db.execute("UPDATE schedules SET next_run_at='2020-01-01T00:00:00Z'")
    assert sch.tick() == 0


def test_scheduler_interval_change_keeps_last_run(db, queue):
    sch = Scheduler(db, queue)
    sch.ensure("s", "x", 60)
    sch.run_now("s")
    sch.ensure("s", "x", 120)
    row = db.one("SELECT * FROM schedules WHERE name='s'")
    assert row["interval_minutes"] == 120 and row["last_run_at"]


# ─── сбор целиком ─────────────────────────────────────────────────────────────

def make_collector(repo, queue, pool, connectors):
    c = Collector(repo, queue, connectors)
    pool.register("collect_kind", c.job_collect_kind)
    pool.register("collect_source", c.job_collect_source, concurrency=4)
    pool.register("collect_telegram", c.job_collect_source)
    return c


def drain(pool, limit=50):
    n = 0
    while pool.run_one("w") and n < limit:
        n += 1
    return n


def test_collect_end_to_end_with_health(repo, queue, pool, db):
    sess = FakeSession({FEED: FakeResponse(FEED, fixture_bytes("rss_full.xml"))})
    make_collector(repo, queue, pool, {"rss": RssConnector(session=sess)})
    good = repo.add_rss("Good", FEED)
    bad = repo.add_rss("Bad", "https://bad.test/rss")
    repo.add_rss("Off", "https://off.test/rss", enabled=False)
    queue.enqueue("collect_kind", {"kind": "rss"})
    assert drain(pool) == 3                             # раздача + 2 включённых источника
    assert db.scalar("SELECT COUNT(*) FROM items WHERE source_id=?", (good.id,)) == 2
    health = {h["name"]: h for h in repo.health()}
    assert health["Good"]["last_ok_at"] and health["Good"]["last_new_items"] == 2
    assert health["Bad"]["consecutive_failures"] == 1 and "404" in health["Bad"]["last_error"]
    assert not health["Bad"]["problem"]
    for _ in range(4):
        repo.record_failure(bad.id, "x")
    assert {h["name"]: h for h in repo.health()}["Bad"]["problem"]


class FakeTg:
    def __init__(self):
        self.calls = []
        now = datetime.now(timezone.utc)
        self.messages = [{"id": 12, "date": now, "text": "Пуск «Союза»\nподробности"},
                         {"id": 11, "date": now - timedelta(hours=1), "text": ""},
                         {"id": 10, "date": now - timedelta(hours=2), "text": "Старт МКС-75"}]

    def fetch_channel(self, channel, min_id=0, min_date=None, limit=5000):
        self.calls.append(min_id)
        return {"username": channel, "title": "", "public": True,
                "messages": [m for m in self.messages if m["id"] > min_id]}


def test_telegram_incremental_cursor(repo, queue, pool, db):
    fake = FakeTg()
    make_collector(repo, queue, pool, {"telegram": TelegramConnector(fake, lambda: 7)})
    src = repo.ensure_telegram("https://t.me/roscosmos_press")
    assert src.key == "tg:roscosmos_press" and src.name == "@roscosmos_press"
    queue.enqueue("collect_kind", {"kind": "telegram"})
    drain(pool)
    rows = db.query("SELECT title, body, url FROM items ORDER BY external_id")
    assert [r["title"] for r in rows] == ["Старт МКС-75", "Пуск «Союза»"]     # пустой пост пропущен
    assert rows[1]["url"] == "https://t.me/roscosmos_press/12"
    assert repo.state(src.id).cursor == "12"
    fake.messages.insert(0, {"id": 13, "date": datetime.now(timezone.utc), "text": "Новый пост"})
    queue.enqueue("collect_kind", {"kind": "telegram"})
    drain(pool)
    assert fake.calls == [0, 12]                        # второй раз — только новее 12
    assert db.scalar("SELECT COUNT(*) FROM items") == 3


def test_telegram_failure_keeps_cursor(repo, queue, pool):
    class Broken:
        def fetch(self, source, state, log=None):
            raise ConnectorError("Нет связи с серверами Telegram")
    make_collector(repo, queue, pool, {"telegram": Broken()})
    src = repo.ensure_telegram("chan")
    repo.record_success(src.id, SourceState(cursor="50"), 0)
    queue.enqueue("collect_kind", {"kind": "telegram"})
    drain(pool)
    assert repo.state(src.id).cursor == "50"
    assert "Нет связи" in repo.health()[0]["last_error"]


def test_title_from_text():
    assert title_from_text("\n\n  Заголовок  \nтекст") == "Заголовок"
    assert len(title_from_text("x" * 300)) == 118


def test_sources_repo_rules(repo, db):
    with pytest.raises(ValueError):
        repo.add_rss("No scheme", "example.com/rss")
    s = repo.add_rss("A", "https://a.test/rss")
    with pytest.raises(ValueError, match="уже есть"):
        repo.add_rss("A2", "https://a.test/rss")
    repo.sync_builtin([{"id": "b1", "name": "B", "url": "https://b.test/rss", "enabled": False}])
    b = repo.by_key("b1")
    assert b.builtin and not b.enabled
    with pytest.raises(ValueError, match="встроенный"):
        repo.delete(b.id)
    # источник с собранными новостями при удалении только выключается
    from spacedigest.services.ingest import ingest
    ingest(db, s, [RawItem("1", title="t")])
    repo.delete(s.id)
    assert repo.get(s.id) is not None and not repo.get(s.id).enabled
    repo.delete(s.id, with_items=True)
    assert repo.get(s.id) is None and db.scalar("SELECT COUNT(*) FROM items") == 0
