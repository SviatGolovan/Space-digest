import pytest

from spacedigest.services.calibrate import Calibrator, best_threshold
from spacedigest.services.export import ExportService

from test_export import add, settings  # noqa: F401  (фикстура settings)


def test_best_threshold_separates_answers_and_prefers_strict():
    labels = [(0.95, True), (0.91, True), (0.88, True), (0.86, True), (0.84, False),
              (0.80, False), (0.78, True), (0.75, False), (0.72, False), (0.70, False)]
    r = best_threshold(labels)
    assert 0.84 < r["threshold"] <= 0.86 and r["false_merges"] == 0 and r["missed"] == 1
    assert best_threshold(labels[:5]) is None                          # мало ответов
    assert best_threshold([(0.9, True)] * 10) is None                  # нет «разных»


def test_pairs_label_and_apply(db, repo, settings, tmp_path):  # noqa: F811
    site, tg = repo.add_rss("Site", "https://s.test/rss"), repo.ensure_telegram("chan")
    texts = ["SpaceX Starship flight test from Starbase Texas", "Starship flight test SpaceX Starbase launch",
             "Roscosmos Progress cargo ship docks with ISS", "Progress cargo ship docks ISS Roscosmos today",
             "ESA Ariane 6 launch delayed weather", "NASA Artemis crew training update"]
    for k, t in enumerate(texts):
        add(db, site if k % 2 else tg, f"x{k}", t, body=t)
    settings.update({"dedup": {"engine": "tfidf", "threshold": 0.5}})
    exp = ExportService(db, settings, export_root=tmp_path / "out")
    cal = Calibrator(db, settings, exp)
    d = cal.pairs(n=10)
    assert d["backend"] == "tfidf" and d["pairs"]
    ids = [x for p in d["pairs"] for x in (p["a"]["id"], p["b"]["id"])]
    assert len(ids) == len(set(ids))                                   # новость — не больше чем в одной паре
    lo, hi = d["range"]
    assert all(lo <= p["similarity"] <= hi for p in d["pairs"])
    p = d["pairs"][0]
    res = cal.label(p["a"]["id"], p["b"]["id"], True, p["similarity"], "tfidf")
    assert res["labels"] == 1 and res["need"] == 7 and res["best"] is None
    again = cal.pairs(n=10)                                            # отвеченная пара больше не предлагается
    assert all({q["a"]["id"], q["b"]["id"]} != {p["a"]["id"], p["b"]["id"]} for q in again["pairs"])
    assert cal.apply(0.874) == 0.874 and settings.get("dedup", "threshold") == 0.874
    assert cal.reset() == 1


def test_pairs_need_news(db, settings, tmp_path):  # noqa: F811
    cal = Calibrator(db, settings, ExportService(db, settings, export_root=tmp_path))
    with pytest.raises(ValueError, match="мало новостей"):
        cal.pairs()
