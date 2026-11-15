import time

import numpy as np
import pytest

from spacedigest.services.export import ExportService
from spacedigest.services.stories import merge_text, novel_sentences
from spacedigest.services.vectors import VectorCache

from test_export import add, fake_dedup, read_csv, settings  # noqa: F401  (фикстура settings)


MAIN = ("Космические силы США заключили с Northrop Grumman контракт на создание спутника связи. "
        "Запуск планируется не ранее 2030 года.")
OTHER = ("Космические силы США заключили контракт с компанией Northrop Grumman на создание спутника. "
         "Сумма контракта составляет 400 млн долларов. Аппарат построен на платформе ESPAStar-HP. "
         "Подписывайтесь на наш канал @spacenews")


def test_novel_sentences_keep_only_new_facts():
    new = novel_sentences([MAIN], OTHER)
    assert new == ["Сумма контракта составляет 400 млн долларов.",
                   "Аппарат построен на платформе ESPAStar-HP."]
    assert novel_sentences([MAIN], MAIN) == []


def test_merge_text_appends_sources_and_reports_added():
    text, added = merge_text(MAIN, [("SpaceNews", OTHER), ("@chan", MAIN)])
    assert text.startswith(MAIN)
    assert "[Дополнительно: SpaceNews]\nСумма контракта" in text and "@chan" not in text
    assert added[0] > 0 and added[1] == 0
    # повтор уже добавленного не дублируется
    text2, added2 = merge_text(MAIN, [("A", OTHER), ("B", OTHER)])
    assert text2.count("400 млн") == 1 and added2[1] == 0


@pytest.fixture
def svc(db, settings, tmp_path):  # noqa: F811
    return ExportService(db, settings, deduper=fake_dedup, downloads_dir=tmp_path / "Downloads",
                         export_root=tmp_path / "out")


def test_story_row_merges_versions_and_review_edits(db, repo, svc):
    site, tg = repo.add_rss("SpaceNews", "https://s.test/rss"), repo.ensure_telegram("chan")
    add(db, site, "a", "Contract signed", body=MAIN)
    add(db, tg, "1", "contract signed", body=OTHER)
    add(db, site, "b", "Other news", body="Совсем другая новость про запуск ракеты с Байконура.")
    e = svc.prepare()
    rows = read_csv(e["csv_file"])
    assert len(rows) == 3 and e["items_exported"] == 2
    story = next(r for r in rows[1:] if r[4] == "Contract signed")
    assert "[Дополнительно: @chan]" in story[5] and "ESPAStar-HP" in story[5]
    assert story[7] == "@chan: https://ex.test/1"

    rv = svc.review(e["id"])
    assert rv["counts"] == {"rows": 2, "multi": 1, "merged": 1, "known": 0, "excluded": 0, "filtered": 0}
    s = next(x for x in rv["stories"] if x["others"])
    tg_id = s["others"][0]["id"]
    assert s["others"][0]["added"] > 0

    rv = svc.change(e["id"], tg_id, "separate")          # ошибочно сведено → своя строка
    assert rv["counts"]["rows"] == 3 and rv["counts"]["merged"] == 0
    rows = read_csv(e["csv_file"])
    assert len(rows) == 4 and all(r[7] == "" for r in rows[1:])
    assert [r[0] for r in rows[1:]] == ["1", "2", "3"]

    other_id = next(x["id"] for x in rv["stories"] if x["title"] == "Other news")
    rv = svc.change(e["id"], other_id, "exclude")
    assert rv["counts"]["excluded"] == 1 and len(read_csv(e["csv_file"])) == 3
    assert svc.get(e["id"])["items_exported"] == 2
    with pytest.raises(ValueError, match="изменилось"):
        svc.change(e["id"], other_id, "exclude")
    svc.change(e["id"], other_id, "include")
    assert len(read_csv(e["csv_file"])) == 4


def test_known_items_listed_and_can_be_restored(db, repo, svc):
    site, tg = repo.add_rss("Site", "https://s.test/rss"), repo.ensure_telegram("chan")
    add(db, site, "a", "Starship flight")
    first = svc.prepare()
    time.sleep(1.1)
    add(db, tg, "1", "starship flight")                   # то же событие — уже было
    add(db, site, "b", "New event")
    e = svc.prepare()
    rv = svc.review(e["id"])
    assert rv["counts"]["known"] == 1 and rv["counts"]["rows"] == 1
    k = rv["known"][0]
    assert k["match"]["title"] == "Starship flight" and k["match"]["exported"]
    svc.change(e["id"], k["id"], "restore")               # всё-таки нужна (новые подробности)
    assert {r[4] for r in read_csv(e["csv_file"])[1:]} == {"New event", "starship flight"}
    assert first["id"] != e["id"]


def test_excluded_items_are_not_reference_for_next_exports(db, repo, svc):
    site = repo.add_rss("Site", "https://s.test/rss")
    add(db, site, "a", "Junk post")
    add(db, site, "b", "Real news")
    e = svc.prepare()
    junk = next(x["id"] for x in svc.review(e["id"])["stories"] if x["title"] == "Junk post")
    svc.change(e["id"], junk, "exclude")
    titles = {r["title"] for r in svc.reference_rows(7, set())}
    assert titles == {"Real news"}


def test_vector_cache_encodes_each_text_once(db, repo):
    site = repo.add_rss("Site", "https://s.test/rss")
    add(db, site, "a", "One"); add(db, site, "b", "Two")
    ids = [r["id"] for r in db.query("SELECT id FROM items ORDER BY id")]
    calls = []

    def neural(texts, log):
        calls.append(list(texts))
        v = np.array([[len(t), 1.0, 0.0] for t in texts], dtype=np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    vc = VectorCache(db, neural=neural)
    arts = [{"_item_id": i} for i in ids]
    a = vc.neural_vectors(arts, ["one", "two!"])
    b = vc.neural_vectors(arts, ["one", "two!"])
    assert np.allclose(a, b) and calls == [["one", "two!"]]
    vc.neural_vectors(arts, ["one", "changed text"])       # текст изменился → пересчёт
    assert calls[-1] == ["changed text"]
    enc = VectorCache(db, neural=lambda t, l: (_ for _ in ()).throw(RuntimeError("нет модели")),
                      tfidf=lambda t, l: "TFIDF").encoder("auto")
    assert enc(arts, ["x", "y"], None) == ("TFIDF", "tfidf")


def test_migration_003_backfills_states(tmp_path):
    from spacedigest.core.db import Database
    d = Database(tmp_path / "m.db")
    c = d.conn()
    for n, path in d.available_migrations():
        if n > 2:
            break
        c.executescript(f"BEGIN;\n{path.read_text(encoding='utf-8')}\nPRAGMA user_version = {n};\nCOMMIT;")
    c.executescript("""
        INSERT INTO sources (id, key, kind, name, created_at) VALUES (1, 'k', 'rss', 'S', 'x');
        INSERT INTO items (id, source_id, external_id, title, fetched_at, origin, content_hash)
            VALUES (1,1,'a','A','2026-01-01T00:00:00Z','collect','h1'),
                   (2,1,'b','B','2026-01-01T00:00:00Z','collect','h2'),
                   (3,1,'c','C','2026-01-01T00:00:00Z','collect','h3');
        INSERT INTO exports (id, created_at, mode, fetched_until, folder) VALUES (1,'x','dates','x','f');
        INSERT INTO export_items (export_id, item_id, row_no, duplicate_of) VALUES (1,1,1,NULL),(1,2,NULL,1),(1,3,NULL,99);
    """)
    assert d.migrate() >= 3
    states = {r["item_id"]: r["state"] for r in d.query("SELECT item_id, state FROM export_items")}
    assert states == {1: "main", 2: "merged", 3: "known"}
