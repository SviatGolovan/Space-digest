import pytest

from spacedigest.services.export import ExportService
from spacedigest.services.filters import DEFAULT_STOP, DEFAULT_TOPIC, ContentFilter, compile_words

from test_export import add, fake_dedup, read_csv, settings  # noqa: F401  (фикстура settings)


def test_word_syntax_stems_whole_words_phrases_and_comments():
    rx = compile_words("# комментарий\nракет*\nESA\nмагнитн* бур*\n#реклама\nerid\n")
    assert rx.search("Новая РАКЕТА-носитель") and rx.search("ракетостроение")
    assert rx.search("ESA and NASA") and not rx.search("Mesa Verde")
    assert rx.search("Ожидается магнитная  буря") and rx.search("#реклама")
    assert not rx.search("комментарий") and not rx.search("Meridian") and rx.search("erid: 2Vtz")


def test_default_lists_catch_ads_and_keep_space_news():
    stop, topic = compile_words(DEFAULT_STOP), compile_words(DEFAULT_TOPIC)
    assert stop.search("Скидка по промокоду FEAR10. Реклама. erid: 2VtzqXYZ")
    assert not stop.search("Ракета стартовала с Байконура")
    for t in ("Союз-2.1б вывел спутник", "Starship flight 12", "Магнитная буря", "the ISS crew",
              "Shenzhou-23 crew", "Eutelsat LEO revenue"):
        assert topic.search(t), t
    for t in ("Michigan Senate race", "Союзники по НАТО", "9 dead as private jet crashes", "Starting a startup"):
        assert not topic.search(t), t


@pytest.fixture
def svc(db, settings, tmp_path):  # noqa: F811
    return ExportService(db, settings, deduper=fake_dedup, downloads_dir=tmp_path / "Downloads",
                         export_root=tmp_path / "out")


def test_export_filters_ads_and_off_topic_only_for_marked_sources(db, repo, svc):
    scmp, tg = repo.add_rss("SCMP", "https://scmp.test/rss"), repo.ensure_telegram("chan")
    add(db, scmp, "a", "Michigan Senate race", body="Election news.")
    add(db, scmp, "b", "China launches Shenzhou crew", body="Launch from Jiuquan.")
    add(db, tg, "1", "Скидка", body="Промокод FEAR10 на всё. erid: 2Vtz")
    add(db, tg, "2", "Кот", body="Просто кот.")                     # у канала нет «только про космос»
    assert svc.preview(mode="since_last")["filtered"] == 1
    repo.update(scmp.id, space_only=True)
    p = svc.preview(mode="since_last")
    assert p["filtered"] == 2
    assert {x["title"]: x["filtered"] for x in p["sample"]}["Michigan Senate race"].startswith("не про космос")

    e = svc.prepare()
    assert {r[4] for r in read_csv(e["csv_file"])[1:]} == {"China launches Shenzhou crew", "Кот"}
    rv = svc.review(e["id"])
    assert rv["counts"]["filtered"] == 2
    reasons = {f["title"]: f["reason"] for f in rv["filtered"]}
    assert reasons["Скидка"].startswith("стоп-слово") and "Michigan Senate race" in reasons

    svc.change(e["id"], next(f["id"] for f in rv["filtered"] if f["title"] == "Скидка"), "restore")
    assert len(read_csv(e["csv_file"])) == 4


def test_new_rule_refilters_open_export_but_never_empties_it(db, repo, svc, settings):  # noqa: F811
    site = repo.add_rss("Site", "https://s.test/rss")
    add(db, site, "a", "Кот дня", body="Кот.")
    add(db, site, "b", "Запуск ракеты", body="Ракета стартовала.")
    e = svc.prepare()
    flt = ContentFilter(db, settings)
    flt.add_stop("кот*")
    assert "кот*" in settings.get("filter", "stop") and DEFAULT_STOP.strip().splitlines()[1] in settings.get("filter", "stop")
    assert svc.refilter(e["id"]) == 1
    assert [r[4] for r in read_csv(e["csv_file"])[1:]] == ["Запуск ракеты"]
    flt.add_stop("ракет*")
    with pytest.raises(ValueError, match="все строки"):
        svc.refilter(e["id"])


def test_suggestions_from_stats_and_manual_exclusions(db, repo, svc, settings):  # noqa: F811
    scmp, good = repo.add_rss("SCMP", "https://scmp.test/rss"), repo.add_rss("Space", "https://sp.test/rss")
    for n in range(12):
        add(db, scmp, f"s{n}", f"Politics story {n}", body="Elections and markets.")
        add(db, good, f"g{n}", f"Rocket launch {n}", body="Orbit reached.")
    stats = {s["name"]: s for s in ContentFilter(db, settings).source_stats()}
    assert stats["SCMP"]["recommended"] and stats["SCMP"]["share"] == 1.0
    assert not stats["Space"]["recommended"]

    tg = repo.ensure_telegram("chan")
    add(db, tg, "p1", "Розница", body="Покупайте мерч FEARSHOP сегодня.")
    add(db, tg, "p2", "Мерч", body="Новый мерч FEARSHOP уже в продаже.")
    add(db, tg, "p3", "Футболки", body="Футболки FEARSHOP с ракетой.")
    add(db, tg, "p4", "Луна", body="Китай готовит высадку на Луну. Высадка в 2030.")
    e = svc.prepare()
    for f in svc.review(e["id"])["stories"]:
        if f["title"] in ("Розница", "Мерч"):
            svc.change(e["id"], f["id"], "exclude")
    assert ContentFilter(db, settings).suggest_stop() == []          # двух случаев мало
    for f in svc.review(e["id"])["stories"]:
        if f["title"] in ("Футболки", "Луна"):
            svc.change(e["id"], f["id"], "exclude")
    sg = ContentFilter(db, settings).suggestions(e["id"])
    words = [w["word"] for w in sg["stop"]]
    assert "fearshop" in words and not any(w.startswith(("луну", "ракет")) for w in words)
    assert [s["name"] for s in sg["sources"]] == ["SCMP"]
