from datetime import datetime, timedelta, timezone

from spacedigest.domain.models import RawItem
from spacedigest.services.fulltext import FullText, extract_text
from spacedigest.services.ingest import ingest

from test_export import settings  # noqa: F401  (фикстура settings)

ARTICLE = """<html><head><title>Rocket Lab</title></head><body>
<nav><a href="/">Home</a> | <a href="/news">News</a> | Subscribe to our newsletter</nav>
<article><h1>Rocket Lab launches 80th Electron</h1>
<p>Rocket Lab launched its 80th Electron rocket from Launch Complex 1 in New Zealand on Tuesday,
deploying a synthetic aperture radar satellite for iQPS into a 575-kilometer orbit.</p>
<p>The mission, named "The Harvest Goddess Thrives", lifted off at 10:12 UTC. It was the company's
18th launch of the year, a record pace for the small launch vehicle.</p>
<p>Rocket Lab said it has a backlog of more than 40 Electron missions and expects Neutron to fly in 2026.
The contract with iQPS covers ten more launches through 2027, the company added in a statement.</p>
</article><footer>Copyright 2026. All rights reserved. Cookie policy.</footer></body></html>"""


class Resp:
    def __init__(self, text, code=200, ctype="text/html; charset=utf-8"):
        self.text, self.status_code, self.headers = text, code, {"Content-Type": ctype}


def _item(db, src, ext, body, hours=1):
    ingest(db, src, [RawItem(ext, title=f"T {ext}", body=body, url=f"https://site.test/{ext}",
                             published_at=datetime.now(timezone.utc) - timedelta(hours=hours))])
    return db.scalar("SELECT id FROM items WHERE external_id = ?", (ext,))


def test_extract_text_drops_navigation_and_footer():
    text = extract_text(ARTICLE, "https://site.test/a")
    assert "80th Electron" in text and "ten more launches" in text
    assert "Cookie policy" not in text and "Subscribe to our newsletter" not in text


def test_short_items_get_full_text_and_feed_does_not_overwrite_it(db, repo, settings):  # noqa: F811
    src = repo.add_rss("Site", "https://site.test/rss")
    tg = repo.ensure_telegram("chan")
    iid = _item(db, src, "a", "Rocket Lab launched its 80th Electron.")
    long_id = _item(db, src, "b", "x " * 500)                        # уже полный текст
    _item(db, src, "old", "Short.", hours=24 * 10)                     # старше окна
    ingest(db, tg, [RawItem("1", title="tg", body="коротко", url="https://t.me/c/1",
                            published_at=datetime.now(timezone.utc))])
    calls = []
    ft = FullText(db, settings, http_get=lambda u: calls.append(u) or Resp(ARTICLE), sleep=lambda s: None)
    rows = ft.pending()
    assert [r["id"] for r in rows] == [iid]                            # только короткие, сайты, свежие
    assert ft.process(rows) == {"ok": 1, "same": 0, "failed": 0, "dated": 0}
    body = db.scalar("SELECT body FROM items WHERE id = ?", (iid,))
    assert "ten more launches" in body and calls == ["https://site.test/a"]
    assert ft.pending() == [] and long_id

    # следующий сбор той же ленты (анонс не менялся) не затирает полный текст
    ingest(db, src, [RawItem("a", title="T a", body="Rocket Lab launched its 80th Electron.",
                             url="https://site.test/a", published_at=datetime.now(timezone.utc) - timedelta(hours=1))])
    assert "ten more launches" in db.scalar("SELECT body FROM items WHERE id = ?", (iid,))
    # а если статья в ленте изменилась — будет взята заново
    ingest(db, src, [RawItem("a", title="T a (upd)", body="Обновлено.", url="https://site.test/a",
                             published_at=datetime.now(timezone.utc) - timedelta(hours=1))])
    assert [r["id"] for r in ft.pending()] == [iid]


def test_failures_and_pages_without_more_text_are_not_retried(db, repo, settings):  # noqa: F811
    src = repo.add_rss("Site", "https://site.test/rss")
    a = _item(db, src, "a", "Teaser one.")
    b = _item(db, src, "b", "Teaser two.")
    c = _item(db, src, "c", "Teaser three.")
    pages = {"https://site.test/a": Resp("", 404), "https://site.test/b": Resp("<html><p>Teaser two.</p></html>"),
             "https://site.test/c": Resp("%PDF", 200, "application/pdf")}

    def get(u):
        return pages[u]
    ft = FullText(db, settings, http_get=get, sleep=lambda s: None)
    assert ft.process(ft.pending()) == {"ok": 0, "same": 1, "failed": 2, "dated": 0}
    st = {r["id"]: r["fulltext_status"] for r in db.query("SELECT id, fulltext_status FROM items")}
    assert st == {a: "failed", b: "same", c: "failed"} and ft.pending() == []
    s = ft.stats()
    assert s["total"] == 3 and s["short"] == 3 and s["failed"] == 2 and s["pending"] == 0


def test_collect_enqueues_fulltext_for_new_rss_items(db, repo, queue, settings):  # noqa: F811
    from spacedigest.domain.models import FetchResult
    from spacedigest.services.collect import Collector

    class Conn:
        def fetch(self, source, state, log=None):
            return FetchResult(items=[RawItem("n1", title="New", body="Short teaser.", url="https://site.test/n1",
                                              published_at=datetime.now(timezone.utc))], state=state)
    src = repo.add_rss("Site", "https://site.test/rss")
    ft = FullText(db, settings, http_get=lambda u: Resp(ARTICLE), sleep=lambda s: None)
    col = Collector(repo, queue, {"rss": Conn()}, ft)
    jid = col.enqueue_source(src.id)
    from spacedigest.core.jobs import JobContext
    col.job_collect_source(JobContext(jid, "collect_source", {"source_id": src.id}, 1, queue))
    assert db.scalar("SELECT COUNT(*) FROM jobs WHERE type = 'fulltext' AND status = 'queued'") == 1
