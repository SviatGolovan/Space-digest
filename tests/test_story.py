"""Склейка с предохранителями и «один сюжет» (столбец «Связанные строки»)."""
from datetime import datetime, timedelta, timezone

import numpy as np

from spacedigest.deduplicator import _dedup_pool, may_merge, title_numbers
from spacedigest.domain.models import RawItem
from spacedigest.services.export import ExportService
from spacedigest.services.ingest import ingest

from test_export import fake_dedup, read_csv, settings  # noqa: F401

NOW = datetime.now(timezone.utc)


def test_title_numbers_and_guard():
    assert title_numbers("Rocket Lab Launches 98th Electron Mission in 2026") == {"98"}
    assert title_numbers("15-й испытательный полёт Starship") == {"15"}
    a = {"title": "Electron mission 98", "published_at": "2026-11-10 10:00"}
    b = {"title": "Electron mission 99", "published_at": "2026-11-10 12:00"}
    c = {"title": "Electron launch, mission 98 success", "published_at": "2026-11-20 10:00"}
    assert not may_merge(a, b, None, True)                 # разные номера
    assert may_merge(a, c, None, True) and not may_merge(a, c, 4, True)   # окно по датам
    assert may_merge({"title": "x"}, {"title": "y"}, 4, True)              # нет дат — окно не мешает


def test_pool_skips_guarded_best_and_takes_next():
    arts = [{"title": "Electron mission 98", "published_at": "2026-11-10 10:00", "set_kind": "parser"},
            {"title": "Electron mission 99", "published_at": "2026-11-10 11:00", "set_kind": "parser"},
            {"title": "Electron flies mission 99", "published_at": "2026-11-10 12:00", "set_kind": "parser"}]
    emb = np.array([[1, 0], [0.99, 0.14], [0.98, 0.2]], dtype=np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    kept, removed = _dedup_pool(arts, emb, 0.8, False, 4, True)
    assert [k["title"] for k in kept] == ["Electron mission 98", "Electron mission 99"]
    assert removed[0]["duplicate_of"]["title"] == "Electron mission 99"


def _encoder(groups):
    """Векторы по ключевому слову заголовка: одна группа — один сюжет."""
    def enc(texts, log=None):
        out = []
        for t in texts:
            v = np.zeros(4, dtype=np.float32)
            for k, word in enumerate(groups):
                if word in t.lower():
                    v[k] = 1
            v[3] = 0.05
            out.append(v / np.linalg.norm(v))
        return np.vstack(out)
    return enc


def test_related_rows_column(db, repo, settings, tmp_path):  # noqa: F811
    src = repo.add_rss("Space", "https://s.test/")
    for ext, title, h in (("a", "Starship launches on Flight 15", 30), ("b", "SpaceX catches Starship with tower", 20),
                          ("c", "Webb finds old ice", 10), ("d", "Starship ship caught by Mechazilla", 5)):
        ingest(db, src, [RawItem(ext, title=title, url=f"https://s.test/{ext}",
                                 published_at=NOW - timedelta(hours=h))])
    svc = ExportService(db, settings, deduper=fake_dedup, downloads_dir=tmp_path / "dl",
                        export_root=tmp_path / "out", story_encoder=_encoder(["starship", "webb", "-"]))
    e = svc.prepare(mode="dates", date_from=(NOW - timedelta(days=3)).date().isoformat(),
                    date_to=NOW.date().isoformat())
    rows = read_csv(e["csv_file"])
    assert rows[0][-1] == "Связанные строки"
    by_title = {r[4]: r for r in rows[1:]}
    num = {r[4]: r[0] for r in rows[1:]}
    star = by_title["SpaceX catches Starship with tower"][-1].split(", ")
    assert set(star) == {num["Starship launches on Flight 15"], num["Starship ship caught by Mechazilla"]}
    assert by_title["Webb finds old ice"][-1] == ""
    # номера пересчитываются, если строку убрали из CSV
    webb_id = next(s["id"] for s in svc.review(e["id"])["stories"] if s["title"] == "Webb finds old ice")
    svc.change(e["id"], webb_id, "exclude")
    rows = read_csv(e["csv_file"])
    assert all(x.isdigit() for r in rows[1:] for x in r[-1].split(", ") if x)
    assert max(int(r[0]) for r in rows[1:]) == 3


def test_related_skipped_when_model_missing(db, repo, settings, tmp_path):  # noqa: F811
    src = repo.add_rss("Space", "https://s.test/")
    ingest(db, src, [RawItem("a", title="One", url="https://s.test/a", published_at=NOW),
                     RawItem("b", title="Two", url="https://s.test/b", published_at=NOW)])
    logs = []
    svc = ExportService(db, settings, deduper=fake_dedup, downloads_dir=tmp_path / "dl",
                        export_root=tmp_path / "out")             # настоящая модель: в тестах не установлена
    e = svc.prepare(mode="dates", date_from=NOW.date().isoformat(), date_to=NOW.date().isoformat(), log=logs.append)
    assert all(r[-1] == "" for r in read_csv(e["csv_file"])[1:])
    assert any("модель сюжетов недоступна" in m for m in logs)
