import pytest

from conftest import FakeResponse, FakeSession, fixture_bytes
from spacedigest.connectors.base import ConnectorError
from spacedigest.connectors.rss import RssConnector
from spacedigest.domain.models import RawItem, SourceState
from spacedigest.services.ingest import ingest

FEED = "https://example.com/feed/"


def rss_source(repo, url=FEED):
    return repo.add_rss("Test", url)


def test_rss_keeps_full_text_guid_and_dates(repo):
    sess = FakeSession({FEED: FakeResponse(FEED, fixture_bytes("rss_full.xml"),
                                           headers={"ETag": '"v1"', "Content-Type": "application/rss+xml"})})
    res = RssConnector(session=sess).fetch(rss_source(repo), SourceState())
    assert len(res.items) == 2
    first = res.items[0]
    assert first.external_id == "https://example.com/?p=101"
    assert first.author == "Jane Doe"
    assert first.published_at.isoformat() == "2026-11-13T07:00:00+00:00"
    assert "Second paragraph" in first.body and len(first.body) > 500
    assert res.state.etag == '"v1"'


def test_ingest_normalizes_and_is_idempotent(repo, db):
    src = rss_source(repo)
    sess = FakeSession({FEED: FakeResponse(FEED, fixture_bytes("rss_full.xml"))})
    res = RssConnector(session=sess).fetch(src, SourceState())
    s1 = ingest(db, src, res.items)
    assert (s1.new, s1.updated) == (2, 0)
    row = db.one("SELECT * FROM items WHERE external_id = ?", ("https://example.com/?p=101",))
    assert row["title"] == "NASA’s Artemis & SpaceX update"
    assert row["summary"] == "Short teaser about Artemis…"
    assert "alert" not in row["body"] and "appeared first" not in row["body"]
    assert len(row["body"]) > 500                       # без обрезки до 500 символов
    assert row["url_canonical"] == "https://example.com/artemis-update"
    assert row["published_at"] == "2026-11-13T07:00:00Z"
    s2 = ingest(db, src, res.items)
    assert (s2.new, s2.updated, s2.unchanged) == (0, 0, 2)
    # поиск по полному тексту
    assert db.scalar("SELECT COUNT(*) FROM items_fts WHERE items_fts MATCH 'reprehenderit'") == 1


def test_ingest_updates_changed_text_but_import_does_not(repo, db):
    src = rss_source(repo)
    ingest(db, src, [RawItem("g1", title="T", body="full text v1")])
    s = ingest(db, src, [RawItem("g1", title="T", body="full text v2")])
    assert s.updated == 1
    s = ingest(db, src, [RawItem("g1", title="T", summary="old truncated")], update_existing=False)
    assert s.unchanged == 1
    assert db.scalar("SELECT body FROM items WHERE external_id='g1'") == "full text v2"


def test_ingest_matches_changed_guid_by_url(repo, db):
    src = rss_source(repo)
    ingest(db, src, [RawItem("old-guid", title="T", url="https://www.example.com/x/?utm_source=a")])
    s = ingest(db, src, [RawItem("new-guid", title="T", url="https://example.com/x")])
    assert s.new == 0 and db.scalar("SELECT COUNT(*) FROM items") == 1


def test_ingest_skips_empty(repo, db):
    s = ingest(db, rss_source(repo), [RawItem("e1"), RawItem("", title="x")])
    assert s.skipped == 2


def test_conditional_get_304(repo):
    def route(headers):
        if headers.get("If-None-Match") == '"v1"':
            return FakeResponse(FEED, b"", 304)
        return FakeResponse(FEED, fixture_bytes("rss_full.xml"), headers={"ETag": '"v1"'})
    sess = FakeSession({FEED: route})
    c = RssConnector(session=sess)
    src = rss_source(repo)
    first = c.fetch(src, SourceState())
    second = c.fetch(src, first.state)
    assert second.not_modified and second.items == []
    assert sess.calls[-1][1].get("If-None-Match") == '"v1"'


def test_atom_picks_alternate_link_and_content(repo):
    url = "https://example.org/atom.xml"
    sess = FakeSession({url: FakeResponse(url, fixture_bytes("atom.xml"))})
    res = RssConnector(session=sess).fetch(repo.add_rss("Atom", url), SourceState())
    it = res.items[0]
    assert it.url == "https://example.org/atom-entry"
    assert it.external_id == "tag:example.org,2026:1"
    assert "Atom full content" in it.body and it.summary == "Atom summary"


def test_html_page_discovers_and_remembers_feed(repo):
    page = "https://site.test/"
    sess = FakeSession({page: FakeResponse(page, fixture_bytes("page.html")),
                        "https://site.test/feed/": FakeResponse("https://site.test/feed/",
                                                                fixture_bytes("rss_full.xml"))})
    res = RssConnector(session=sess).fetch(repo.add_rss("Site", page), SourceState())
    assert res.state.resolved_url == "https://site.test/feed/"
    assert len(res.items) == 2 and "найдена лента" in res.note


def test_errors_are_readable(repo):
    url = "https://bad.test/feed"
    sess = FakeSession({url: FakeResponse(url, b"<html><body>no feed</body></html>")})
    with pytest.raises(ConnectorError, match="RSS/Atom"):
        RssConnector(session=sess).fetch(repo.add_rss("Bad", url), SourceState())
    with pytest.raises(ConnectorError, match="HTTP 404"):
        RssConnector(session=FakeSession({})).fetch(repo.add_rss("Missing", "https://nope.test/rss"),
                                                    SourceState())
