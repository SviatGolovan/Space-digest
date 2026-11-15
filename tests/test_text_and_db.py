from spacedigest.core.db import Database
from spacedigest.core.timeutil import parse_any, to_iso
from spacedigest.domain.text import canonical_url, content_hash, guess_lang, html_to_text, one_line


def test_html_to_text_keeps_paragraphs_and_decodes_entities():
    t = html_to_text("<p>NASA&#8217;s &amp; ESA</p><p>Line<br>two</p><script>x()</script>")
    assert t == "NASA’s & ESA\n\nLine\ntwo"


def test_html_to_text_strips_wordpress_tail_and_invisible_chars():
    t = html_to_text("<p>Body⁠ text</p><p>The post Foo appeared first on Bar.</p>")
    assert t == "Body text"


def test_one_line_collapses():
    assert one_line("A <i>b</i>\n\n c") == "A b c"


def test_canonical_url_variants_collapse():
    a = canonical_url("https://www.example.com/a/?utm_source=rss&id=5#frag")
    b = canonical_url("http://example.com/a/amp/?id=5&fbclid=zzz")
    assert a == b == "https://example.com/a?id=5"
    assert canonical_url("") == ""


def test_content_hash_ignores_markup_and_case():
    assert content_hash("Title", "Some  TEXT!") == content_hash("title", "some text")
    assert content_hash("Title", "a") != content_hash("Title", "b")


def test_guess_lang():
    assert guess_lang("Роскосмос сообщил о запуске ракеты") == "ru"
    assert guess_lang("NASA announced a new mission today") == "en"
    assert guess_lang("123") == ""


def test_parse_any_formats():
    assert to_iso(parse_any("2026-11-13 07:00 UTC")) == "2026-11-13T07:00:00Z"
    assert to_iso(parse_any("2026-05-31 08:03:20.000000")) == "2026-05-31T08:03:20Z"
    assert to_iso(parse_any("Fri, 13 Nov 2026 10:00:00 +0300")) == "2026-11-13T07:00:00Z"
    assert to_iso(parse_any("2026-11-13T10:00:00+03:00")) == "2026-11-13T07:00:00Z"
    assert parse_any("garbage") is None


def test_migrations_idempotent_and_backup(tmp_path):
    db = Database(tmp_path / "x.db")
    assert db.migrate() >= 1
    v = db.version()
    assert db.migrate() == v
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sources", "items", "jobs", "schedules", "meta", "source_state"} <= tables
    db.close()


def test_tx_rolls_back_on_error(db):
    try:
        with db.tx():
            db.set_meta("k", "v")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert db.get_meta("k") is None
    with db.tx():
        with db.tx():                       # вложенная транзакция — часть внешней
            db.set_meta("k", "v2")
    assert db.get_meta("k") == "v2"


def test_fix_mojibake_repairs_utf8_read_as_cp1252():
    from spacedigest.domain.text import fix_mojibake
    assert fix_mojibake("each planetâ€™s striking features") == "each planet’s striking features"
    broken = "Космос".encode("utf-8").decode("latin-1")
    assert fix_mojibake(broken) == "Космос"
    for ok in ("Café — normal", "Москва", "", "It’s fine"):
        assert fix_mojibake(ok) == ok
