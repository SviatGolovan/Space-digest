import json
import sqlite3

from spacedigest.services.ingest import ingest
from spacedigest.domain.models import RawItem
from spacedigest.services.legacy_import import LegacyImporter, import_if_needed
from spacedigest.settings import Settings

BUILTIN = [{"id": "spacenews", "name": "SpaceNews", "url": "https://spacenews.com/feed/",
            "category": "Ежедневные", "region": "США", "enabled": True}]


def make_legacy_dir(tmp_path):
    d = tmp_path / "data"
    (d / "jobs").mkdir(parents=True)
    (d / "tg").mkdir()
    (d / "weeks" / "2026-11-09").mkdir(parents=True)
    (d / "telegram").mkdir()
    site = {"source_name": "SpaceNews", "source_id": "spacenews", "title": "Launch",
            "summary": "Truncated text", "url": "https://spacenews.com/launch/",
            "published_at": "2026-11-10 09:00 UTC", "title_ru": "Запуск"}
    unknown = {"source_name": "Old Blog", "title": "Old", "summary": "s",
               "url": "https://old.blog/p1", "published_at": "2026-11-10 10:00 UTC"}
    tg_art = {"source_name": "@roscosmos_press", "title": "Пуск", "summary": "Пуск ракеты",
              "url": "https://t.me/roscosmos_press/7", "published_at": "2026-11-10 11:00"}
    empty_tg = {"source_name": "@roscosmos_press", "title": "(без текста)", "summary": "",
                "url": "https://t.me/roscosmos_press/8", "published_at": "2026-11-10 11:05"}
    (d / "jobs" / "a.json").write_text(json.dumps({"articles": [site, unknown]}), "utf-8")
    (d / "tg" / "b.json").write_text(json.dumps({"articles": [tg_art, empty_tg]}), "utf-8")
    (d / "weeks" / "2026-11-09" / "articles.json").write_text(
        json.dumps([dict(site, set_kind="parser"), dict(tg_art, set_kind="tg")]), "utf-8")
    c = sqlite3.connect(d / "telegram" / "news.db")
    c.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, channel TEXT, message_id INT, date TEXT, "
              "text TEXT, link TEXT)")
    c.executemany("INSERT INTO posts (channel, message_id, date, text, link) VALUES (?,?,?,?,?)", [
        ("roscosmos_press", 7, "2026-11-10 11:00:00.000000", "Пуск ракеты", "https://t.me/roscosmos_press/7"),
        ("roscosmos_press", 9, "2026-11-10 12:00:00.000000", "", ""),
        ("prokosmosru", 1, "2026-11-11 08:00:00.000000", "Новость канала", "https://t.me/prokosmosru/1"),
    ])
    c.commit(); c.close()
    s = Settings(d / "settings.json")
    s.update({"sources": {"custom": [{"id": "custom_1", "name": "Mine", "url": "https://mine.test/rss",
                                      "category": "Свои"}]},
              "telegram": {"channels": ["@newscienceru"]}})
    return d, s


def test_import_everything_once(tmp_path, db, repo):
    d, s = make_legacy_dir(tmp_path)
    report = import_if_needed(db, repo, d, s, BUILTIN)
    assert report["sources"] == {"builtin": 1, "custom": 1, "telegram": 3}
    q = lambda sql: db.scalar(sql)                                   # noqa: E731
    assert q("SELECT COUNT(*) FROM items") == 4          # 2 сайта + 2 непустых поста
    assert q("SELECT COUNT(*) FROM items WHERE title='(без текста)'") == 0
    assert q("SELECT published_at FROM items WHERE external_id='https://spacenews.com/launch/'") \
        == "2026-11-10T09:00:00Z"
    assert repo.by_key("legacy:rss:old-blog") is not None and not repo.by_key("legacy:rss:old-blog").enabled
    assert repo.by_key("custom_1").name == "Mine"
    assert repo.by_key("tg:newscienceru") is not None
    assert q("SELECT COUNT(*) FROM items WHERE origin='import30'") == 4
    # повторный запуск ничего не дублирует
    assert import_if_needed(db, repo, d, s, BUILTIN) is None
    assert q("SELECT COUNT(*) FROM items") == 4


def test_import_does_not_overwrite_fresh_full_text(tmp_path, db, repo):
    d, s = make_legacy_dir(tmp_path)
    repo.sync_builtin(BUILTIN)
    src = repo.by_key("spacenews")
    ingest(db, src, [RawItem("https://spacenews.com/launch/", title="Launch",
                             body="Full fresh text " * 100, url="https://spacenews.com/launch/")])
    LegacyImporter(db, repo, d, s, BUILTIN).run()
    body = db.scalar("SELECT body FROM items WHERE external_id='https://spacenews.com/launch/'")
    assert body.startswith("Full fresh text")
