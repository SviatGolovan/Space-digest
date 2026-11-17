"""Дайджест СЛК: страницы без RSS, надёжные даты, предфильтр, окно с перекрытием, повторы."""
import json
from datetime import datetime, timedelta, timezone

from conftest import FakeResponse, FakeSession
from spacedigest.connectors.html_page import date_from_text, parse_listing
from spacedigest.connectors.rss import RssConnector
from spacedigest.domain.models import RawItem, SourceState
from spacedigest.services.export import ExportService
from spacedigest.services.fulltext import FullText
from spacedigest.services.ingest import ingest
from spacedigest.services.slk import SlkFilter
from spacedigest.services.slk_import import import_slk

from test_export import fake_dedup, read_csv, settings  # noqa: F401

NOW = datetime.now(timezone.utc)
D = lambda days: (NOW - timedelta(days=days)).strftime("%d.%m.%Y")   # noqa: E731

LISTING = f"""<html><head><title>Новости — Space Energy</title></head><body>
<header><a href="/">Главная</a><a href="/contacts">Контакты</a></header>
<div class="news-list">
  <div class="news-item"><a href="/news/kamchatka-start"><h3>Space Energy выполнила пуск прототипа ракеты «Камчатка»</h3></a>
    <span class="date">{D(3)}</span><p>Суборбитальный прототип поднялся на высоту 12 км.</p></div>
  <div class="news-item"><a href="/news/se1-fire"><h3>Огневые стендовые испытания камеры сгорания двигателя SE-1</h3></a>
    <p>Испытания прошли на стенде компании.</p></div>
  <div class="news-item"><a href="tel:+79100248010"><h3>+7 (910) 024 80 10</h3></a></div>
  <div class="news-item"><a href="/news/all"><h3>Все новости</h3></a></div>
</div><footer><a href="/privacy">Политика конфиденциальности</a></footer></body></html>"""


# ─── страница новостей ──────────────────────────────────────────────────────

def test_listing_keeps_cards_drops_menu_and_marks_card_dates():
    items = parse_listing(LISTING, "https://spaceenergy.su/news/")
    assert [i.url for i in items] == ["https://spaceenergy.su/news/kamchatka-start",
                                      "https://spaceenergy.su/news/se1-fire"]
    dated, undated = items
    assert dated.published_at and dated.date_from == "card"
    assert undated.published_at is None and undated.date_from is None     # дату не выдумываем


def test_date_from_text_formats_and_future_dates():
    assert date_from_text("5 марта 2026").strftime("%Y-%m-%d") == "2026-03-05"
    assert date_from_text("March 5, 2026").strftime("%Y-%m-%d") == "2026-03-05"
    assert date_from_text("05.03.2026").strftime("%Y-%m-%d") == "2026-03-05"
    assert date_from_text("пуск запланирован на 1 января 2099") is None   # будущее — не дата публикации


def test_html_source_without_feed_is_parsed_as_page(repo):
    src = repo.add_rss("Space Energy", "https://spaceenergy.su/news/")
    src = repo.update(src.id, config={"html": True})
    sess = FakeSession({"https://spaceenergy.su/news/": FakeResponse(
        "https://spaceenergy.su/news/", LISTING.encode(), headers={"Content-Type": "text/html"})})
    res = RssConnector(session=sess).fetch(src, SourceState())
    assert len(res.items) == 2 and res.state.resolved_url == "html"
    assert "без даты 1" in res.note
    # второй сбор — сразу страница, без поиска ленты
    sess.calls.clear()
    RssConnector(session=sess).fetch(src, res.state)
    assert [u for u, _ in sess.calls] == ["https://spaceenergy.su/news/"]


# ─── даты при приёме ────────────────────────────────────────────────────────

def _status(db, ext):
    return db.one("SELECT date_status, published_at FROM items WHERE external_id = ?", (ext,))


def test_undated_items_first_run_are_archive_later_unconfirmed(db, repo):
    src = repo.add_rss("Site", "https://s.test/")
    ingest(db, src, [RawItem("old", title="Старая новость без даты")], first_run=True)
    ingest(db, src, [RawItem("new", title="Новая новость без даты")])
    ingest(db, src, [RawItem("card", title="Из карточки", published_at=NOW, date_from="card")])
    ingest(db, src, [RawItem("feed", title="Из ленты", published_at=NOW)])
    assert _status(db, "old")["date_status"] == "baseline"
    assert _status(db, "new")["date_status"] == "none"
    assert _status(db, "card")["date_status"] == "card"
    assert _status(db, "feed")["date_status"] is None


def test_page_date_replaces_card_date(db, repo, settings):  # noqa: F811
    src = repo.add_rss("Site", "https://s.test/")
    ingest(db, src, [RawItem("a", title="Новость", url="https://s.test/a", body="x" * 900)])
    page = ('<html><head><meta property="article:published_time" content="2024-05-17T10:00:00+03:00">'
            '</head><body><article><p>Текст.</p></article></body></html>')

    class R:
        status_code, headers, text = 200, {"Content-Type": "text/html"}, page
    ft = FullText(db, settings, http_get=lambda u: R(), sleep=lambda s: None)
    res = ft.process(ft.pending())
    row = _status(db, "a")
    assert res["dated"] == 1 and row["date_status"] == "page" and row["published_at"].startswith("2024-05-17")


# ─── предфильтр ─────────────────────────────────────────────────────────────

def _src(repo, name, url, **cfg):
    s = repo.add_rss(name, url)
    return repo.update(s.id, config=cfg, scope="slk")


def test_prefilter_rules(db, repo, settings):  # noqa: F811
    trusted = _src(repo, "Компания", "https://co.test/", slk_trusted=True)
    general = _src(repo, "РБК", "https://rbc.test/", general=True)
    space = repo.add_rss("Космос", "https://space.test/")
    check = SlkFilter(db, settings).checker()
    row = lambda s, t: {"id": 1, "source_id": s.id, "title": t, "body": "", "summary": ""}  # noqa: E731
    assert check(row(trusted, "Компания провела совещание")) is None
    assert check(row(general, "Ракетный удар по городу")).startswith("военная")
    assert check(row(general, "Курс рубля и запуск нового сервиса")).startswith("не про космос")
    assert check(row(general, "Ракета «Союз-5» прошла огневые испытания")) is None
    assert check(row(space, "Телескоп Уэбб нашёл экзопланету")).startswith("не про ракеты")
    assert check(row(space, "Rocket Lab прошла квалификацию")) is None               # название из перечня
    assert check(row(space, "Galactic Energy готовит запуск Ceres-1S с моря")) is None


# ─── выгрузка СЛК ───────────────────────────────────────────────────────────

def _slk(db, settings, tmp_path):  # noqa: F811
    return ExportService(db, settings, deduper=fake_dedup, downloads_dir=tmp_path / "dl",
                         export_root=tmp_path / "out", profile="slk")


def _space(db, settings, tmp_path):  # noqa: F811
    return ExportService(db, settings, deduper=fake_dedup, downloads_dir=tmp_path / "dl",
                         export_root=tmp_path / "out2")


def _add(db, src, ext, title, days_ago=1, **kw):
    ingest(db, src, [RawItem(ext, title=title, body=f"Полный текст: {title}", url=f"https://x.test/{ext}",
                             published_at=NOW - timedelta(days=days_ago) if days_ago is not None else None,
                             **kw)])


def test_slk_window_scope_columns_and_undated_label(db, repo, settings, tmp_path):  # noqa: F811
    co = _src(repo, "Space Energy", "https://co.test/", slk_trusted=True, html=True)
    common = repo.add_rss("NASASpaceflight", "https://nsf.test/")
    _add(db, co, "fresh", "Пуск прототипа «Камчатка»", 2)
    _add(db, co, "overlap", "Огневые испытания SE-1", 17)             # в неделе перекрытия
    _add(db, co, "old", "Совсем старое", 40)                          # вне окна
    ingest(db, co, [RawItem("arch", title="Архив сайта без даты", url="https://x.test/arch")], first_run=True)
    ingest(db, co, [RawItem("nodate", title="Новость без даты", url="https://x.test/nodate")])
    _add(db, common, "launch", "Electron launches HawkEye 360 satellites", 1)

    slk = _slk(db, settings, tmp_path)
    e = slk.prepare(mode="window")
    rows = read_csv(e["csv_file"])
    head, body = rows[0], rows[1:]
    assert head[:3] == ["ID", "Дата публикации", "Дата проверена"] and head[-1] == "Было в прошлом дайджесте"
    titles = {r[5] for r in body}
    assert titles == {"Пуск прототипа «Камчатка»", "Огневые испытания SE-1", "Новость без даты",
                      "Electron launches HawkEye 360 satellites"}
    undated = next(r for r in body if r[5] == "Новость без даты")
    assert undated[2].startswith("НЕ ПОДТВЕРЖДЕНА")
    assert e["profile"] == "slk" and e["csv_file"].split("/")[-1].startswith("slk_news_")
    w = slk.window()
    assert (e["period_from"], e["period_to"]) == (w["date_from"], w["date_to"])
    assert "{{" not in e["prompt"] and w["new_from"] in e["prompt"]

    # общая выгрузка не видит источник СЛК и архив сайта
    sp = _space(db, settings, tmp_path).prepare(mode="dates", date_from=w["date_from"], date_to=w["date_to"])
    sp_titles = {r[4] for r in read_csv(sp["csv_file"])[1:]}
    assert sp_titles == {"Electron launches HawkEye 360 satellites"}
    assert [x["id"] for x in slk.list()] == [e["id"]]          # истории раздельные


def test_slk_repeats_stay_in_csv_with_note(db, repo, settings, tmp_path):  # noqa: F811
    co = _src(repo, "Rocket Lab", "https://rl.test/", slk_trusted=True)
    _add(db, co, "a", "Electron mission 98", 3)
    slk = _slk(db, settings, tmp_path)
    first = slk.prepare(mode="window")
    _add(db, co, "b", "Electron mission 99", 1)
    second = slk.prepare(mode="window")
    body = {r[5]: r for r in read_csv(second["csv_file"])[1:]}
    assert body["Electron mission 98"][-1].startswith("да, выгрузка СЛК от")
    assert body["Electron mission 99"][-1] == ""
    assert first["id"] != second["id"]
    rv = slk.review(second["id"])
    assert any(s["note"] for s in rv["stories"])


# ─── источники и перенос ────────────────────────────────────────────────────

def test_sync_slk_adds_once_skips_known_urls_and_keeps_override(db, repo):
    repo.add_rss("Уже есть", "https://dup.test/feed")
    slk = [{"id": "slk_a", "name": "A", "url": "https://a.test/", "config": {"html": True}},
           {"id": "slk_dup", "name": "Dup", "url": "https://dup.test/feed", "config": {}}]
    assert repo.sync_slk(slk) == 1
    assert repo.sync_slk(slk) == 0
    a = repo.by_key("slk_a")
    assert a.scope == "slk" and a.config["html"] and a.builtin
    cfg = dict(a.config, url_override="https://a.test/news", html=False)
    db.execute("UPDATE sources SET url=?, config=? WHERE id=?", ("https://a.test/news", json.dumps(cfg), a.id))
    repo.sync_slk(slk)
    a = repo.by_key("slk_a")
    assert a.url == "https://a.test/news" and a.config["html"] is False


def test_sync_slk_telegram_added_once(db, repo):
    tg = [{"channel": "se_data", "name": "Space Energy (Telegram)", "trusted": True}]
    assert repo.sync_slk([], tg) == 1
    src = repo.by_key("tg:se_data")
    assert src.config["slk_trusted"] and src.name == "Space Energy (Telegram)"
    db.execute("DELETE FROM sources WHERE id = ?", (src.id,))
    assert repo.sync_slk([], tg) == 0 and repo.by_key("tg:se_data") is None   # удалённый не возвращается


def test_import_old_slk_parser(db, repo, tmp_path):
    repo.sync_slk([{"id": "slk_isar", "name": "Isar", "url": "https://isar.test/newsroom", "config": {"html": True}}])
    old = tmp_path / "SLK Parser"
    (old / "data").mkdir(parents=True)
    (old / "data" / "custom_sources.json").write_text(json.dumps([
        {"id": "custom_x", "name": "Orbex News", "url": "https://orbex.test/news", "type": "html", "filter": False},
        {"id": "custom_y", "name": "Bad", "url": "ftp://nope"}]), encoding="utf-8")
    (old / "data" / "source_overrides.json").write_text(json.dumps(
        {"isar": {"url": "https://isar.test/feed", "type": "rss"}}), encoding="utf-8")
    (old / "gemini_config.json").write_text("{}", encoding="utf-8")
    rep = import_slk(repo, str(old))
    assert rep["added"] == 1 and rep["urls_fixed"] == 1 and rep["skipped"] == ["Bad"] and rep["notes"]
    orbex = [s for s in repo.list() if s.name == "Orbex News"][0]
    assert orbex.scope == "slk" and orbex.config == {"html": True, "slk_trusted": True}
    assert repo.by_key("slk_isar").url == "https://isar.test/feed"
    assert import_slk(repo, str(old))["exists"] == 1                     # повторный перенос не дублирует
