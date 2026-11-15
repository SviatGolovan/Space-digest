import csv
import io
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from spacedigest.core.timeutil import now_iso, to_iso
from spacedigest.domain.models import RawItem
from spacedigest.services.export import PERIOD_VAR, ExportService, full_text, local_day_bounds
from spacedigest.services.ingest import ingest
from spacedigest.settings import Settings


@pytest.fixture
def settings(tmp_path):
    s = Settings(tmp_path / "settings.json")
    s.update({"export": {"prompt": f"АНАЛИЗИРУЕМАЯ ДАТА: {PERIOD_VAR}. Обработай CSV."}})
    return s


def fake_dedup(parser_articles=None, tg_articles=None, reference_articles=None, **kw):
    """Повтор = совпадающий заголовок (в т. ч. с прошлыми выгрузками). Основная версия — сайт."""
    seen, kept, removed = {}, [], []
    for r in reference_articles or []:
        seen[r["title"].lower()] = r
    for a in (parser_articles or []) + (tg_articles or []):
        key = a["title"].lower()
        if key in seen:
            removed.append(dict(a, duplicate_of={"_item_id": seen[key]["_item_id"]}))
        else:
            seen[key] = a
            kept.append(a)
    return {"kept": kept, "removed": removed, "stats": {}}


@pytest.fixture
def svc(db, settings, tmp_path):
    return ExportService(db, settings, deduper=fake_dedup, downloads_dir=tmp_path / "Downloads",
                         export_root=tmp_path / "out")


def add(db, src, ext, title, hours_ago=1, body="", summary="", origin="collect"):
    pub = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ingest(db, src, [RawItem(ext, title=title, body=body or f"Полный текст: {title}", summary=summary,
                             url=f"https://ex.test/{ext}", published_at=pub)], origin=origin)


def read_csv(path):
    text = open(path, encoding="utf-8-sig").read()
    return list(csv.reader(io.StringIO(text)))


def test_full_text_combines_teaser_only_when_missing():
    assert full_text({"body": "Тело", "summary": ""}) == "Тело"
    assert full_text({"body": "", "summary": "Анонс"}) == "Анонс"
    assert full_text({"body": "Анонс и дальше", "summary": "Анонс…"}) == "Анонс и дальше"
    assert full_text({"body": "Тело", "summary": "Другой анонс"}) == "Другой анонс\n\nТело"


def test_first_export_then_only_new(db, repo, svc):
    site, tg = repo.add_rss("Site", "https://s.test/rss"), repo.ensure_telegram("chan")
    add(db, site, "a", "Launch of Soyuz")
    add(db, tg, "1", "Пуск Союза")
    add(db, site, "old", "Archive news", hours_ago=24 * 10, origin="import30")
    e1 = svc.prepare()
    rows = read_csv(e1["csv_file"])
    assert rows[0] == ["ID", "Дата публикации", "Источник", "Тип источника", "Заголовок",
                       "Полный текст", "Ссылка", "Другие источники"]
    assert {r[4] for r in rows[1:]} == {"Launch of Soyuz", "Пуск Союза"}
    assert {r[3] for r in rows[1:]} == {"Сайт", "Telegram"}
    assert rows[1][0] == "1" and rows[1][6].startswith("https://ex.test/")
    today = datetime.now().astimezone().date().isoformat()
    assert e1["prompt"].startswith("АНАЛИЗИРУЕМАЯ ДАТА: ") and PERIOD_VAR not in e1["prompt"]
    assert today in e1["prompt"]
    assert open(e1["prompt_file"], encoding="utf-8").read() == e1["prompt"]

    with pytest.raises(ValueError, match="нет новых"):
        svc.prepare()                                  # ничего нового не пришло
    time.sleep(1.1)                                    # fetched_at с точностью до секунды
    add(db, site, "b", "Fresh news")
    add(db, site, "old2", "Imported later", origin="import30")
    e2 = svc.prepare()
    assert [r[4] for r in read_csv(e2["csv_file"])[1:]] == ["Fresh news"]


def test_duplicates_removed_including_previous_exports(db, repo, svc):
    site, tg = repo.add_rss("Site", "https://s.test/rss"), repo.ensure_telegram("chan")
    add(db, site, "a", "Same event")
    add(db, tg, "1", "same event")                     # повтор внутри выгрузки
    e1 = svc.prepare()
    assert e1["items_exported"] == 1 and e1["duplicates_removed"] == 1
    dup = db.one("SELECT * FROM export_items WHERE export_id=? AND row_no IS NULL", (e1["id"],))
    assert dup["duplicate_of"] is not None and dup["state"] == "merged"
    time.sleep(1.1)
    add(db, tg, "2", "Same Event")                     # то же событие на следующий день
    with pytest.raises(ValueError, match="уже были"):
        svc.prepare()


def test_dates_mode_and_bounds(db, repo, svc):
    site = repo.add_rss("Site", "https://s.test/rss")
    add(db, site, "x", "Old", hours_ago=24 * 5, origin="import30")
    d = (datetime.now().astimezone() - timedelta(days=5)).date().isoformat()
    p = svc.preview("dates", d, d)
    assert p["total"] == 1 and p["period_from"] == d
    e = svc.prepare("dates", d, d, dedupe=False)
    assert e["mode"] == "dates" and e["period_from"] == e["period_to"] == d
    assert os.path.basename(e["csv_file"]) == f"news_{d}.csv"
    lo, hi = local_day_bounds(d, d)
    assert lo < hi


def test_kinds_filter(db, repo, svc):
    site, tg = repo.add_rss("Site", "https://s.test/rss"), repo.ensure_telegram("chan")
    add(db, site, "a", "Site only")
    add(db, tg, "1", "Только телеграм")
    p = svc.preview(kinds=("telegram",))
    assert p["total"] == 1 and p["by_kind"] == {"rss": 0, "telegram": 1}


def test_collect_result_docx_from_downloads(db, repo, svc, tmp_path):
    site = repo.add_rss("Site", "https://s.test/rss")
    add(db, site, "a", "News")
    e = svc.prepare()
    with pytest.raises(ValueError, match="нет нового DOCX"):
        svc.attach_result(e["id"])
    dl = tmp_path / "Downloads"; dl.mkdir()
    old = dl / "old.docx"; old.write_bytes(b"x")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    (dl / "~$lock.docx").write_bytes(b"x")
    fresh = dl / "Дайджест.docx"; fresh.write_bytes(b"docx")
    with pytest.raises(ValueError):                       # ещё записывается (изменён < 2 с назад)
        svc.attach_result(e["id"])
    os.utime(fresh, (time.time() - 5, time.time() - 5))
    done = svc.attach_result(e["id"])
    assert done["status"] == "done" and done["result_file"].endswith("Дайджест.docx")
    assert os.path.exists(done["result_file"])
    assert svc.list()[0]["id"] == e["id"]


def test_docx_saved_straight_into_export_folder_is_found(db, repo, svc, tmp_path):
    site = repo.add_rss("Site", "https://s.test/rss")
    add(db, site, "a", "News")
    e = svc.prepare()
    p = os.path.join(e["folder"], "digest.docx")
    open(p, "wb").write(b"docx"); os.utime(p, (time.time() - 5, time.time() - 5))
    assert svc.attach_result(e["id"])["result_file"] == p


def test_default_prompt_has_period_variable():
    from spacedigest.services.export import default_prompt
    p = default_prompt()
    assert p.count(PERIOD_VAR) == 1 and "CSV" in p and "ИСТОЧНИК" in p
