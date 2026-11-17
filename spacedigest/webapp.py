"""
Flask-часть приложения: страницы «Сайты», «Telegram», «Дедупликатор», «Настройки»
и их API. Вызывается из main.py: init(data_dir) → app.run(...) в фоне,
а окно приложения показывает этот интерфейс.
"""
from __future__ import annotations

import functools
import io
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

from . import APP_NAME, VERSION, deduplicator, paths
from .deduplicator import DEFAULT_MODEL, parse_csv_articles, run_deduplication
from .exporters import articles_to_csv, articles_to_markdown, articles_to_xlsx
from .fetcher import SpaceNewsFetcher
from .migrate import import_old_version
from .settings import Settings
from .sources import SOURCES
from .telegram_service import TelegramService, normalize_channel
from .translator import make_translator

RES = paths.resource_dir()
app = Flask(__name__, template_folder=str(RES / "templates"), static_folder=str(RES / "static"))
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0          # после обновления — без Ctrl+F5
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

# Заполняются в init()
DATA_DIR: Path = Path(".")
JOBS_DIR = DEDUP_DIR = UPLOADS_DIR = TG_DIR = WEEKS_DIR = DATA_DIR
settings: Settings = None          # type: ignore[assignment]
tg: TelegramService = None         # type: ignore[assignment]
core = None                        # ядро 4.0 (spacedigest.core.runtime.Core)

jobs: dict = {}            # выгрузки сайтов
dedup_jobs: dict = {}      # прогоны дедупликатора
uploads_store: dict = {}   # загруженные CSV
tg_jobs: dict = {}         # выборки Telegram из базы
tasks: dict = {}           # служебные фоновые задачи (обновление TG, скачивание модели)
_admin_tokens: set = set()


def init(data_dir: Path) -> None:
    """Подготовить папки, настройки, Telegram и загрузить историю."""
    global DATA_DIR, JOBS_DIR, DEDUP_DIR, UPLOADS_DIR, TG_DIR, WEEKS_DIR, settings, tg
    DATA_DIR = Path(data_dir)
    JOBS_DIR, DEDUP_DIR = DATA_DIR / "jobs", DATA_DIR / "dedup"
    UPLOADS_DIR, TG_DIR, WEEKS_DIR = DATA_DIR / "uploads", DATA_DIR / "tg", DATA_DIR / "weeks"
    for d in (JOBS_DIR, DEDUP_DIR, UPLOADS_DIR, TG_DIR, WEEKS_DIR, DATA_DIR / "models"):
        d.mkdir(parents=True, exist_ok=True)
    deduplicator.MODELS_DIR = str(DATA_DIR / "models")
    from .services.maintenance import apply_pending_restore
    import logging
    try:
        apply_pending_restore(DATA_DIR, logging.getLogger(__name__).info)   # до открытия базы
    except Exception:                                                        # noqa: BLE001
        logging.getLogger(__name__).exception("Восстановление из копии не удалось")
    settings = Settings(DATA_DIR / "settings.json")
    tg = TelegramService(DATA_DIR, settings)
    load_history()
    start_core()           # Telegram теперь собирает ядро (расписание collect_telegram)


def start_core() -> None:
    """Ядро 4.0: единая база + автосбор. Сбой ядра не должен ронять интерфейс 3.0."""
    global core
    try:
        from .core.runtime import Core
        core = Core(DATA_DIR, settings, tg)
        core.start()
    except Exception:                                    # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("Ядро 4.0 не запустилось")
        core = None


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ─── ПАРОЛЬ НА НАСТРОЙКИ ──────────────────────────────────────────────────────

def _token_ok() -> bool:
    if not settings.password_set():
        return True
    body = request.get_json(silent=True) or {}
    token = request.headers.get("X-Admin-Token") or body.get("_admin_token")
    return bool(token and token in _admin_tokens)


def require_admin(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if _token_ok():
            return fn(*args, **kwargs)
        return jsonify({"error": "нужен пароль для изменения настроек", "admin_required": True}), 403
    return wrapper


@app.route("/api/admin/status")
def api_admin_status():
    token = request.headers.get("X-Admin-Token", "")
    return jsonify({"protected": settings.password_set(), "unlocked": token in _admin_tokens})


@app.route("/api/admin/unlock", methods=["POST"])
def api_admin_unlock():
    pw = (request.get_json(silent=True) or {}).get("password", "")
    if not settings.password_set():
        return jsonify({"ok": True, "token": ""})
    if settings.verify_password(pw):
        token = secrets.token_hex(16)
        _admin_tokens.add(token)
        return jsonify({"ok": True, "token": token})
    time.sleep(0.6)                                   # не даём перебирать быстро
    return jsonify({"ok": False, "error": "неверный пароль"}), 401


@app.route("/api/admin/lock", methods=["POST"])
def api_admin_lock():
    token = request.headers.get("X-Admin-Token") or (request.get_json(silent=True) or {}).get("token", "")
    _admin_tokens.discard(token)
    return jsonify({"ok": True})


# ─── ПЕРСИСТЕНТНОСТЬ ИСТОРИИ ──────────────────────────────────────────────────

def _save_json(path: Path, obj) -> None:
    try:
        tmp = Path(str(path) + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


def save_job(job_id: str) -> None:
    job = jobs.get(job_id)
    if job and job.get("status") == "done":
        _save_json(JOBS_DIR / f"{job_id}.json", {
            "articles": job.get("articles", []), "finished_at": job.get("finished_at", ""),
            "translated": job.get("translated", False), "name": job.get("name", ""),
            "log": job.get("log", [])[-200:]})


def save_dedup(dedup_id: str) -> None:
    job = dedup_jobs.get(dedup_id)
    if job and job.get("status") == "done":
        _save_json(DEDUP_DIR / f"{dedup_id}.json", {
            "result": job.get("result"), "finished_at": job.get("finished_at", ""),
            "translated": job.get("translated", False), "name": job.get("name", "")})


def save_upload(upload_id: str) -> None:
    up = uploads_store.get(upload_id)
    if up:
        _save_json(UPLOADS_DIR / f"{upload_id}.json", up)


def save_tg_job(tg_id: str) -> None:
    job = tg_jobs.get(tg_id)
    if job and job.get("status") == "done":
        _save_json(TG_DIR / f"{tg_id}.json", {
            "articles": job.get("articles", []), "finished_at": job.get("finished_at", ""),
            "translated": job.get("translated", False), "name": job.get("name", "")})


def _stores():
    return {"parser": (jobs, JOBS_DIR, save_job), "dedup": (dedup_jobs, DEDUP_DIR, save_dedup),
            "tg": (tg_jobs, TG_DIR, save_tg_job)}


def delete_history_item(kind: str, item_id: str) -> bool:
    store, folder, _ = _stores().get(kind, _stores()["parser"])
    store.pop(item_id, None)
    p = folder / f"{item_id}.json"
    try:
        if p.exists():
            p.unlink()
        return True
    except Exception:
        return False


def load_history() -> None:
    jobs.clear(); dedup_jobs.clear(); uploads_store.clear(); tg_jobs.clear()
    for store, folder, key in ((jobs, JOBS_DIR, "articles"), (tg_jobs, TG_DIR, "articles"),
                               (dedup_jobs, DEDUP_DIR, "result")):
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(".json"):
                continue
            try:
                d = json.load(open(folder / fn, encoding="utf-8"))
                store[fn[:-5]] = {"status": "done", "progress": 100, "log": d.get("log", []),
                                  key: d.get(key, [] if key == "articles" else None),
                                  "finished_at": d.get("finished_at", ""),
                                  "translated": d.get("translated", False),
                                  "name": d.get("name", "")}
            except Exception:
                pass
    for fn in sorted(os.listdir(UPLOADS_DIR)):
        if fn.endswith(".json"):
            try:
                uploads_store[fn[:-5]] = json.load(open(UPLOADS_DIR / fn, encoding="utf-8"))
            except Exception:
                pass


# ─── ИСТОЧНИКИ ────────────────────────────────────────────────────────────────

def get_sources() -> list:
    """Встроенные (с учётом «включён по умолчанию» из настроек) + свои."""
    ov = settings.get("sources", "overrides") or {}
    out = []
    for s in SOURCES:
        s = dict(s)
        if s["id"] in ov:
            s["enabled"] = bool(ov[s["id"]])
        out.append(s)
    for s in settings.get("sources", "custom") or []:
        s = dict(s)
        s["custom"] = True
        s.setdefault("enabled", True)
        out.append(s)
    return out


def translation_params(req: dict | None = None) -> tuple[str, str]:
    """(provider, deepl_key) из настроек; ключ со страницы (старый формат) тоже понимаем."""
    key = ((req or {}).get("deepl_key") or "").strip()
    provider = settings.get("translation", "provider")
    if not key and provider == "deepl":
        key = settings.get("translation", "deepl_key") or ""
    return ("deepl" if key else "google"), key


# ─── СТРАНИЦЫ ────────────────────────────────────────────────────────────────

def _page(tpl: str, **kw):
    g = (settings.get("general") or {}) if settings else {}
    fx = bool(g.get("animations", True))
    theme = g.get("theme") or "light"
    return render_template(tpl, app_name=APP_NAME, version=VERSION, fx_on=fx, theme=theme, **kw)


@app.route("/home")
def home_page():
    return _page("home.html")


@app.route("/api/dashboard")
def api_dashboard():
    if (r := _need_core()):
        return r
    from .services.dashboard import overview
    return jsonify({"ok": True, **overview(core)})


@app.route("/")
def index():
    return _page("index.html", sources=get_sources())


@app.route("/tg")
def tg_page():
    return _page("tg.html")


@app.route("/dedup")
def dedup_page():
    return _page("dedup.html")


@app.route("/settings")
def settings_page():
    return _page("settings.html")


QUIT = threading.Event()


@app.route("/api/app/quit", methods=["POST"])
def api_app_quit():
    """Выход из приложения (нужен в режиме «в браузере», где нет окна)."""
    QUIT.set()
    return jsonify({"ok": True})


@app.route("/api/core/status")
def api_core_status():
    """Состояние ядра 4.0: база, источники, очередь, расписания (для проверки и отладки)."""
    if core is None:
        return jsonify({"running": False})
    st = core.status()
    st["running"] = True
    return jsonify(st)


@app.route("/api/app/info")
def api_app_info():
    return jsonify({"name": APP_NAME, "version": VERSION, "data_dir": str(DATA_DIR),
                    "default_data_dir": str(paths.default_data_dir()),
                    "platform": sys.platform, "frozen": paths.is_frozen(),
                    "python": sys.version.split()[0]})


# ─── НАСТРОЙКИ: API ───────────────────────────────────────────────────────────

@app.route("/api/settings/public")
def api_settings_public():
    return jsonify(settings.public())


@app.route("/api/settings", methods=["GET"])
@require_admin
def api_settings_get():
    d = settings.for_editor()
    d["_builtin_sources"] = [s for s in get_sources() if not s.get("custom")]
    return jsonify(d)


@app.route("/api/settings", methods=["POST"])
@require_admin
def api_settings_save():
    patch = request.get_json(silent=True) or {}
    patch.pop("_admin_token", None)
    patch.pop("security", None)                        # пароль — отдельным методом
    before_tg = (settings.get("telegram", "api_id"), settings.get("telegram", "api_hash"))
    if "telegram" in patch and "channels" in patch["telegram"]:
        patch["telegram"]["channels"] = list(dict.fromkeys(
            normalize_channel(c) for c in patch["telegram"]["channels"] if normalize_channel(c)))
    new = settings.update(patch)
    if (new["telegram"]["api_id"], new["telegram"]["api_hash"]) != before_tg:
        tg.reset_client()
    if core is not None and ("collect" in patch or "telegram" in patch or "morning" in patch):
        core.apply_schedules()
    if "autostart" in (patch.get("general") or {}):
        from .system import set_autostart
        try:
            set_autostart(bool(new["general"]["autostart"]))
        except Exception as e:                                                   # noqa: BLE001
            return jsonify({"ok": False, "error": f"автозапуск не настроен: {e}"}), 500
    return jsonify({"ok": True, "settings": settings.for_editor()})


@app.route("/api/settings/password", methods=["POST"])
@require_admin
def api_settings_password():
    d = request.get_json(silent=True) or {}
    new = d.get("password") or ""
    if new and len(new) < 4:
        return jsonify({"ok": False, "error": "Пароль слишком короткий (минимум 4 символа)."}), 400
    settings.set_password(new)
    _admin_tokens.clear()
    token = ""
    if new:
        token = secrets.token_hex(16)
        _admin_tokens.add(token)
    return jsonify({"ok": True, "protected": bool(new), "token": token})


# ─── ИСТОЧНИКИ: API (управление — только из Настроек) ────────────────────────

@app.route("/api/sources")
def api_sources():
    return jsonify(get_sources())


@app.route("/api/sources/add", methods=["POST"])
@require_admin
def api_sources_add():
    d = request.get_json(silent=True) or {}
    name, url = (d.get("name") or "").strip(), (d.get("url") or "").strip()
    if not name or not url:
        return jsonify({"error": "укажите название и URL"}), 400
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "URL должен начинаться с http:// или https://"}), 400
    if any(s["url"] == url for s in get_sources()):
        return jsonify({"error": "источник с таким URL уже есть"}), 400
    src = {"id": "custom_" + uuid.uuid4().hex[:8], "name": name, "url": url, "type": "rss",
           "category": (d.get("category") or "Свои").strip() or "Свои",
           "region": (d.get("region") or "—").strip() or "—", "enabled": True, "custom": True}
    settings.update({"sources": {"custom": (settings.get("sources", "custom") or []) + [src]}})
    return jsonify(src)


@app.route("/api/sources/update", methods=["POST"])
@require_admin
def api_sources_update():
    """Свой источник — правка полей; встроенный — только «включён по умолчанию»."""
    d = request.get_json(silent=True) or {}
    sid = d.get("id")
    custom = settings.get("sources", "custom") or []
    for s in custom:
        if s["id"] == sid:
            for k in ("name", "url", "category", "region"):
                if k in d and str(d[k]).strip():
                    s[k] = str(d[k]).strip()
            if "enabled" in d:
                s["enabled"] = bool(d["enabled"])
            settings.update({"sources": {"custom": custom}})
            return jsonify({"ok": True, "source": s})
    if any(s["id"] == sid for s in SOURCES) and "enabled" in d:
        ov = settings.get("sources", "overrides") or {}
        ov[sid] = bool(d["enabled"])
        settings.update({"sources": {"overrides": ov}})
        return jsonify({"ok": True})
    return jsonify({"error": "источник не найден"}), 404


@app.route("/api/sources/delete", methods=["POST"])
@require_admin
def api_sources_delete():
    sid = (request.get_json(silent=True) or {}).get("id")
    custom = settings.get("sources", "custom") or []
    left = [s for s in custom if s["id"] != sid]
    if len(left) == len(custom):
        return jsonify({"error": "источник не найден или встроенный (его можно только выключить)"}), 400
    settings.update({"sources": {"custom": left}})
    return jsonify({"ok": True})


@app.route("/api/sources/test", methods=["POST"])
def api_sources_test():
    """Проверить ленту: сколько новостей отдаёт и как выглядит последняя."""
    d = request.get_json(silent=True) or {}
    url = (d.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "URL должен начинаться с http:// или https://"})
    try:
        f = SpaceNewsFetcher(timeout=int(settings.get("fetch", "timeout")), delay=0)
        arts = f.fetch_source({"id": "test", "name": d.get("name") or "test", "url": url})
        arts.sort(key=lambda a: a.get("published_at", ""), reverse=True)
        return jsonify({"ok": True, "count": len(arts),
                        "latest": arts[0] if arts else None})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]})


# ─── ПАРСИНГ САЙТОВ ───────────────────────────────────────────────────────────

def run_fetch_job(job_id: str, source_ids: list, date_from: str, date_to: str,
                  translate: bool, provider: str, deepl_key: str):
    job = jobs[job_id]
    job.update(status="running", log=[], articles=[], translated=False)
    selected = [s for s in get_sources() if s["id"] in source_ids]
    fetcher = SpaceNewsFetcher(timeout=int(settings.get("fetch", "timeout")),
                               delay=float(settings.get("fetch", "delay")))
    fetch_cap = 60 if translate else 100
    total = max(len(selected), 1)
    for i, source in enumerate(selected):
        job["progress"] = int((i / total) * fetch_cap)
        job["log"].append(f"Fetching: {source['name']}...")
        try:
            arts = fetcher.fetch_source(source, date_from, date_to)
            job["articles"].extend(arts)
            job["log"].append(f"  ✓ {source['name']}: {len(arts)} articles")
        except Exception as e:
            job["log"].append(f"  ✗ {source['name']}: {str(e)[:80]}")

    arts = job["articles"]
    job["log"].append(f"\nСобрано: {len(arts)} статей.")
    if translate and arts:
        _translate_job(job, arts, provider, deepl_key, fetch_cap)
    job.update(progress=100, status="done", finished_at=now_utc())
    job["name"] = job.get("name") or f"Выгрузка · {len(arts)} новостей"
    save_job(job_id)


def _translate_job(job: dict, arts: list, provider: str, deepl_key: str, start: int,
                   **kw) -> None:
    job["progress"] = start
    job["log"].append(f"🇷🇺 Перевод на русский ({'DeepL' if deepl_key else 'Google'})...")
    tr = make_translator(provider=provider, deepl_key=deepl_key or None,
                         log=lambda m: job["log"].append("  " + m))

    def prog(done, all_):
        job["progress"] = start + int((done / max(all_, 1)) * (98 - start))

    n = tr.translate_articles(arts, fields=("title", "summary"), progress=prog, **kw)
    if n and tr.available:
        job["translated"] = True
        job["log"].append(f"  ✓ Переведено уникальных строк: {n}")
    else:
        job["log"].append("  ⚠ Перевод не выполнен — показаны оригиналы.")


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    data = request.get_json(silent=True) or {}
    source_ids = data.get("sources") or [s["id"] for s in get_sources() if s.get("enabled")]
    provider, key = translation_params(data)
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "progress": 0, "log": [], "articles": []}
    threading.Thread(target=run_fetch_job, daemon=True, args=(
        job_id, source_ids, data.get("date_from", ""), data.get("date_to", ""),
        bool(data.get("translate")), provider, key)).start()
    return jsonify({"job_id": job_id})


@app.route("/api/job/<job_id>")
def api_job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify({"status": job["status"], "progress": job["progress"], "log": job["log"],
                    "count": len(job["articles"]), "translated": job.get("translated", False),
                    "finished_at": job.get("finished_at", "")})


@app.route("/api/job/<job_id>/articles")
def api_job_articles(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify({"articles": job["articles"], "translated": job.get("translated", False),
                    "status": job["status"]})


@app.route("/api/jobs/completed")
def api_jobs_completed():
    res = [{"job_id": k, "count": len(j.get("articles", [])), "finished_at": j.get("finished_at", ""),
            "translated": j.get("translated", False), "name": j.get("name", "")}
           for k, j in jobs.items() if j.get("status") == "done"]
    return jsonify(sorted(res, key=lambda x: x["finished_at"], reverse=True))


@app.route("/api/tg/completed")
def api_tg_completed():
    res = [{"job_id": k, "count": len(j.get("articles", [])), "finished_at": j.get("finished_at", ""),
            "translated": j.get("translated", False), "name": j.get("name", "")}
           for k, j in tg_jobs.items() if j.get("status") == "done"]
    return jsonify(sorted(res, key=lambda x: x["finished_at"], reverse=True))


# ─── ЭКСПОРТ ──────────────────────────────────────────────────────────────────

def _export_response(articles, fmt: str, lang: str, base: str):
    fmt = (fmt or "csv").lower()
    suffix = "_ru" if lang == "ru" else ""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if fmt == "xlsx":
        return Response(articles_to_xlsx(articles, lang=lang),
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{base}{suffix}_{stamp}.xlsx"'})
    if fmt in ("md", "markdown"):
        return Response(articles_to_markdown(articles, lang=lang), mimetype="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{base}{suffix}_{stamp}.md"'})
    return Response(articles_to_csv(articles, lang=lang), mimetype="text/csv; charset=utf-8-sig",
                    headers={"Content-Disposition": f'attachment; filename="{base}{suffix}_{stamp}.csv"'})


def _by_date(arts):
    return sorted(arts, key=lambda x: x.get("published_at", ""), reverse=True)


@app.route("/api/job/<job_id>/export")
@app.route("/api/job/<job_id>/csv")
def api_job_export(job_id: str):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "not ready"}), 400
    return _export_response(_by_date(job["articles"]), request.args.get("fmt", "csv"),
                            request.args.get("lang", "ru"), "space_news")


@app.route("/api/dedup/<dedup_id>/export")
@app.route("/api/dedup/<dedup_id>/csv")
def api_dedup_export(dedup_id: str):
    job = dedup_jobs.get(dedup_id)
    if not job or job.get("status") != "done":
        return jsonify({"error": "not ready"}), 400
    which = request.args.get("which", "kept")
    arts = job["result"]["removed"] if which == "removed" else job["result"]["kept"]
    base = "space_news_duplicates" if which == "removed" else "space_news_deduped"
    return _export_response(arts, request.args.get("fmt", "csv"), request.args.get("lang", "ru"), base)


@app.route("/api/tg/job/<tg_id>/export")
def api_tg_job_export(tg_id: str):
    job = tg_jobs.get(tg_id)
    if not job or job.get("status") != "done":
        return jsonify({"error": "not ready"}), 400
    return _export_response(_by_date(job.get("articles", [])), request.args.get("fmt", "csv"),
                            request.args.get("lang", "ru"), "tg_news")


# ─── НЕДЕЛЬНАЯ БАЗА (Пн–Вс) ───────────────────────────────────────────────────

def _week_key_for(d: date) -> str:
    return (d - timedelta(days=d.weekday())).isoformat()


def _week_label(key: str) -> str:
    try:
        monday = date.fromisoformat(key)
    except ValueError:
        return key
    return f"{monday.strftime('%d.%m')}–{(monday + timedelta(days=6)).strftime('%d.%m.%Y')}"


def _week_paths(key: str):
    folder = WEEKS_DIR / key
    return folder, folder / "articles.json", folder / f"{key}.csv"


def _article_key(a: dict) -> str:
    u = (a.get("url") or "").strip()
    if u:
        return "u:" + u
    return "t:" + "|".join([a.get("source_name", ""), a.get("title", ""), a.get("published_at", "")])


def _load_week(key: str) -> list:
    _, jp, _ = _week_paths(key)
    if jp.exists():
        try:
            return json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_week(key: str, articles: list) -> None:
    folder, jp, cp = _week_paths(key)
    folder.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(articles, ensure_ascii=False), encoding="utf-8")
    try:
        with open(cp, "w", encoding="utf-8", newline="") as f:
            f.write(articles_to_csv(articles, lang="orig"))
    except Exception:
        pass


def _accumulate_week(key: str, new_articles: list, source_kind: str) -> tuple:
    pool = _load_week(key)
    index = {_article_key(a): i for i, a in enumerate(pool)}
    kind = "tg" if source_kind == "tg" else "parser"
    added = updated = 0
    for a in new_articles:
        a = dict(a)
        a["set_kind"] = kind
        a.setdefault("set_label", "Telegram" if kind == "tg" else "Сайты")
        k = _article_key(a)
        if k in index:
            pool[index[k]] = a
            updated += 1
        else:
            index[k] = len(pool)
            pool.append(a)
            added += 1
    _save_week(key, pool)
    return added, updated, len(pool)


@app.route("/api/week/add", methods=["POST"])
def api_week_add():
    d = request.get_json(silent=True) or {}
    source = d.get("source")
    job = (tg_jobs if source == "tg" else jobs).get(d.get("job_id"))
    if not job or job.get("status") != "done":
        return jsonify({"error": "нет готовой выгрузки"}), 400
    arts = job.get("articles", [])
    if not arts:
        return jsonify({"error": "выгрузка пустая"}), 400
    by_week: dict = {}
    fallback = _week_key_for(date.today())
    for a in arts:
        try:
            key = _week_key_for(date.fromisoformat((a.get("published_at") or "")[:10]))
        except ValueError:
            key = fallback
        by_week.setdefault(key, []).append(a)
    out, ta, tu = [], 0, 0
    for key in sorted(by_week):
        added, updated, total = _accumulate_week(key, by_week[key], source)
        ta += added; tu += updated
        out.append({"week_key": key, "label": _week_label(key), "added": added,
                    "updated": updated, "total": total})
    return jsonify({"ok": True, "weeks": out, "added": ta, "updated": tu})


@app.route("/api/weeks")
def api_weeks():
    out = []
    if WEEKS_DIR.is_dir():
        for key in sorted(os.listdir(WEEKS_DIR), reverse=True):
            arts = _load_week(key)
            if not arts:
                continue
            n_tg = sum(1 for a in arts if a.get("set_kind") == "tg")
            out.append({"key": key, "label": _week_label(key), "count": len(arts),
                        "tg": n_tg, "sites": len(arts) - n_tg})
    return jsonify(out)


@app.route("/api/week/<key>/export")
def api_week_export(key: str):
    arts = _load_week(key)
    if not arts:
        return jsonify({"error": "пусто"}), 404
    return _export_response(_by_date(arts), request.args.get("fmt", "csv"),
                            request.args.get("lang", "orig"), "week_" + key)


@app.route("/api/week/<key>/delete", methods=["POST"])
@require_admin
def api_week_delete(key: str):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", key):
        return jsonify({"error": "неверный ключ недели"}), 400
    folder, _, _ = _week_paths(key)
    if not folder.is_dir():
        return jsonify({"error": "такой недели нет"}), 404
    shutil.rmtree(folder, ignore_errors=True)
    return jsonify({"ok": True, "deleted": key})


@app.route("/api/weeks/clear", methods=["POST"])
@require_admin
def api_weeks_clear():
    n = 0
    for key in os.listdir(WEEKS_DIR):
        shutil.rmtree(WEEKS_DIR / key, ignore_errors=True)
        n += 1
    return jsonify({"ok": True, "deleted_weeks": n})


# ─── ДЕДУПЛИКАТОР ─────────────────────────────────────────────────────────────

def run_dedup_job(dedup_id: str, params: dict):
    job = dedup_jobs[dedup_id]
    job.update(status="running", log=[], progress=10, translated=False)
    log = job["log"].append
    try:
        parser_articles = (jobs.get(params["job_id"]) or {}).get("articles") if params.get("job_id") else None
        tg_articles = (tg_jobs.get(params["tg_job_id"]) or {}).get("articles") if params.get("tg_job_id") else None
        file_groups = [{"label": uploads_store[u]["label"], "articles": uploads_store[u]["articles"]}
                       for u in params.get("upload_ids", []) if u in uploads_store]
        reference = []
        for wk in params.get("week_keys", []) or []:
            wa = _load_week(wk)
            reference.extend(wa)
            log(f"Эталон: неделя {_week_label(wk)} ({len(wa)} новостей).")
        job["progress"] = 30
        dd = settings.get("dedup")
        result = run_deduplication(
            parser_articles=parser_articles, tg_articles=tg_articles, file_groups=file_groups,
            reference_articles=reference or None, reference_label="Недельная база",
            threshold=float(params.get("threshold", dd["threshold"])),
            cross_compare=bool(params.get("cross_compare", dd["cross_compare"])),
            prefer_file_as_base=bool(params.get("prefer_file_as_base", dd["prefer_file_as_base"])),
            model_name=DEFAULT_MODEL, engine=dd.get("engine", "auto"), log=log)
        if params.get("translate"):
            provider, key = translation_params(params)
            _translate_job(job, result["kept"] + result["removed"], provider, key, 70,
                           include_duplicate_of=True)
        job.update(result=result, progress=100, status="done", finished_at=now_utc())
        job["name"] = job.get("name") or f"Дедуп · {result['stats']['kept']}✓ / {result['stats']['removed']}⛔"
        save_dedup(dedup_id)
    except Exception as e:
        job.update(status="error", progress=100)
        log(f"✗ Ошибка: {str(e)[:200]}")


@app.route("/api/dedup/upload", methods=["POST"])
def api_dedup_upload():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "файл не получен"}), 400
    label = f"Файл: {file.filename}"
    try:
        articles = parse_csv_articles(file.read(), label)
    except Exception as e:
        return jsonify({"error": f"не удалось разобрать CSV: {str(e)[:120]}"}), 400
    upload_id = str(uuid.uuid4())
    uploads_store[upload_id] = {"label": label, "filename": file.filename, "articles": articles}
    save_upload(upload_id)
    return jsonify({"upload_id": upload_id, "filename": file.filename, "count": len(articles),
                    "preview": [{"title": a["title"], "source_name": a["source_name"],
                                 "published_at": a["published_at"]} for a in articles[:5]]})


@app.route("/api/dedup/run", methods=["POST"])
def api_dedup_run():
    params = request.get_json(silent=True) or {}
    if not (params.get("job_id") or params.get("tg_job_id") or params.get("upload_ids")
            or params.get("week_keys")):
        return jsonify({"error": "нет данных: выберите неделю, выгрузку сайтов, Telegram и/или файл"}), 400
    dedup_id = str(uuid.uuid4())
    dedup_jobs[dedup_id] = {"status": "pending", "progress": 0, "log": [], "result": None}
    threading.Thread(target=run_dedup_job, args=(dedup_id, params), daemon=True).start()
    return jsonify({"dedup_id": dedup_id})


@app.route("/api/dedup/<dedup_id>")
def api_dedup_status(dedup_id: str):
    job = dedup_jobs.get(dedup_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    payload = {"status": job["status"], "progress": job["progress"], "log": job["log"],
               "translated": job.get("translated", False)}
    if job["status"] == "done" and job.get("result"):
        payload["stats"] = job["result"]["stats"]
    return jsonify(payload)


@app.route("/api/dedup/<dedup_id>/result")
def api_dedup_result(dedup_id: str):
    job = dedup_jobs.get(dedup_id)
    if not job or job.get("status") != "done":
        return jsonify({"error": "not ready"}), 400
    r = job["result"]
    return jsonify({"kept": r["kept"], "removed": r["removed"], "stats": r["stats"],
                    "translated": job.get("translated", False)})


@app.route("/api/dedup/engine")
def api_dedup_engine():
    t = tasks.get("model")
    return jsonify({"available": deduplicator.neural_available(),
                    "ready": deduplicator.neural_model_ready(),
                    "engine": settings.get("dedup", "engine"),
                    "task": {k: t[k] for k in ("status", "log")} if t else None})


@app.route("/api/dedup/engine/download", methods=["POST"])
@require_admin
def api_dedup_engine_download():
    t = tasks.get("model")
    if t and t["status"] == "running":
        return jsonify({"ok": True, "status": "running"})
    t = tasks["model"] = {"status": "running", "log": []}

    def work():
        try:
            deduplicator.download_neural_model(log=t["log"].append)
            t["status"] = "done"
        except Exception as e:
            t["log"].append(f"✗ {str(e)[:200]}")
            t["status"] = "error"
    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True, "status": "running"})


# ─── ИСТОРИЯ ──────────────────────────────────────────────────────────────────

@app.route("/api/history")
def api_history():
    items = []
    for jid, j in jobs.items():
        if j.get("status") == "done":
            items.append({"id": jid, "kind": "parser", "name": j.get("name") or "Выгрузка",
                          "count": len(j.get("articles", [])), "finished_at": j.get("finished_at", ""),
                          "translated": j.get("translated", False)})
    for did, j in dedup_jobs.items():
        if j.get("status") == "done" and j.get("result"):
            st = j["result"]["stats"]
            items.append({"id": did, "kind": "dedup", "name": j.get("name") or "Дедупликация",
                          "count": st.get("kept", 0), "removed": st.get("removed", 0),
                          "finished_at": j.get("finished_at", ""), "translated": j.get("translated", False)})
    for tid, j in tg_jobs.items():
        if j.get("status") == "done":
            items.append({"id": tid, "kind": "tg", "name": j.get("name") or "Telegram",
                          "count": len(j.get("articles", [])), "finished_at": j.get("finished_at", ""),
                          "translated": j.get("translated", False)})
    return jsonify(sorted(items, key=lambda x: x["finished_at"], reverse=True))


@app.route("/api/history/rename", methods=["POST"])
def api_history_rename():
    d = request.get_json(silent=True) or {}
    store, _, saver = _stores().get(d.get("kind"), _stores()["parser"])
    job = store.get(d.get("id"))
    if not job:
        return jsonify({"error": "not found"}), 404
    job["name"] = (d.get("name") or "").strip() or job.get("name", "")
    saver(d.get("id"))
    return jsonify({"ok": True, "name": job["name"]})


@app.route("/api/history/delete", methods=["POST"])
def api_history_delete():
    d = request.get_json(silent=True) or {}
    return jsonify({"ok": delete_history_item(d.get("kind"), d.get("id"))})


@app.route("/api/history/clear", methods=["POST"])
@require_admin
def api_history_clear():
    n = 0
    for kind, (store, folder, _) in _stores().items():
        for k in list(store):
            if delete_history_item(kind, k):
                n += 1
    return jsonify({"ok": True, "deleted": n})


# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def _tg_fmt_date(raw: str) -> str:
    return (raw or "").strip().replace("T", " ")[:16]


def _tg_post_to_article(row: dict) -> dict:
    text = (row.get("text") or "").strip()
    first = text.split("\n", 1)[0].strip() if text else ""
    title = (first[:117] + "…") if len(first) > 118 else first
    channel = (row.get("channel") or "").strip()
    return {"published_at": _tg_fmt_date(row.get("date", "")),
            "source_name": ("@" + channel) if channel and not channel.startswith("@") else channel,
            "title": title or "(без текста)", "summary": text, "url": row.get("link", "")}


def _item_to_tg_article(r: dict) -> dict:
    from .services.export import local_dt
    d = local_dt(r.get("published_at"))
    return {"published_at": d.strftime("%Y-%m-%d %H:%M") if d else "",
            "source_name": r.get("source_name") or "", "title": r.get("title") or "(без текста)",
            "summary": r.get("body") or r.get("summary") or "", "url": r.get("url") or ""}


def run_tg_job(tg_id: str, params: dict):
    job = tg_jobs[tg_id]
    job.update(status="running", log=[], progress=10, articles=[], translated=False)
    translate = bool(params.get("translate"))
    try:
        job["log"].append("Чтение базы Telegram...")
        rows = core.query_items("telegram", params.get("date_from", ""), params.get("date_to", ""),
                                params.get("channels", []) or [])
        arts = [_item_to_tg_article(r) for r in rows]
        job["articles"] = arts
        job["progress"] = 60 if translate else 100
        job["log"].append(f"Найдено постов: {len(arts)}.")
        if translate and arts:
            provider, key = translation_params(params)
            _translate_job(job, arts, provider, key, 60)
        job.update(progress=100, status="done", finished_at=now_utc())
        job["name"] = job.get("name") or f"Telegram · {len(arts)} постов"
        save_tg_job(tg_id)
    except Exception as e:
        job.update(status="error", progress=100)
        job["log"].append(f"✗ Ошибка: {str(e)[:200]}")


@app.route("/api/tg/config")
def api_tg_get_config():
    return jsonify(core.tg_channels())


@app.route("/api/tg/channels/add", methods=["POST"])
@require_admin
def api_tg_channel_add():
    ch = normalize_channel((request.get_json(silent=True) or {}).get("channel", ""))
    if not ch:
        return jsonify({"error": "Укажите канал (@имя или ссылку t.me)"}), 400
    src = core.sources.ensure_telegram(ch)
    if not src.enabled:
        core.sources.update(src.id, enabled=True)
    core.collector.enqueue_source(src.id, priority=5)          # сразу собрать новый канал
    return jsonify({"ok": True, "channel": ch, **core.tg_channels()})


@app.route("/api/tg/channels/delete", methods=["POST"])
@require_admin
def api_tg_channel_delete():
    ch = normalize_channel((request.get_json(silent=True) or {}).get("channel", "")).lower()
    src = core.sources.by_key("tg:" + ch)
    if src:
        core.sources.delete(src.id)          # с собранными постами канал выключается, посты остаются
    return jsonify({"ok": True, **core.tg_channels()})


@app.route("/api/tg/status")
def api_tg_status():
    st = tg.status(check_auth=request.args.get("auth", "1") != "0")
    st["db"] = core.tg_stats()
    st["auto_collect"] = bool(settings.get("collect", "telegram_auto"))
    health = core.sources.health("telegram")
    oks = [h["last_ok_at"] for h in health if h["last_ok_at"]]
    if oks:
        from .services.export import local_dt
        st["last_refresh"] = local_dt(max(oks)).strftime("%Y-%m-%d %H:%M")
    errs = sorted((h for h in health if h["last_error"]), key=lambda h: h["last_attempt_at"] or "")
    st["last_error"] = errs[-1]["last_error"] if errs else ""
    t = tasks.get("tg_refresh")
    if t:
        summ = core.jobs_summary(t["ids"])
        st["refresh_task"] = {"id": t["id"], "status": summ["status"]}
        st["busy"] = summ["status"] == "running"
    else:
        st["refresh_task"] = None
    return jsonify(st)


@app.route("/api/tg/refresh", methods=["POST"])
def api_tg_refresh():
    """Собрать свежие посты прямо сейчас (фоновая задача с логом)."""
    t = tasks.get("tg_refresh")
    if t and core.jobs_summary(t["ids"])["status"] == "running":
        return jsonify({"ok": True, "task_id": t["id"], "already": True})
    if not tg.configured():
        return jsonify({"ok": False, "error": "Не заданы API ID и API Hash (Настройки → Telegram)."})
    ids = core.refresh_kind("telegram")
    if not ids:
        return jsonify({"ok": False, "error": "Нет каналов. Добавьте их в Настройках → Telegram."})
    t = tasks["tg_refresh"] = {"id": uuid.uuid4().hex, "ids": ids}
    return jsonify({"ok": True, "task_id": t["id"]})


@app.route("/api/tg/refresh/status")
def api_tg_refresh_status():
    t = tasks.get("tg_refresh")
    if not t:
        return jsonify({"status": "none"})
    return jsonify({"id": t["id"], **core.jobs_summary(t["ids"])})


@app.route("/api/tg/login/code", methods=["POST"])
@require_admin
def api_tg_login_code():
    return jsonify(tg.send_code((request.get_json(silent=True) or {}).get("phone", "")))


@app.route("/api/tg/login/verify", methods=["POST"])
@require_admin
def api_tg_login_verify():
    return jsonify(tg.submit_code((request.get_json(silent=True) or {}).get("code", "")))


@app.route("/api/tg/login/password", methods=["POST"])
@require_admin
def api_tg_login_password():
    return jsonify(tg.submit_password((request.get_json(silent=True) or {}).get("password", "")))


@app.route("/api/tg/logout", methods=["POST"])
@require_admin
def api_tg_logout():
    return jsonify(tg.logout())


@app.route("/api/tg/import_db", methods=["POST"])
@require_admin
def api_tg_import_db():
    p = ((request.get_json(silent=True) or {}).get("path") or "").strip().strip('"')
    try:
        return jsonify({"ok": True, "added": core.import_news_db(Path(p))})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Не удалось импортировать: {str(e)[:200]}"})


@app.route("/api/tg/fetch", methods=["POST"])
def api_tg_fetch():
    tg_id = str(uuid.uuid4())
    tg_jobs[tg_id] = {"status": "pending", "progress": 0, "log": [], "articles": []}
    threading.Thread(target=run_tg_job, args=(tg_id, request.get_json(silent=True) or {}),
                     daemon=True).start()
    return jsonify({"job_id": tg_id})


@app.route("/api/tg/job/<tg_id>")
def api_tg_job_status(tg_id: str):
    job = tg_jobs.get(tg_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify({"status": job["status"], "progress": job["progress"], "log": job["log"],
                    "count": len(job.get("articles", [])), "translated": job.get("translated", False),
                    "finished_at": job.get("finished_at", "")})


@app.route("/api/tg/job/<tg_id>/articles")
def api_tg_job_articles(tg_id: str):
    job = tg_jobs.get(tg_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify({"articles": job.get("articles", []), "translated": job.get("translated", False),
                    "status": job["status"]})


# ─── ВЫГРУЗКА ДЛЯ CHATGPT (ядро 4.0) ──────────────────────────────────────────

@app.route("/export")
def export_page():
    return _page("export.html", profile="space")


@app.route("/slk")
def slk_page():
    """Дайджест по РН сверхлёгкого класса: та же страница выгрузки, профиль slk."""
    return _page("export.html", profile="slk")


def _svc(profile=None):
    """Сервис выгрузки по профилю: space — общий дайджест, slk — РН сверхлёгкого класса."""
    return core.slk if profile == "slk" else core.exports


def _svc_for(eid: int):
    e = core.exports.get(eid) if core else None
    return _svc((e or {}).get("profile"))


def _need_core():
    if core is None:
        return jsonify({"ok": False, "error": "Ядро не запущено — см. журнал программы"}), 503
    return None


def _export_view(e: dict) -> dict:
    e = dict(e)
    for k in ("csv_file", "prompt_file", "result_file"):
        e[k.replace("_file", "_exists")] = bool(e.get(k)) and Path(e[k]).exists()
        e[k.replace("_file", "_name")] = Path(e[k]).name if e.get(k) else ""
    return e


@app.route("/api/export/prompt")
def api_export_prompt():
    from .services.export import default_prompt
    profile = "slk" if request.args.get("profile") == "slk" else "space"
    custom = (settings.get("slk" if profile == "slk" else "export", "prompt") or "").strip()
    return jsonify({"prompt": custom or default_prompt(profile), "is_default": not custom,
                    "default": default_prompt(profile)})


@app.route("/api/export/preview", methods=["POST"])
def api_export_preview():
    if (r := _need_core()):
        return r
    d = request.get_json(silent=True) or {}
    svc = _svc(d.get("profile"))
    try:
        p = svc.preview(d.get("mode") or ("window" if svc.slk else "since_last"), d.get("date_from", ""),
                        d.get("date_to", ""), tuple(d.get("kinds") or ("rss", "telegram")))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)})
    if p.get("last_export"):
        p["last_export"] = _export_view(p["last_export"])
    return jsonify({"ok": True, **p})


@app.route("/api/export/prepare", methods=["POST"])
def api_export_prepare():
    if (r := _need_core()):
        return r
    d = request.get_json(silent=True) or {}
    payload = {k: d.get(k) for k in ("mode", "date_from", "date_to", "kinds", "dedupe", "profile") if k in d}
    job_id = core.queue.enqueue("export_prepare", payload,
                                dedupe_key="export_prepare:" + ("slk" if d.get("profile") == "slk" else "space"),
                                priority=10, max_attempts=1)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/api/jobs/<int:job_id>")
def api_job_get(job_id: int):
    if (r := _need_core()):
        return r
    j = core.queue.get(job_id)
    if not j:
        return jsonify({"error": "not found"}), 404
    return jsonify({k: j.get(k) for k in ("id", "type", "status", "progress", "log", "result", "error")})


@app.route("/api/export/list")
def api_export_list():
    if (r := _need_core()):
        return r
    return jsonify([_export_view(e) for e in _svc(request.args.get("profile")).list(50)])


@app.route("/api/export/<int:eid>")
def api_export_get(eid: int):
    e = core.exports.get(eid) if core else None
    if not e:
        return jsonify({"error": "not found"}), 404
    prompt = ""
    if e.get("prompt_file") and Path(e["prompt_file"]).exists():
        prompt = Path(e["prompt_file"]).read_text(encoding="utf-8")
    return jsonify({**_export_view(e), "prompt": prompt})


@app.route("/api/export/<int:eid>/review")
def api_export_review(eid: int):
    if (r := _need_core()):
        return r
    if not core.exports.get(eid):
        return jsonify({"ok": False, "error": "выгрузка не найдена"}), 404
    return jsonify({"ok": True, **_svc_for(eid).review(eid)})


@app.route("/api/export/<int:eid>/item", methods=["POST"])
def api_export_item(eid: int):
    """Правка выгрузки: {item_id, action: separate|restore|exclude|include} → CSV пересобирается."""
    if (r := _need_core()):
        return r
    d = request.get_json(silent=True) or {}
    try:
        review = _svc_for(eid).change(eid, int(d.get("item_id") or 0), str(d.get("action") or ""))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, **review, "export": _export_view(core.exports.get(eid))})


# ─── подбор порога дедупликации ──────────────────────────────────────────────
@app.route("/api/calibrate/pairs")
def api_calibrate_pairs():
    if (r := _need_core()):
        return r
    try:
        return jsonify({"ok": True, **core.calibrator.pairs(n=min(40, max(5, request.args.get("n", 20, type=int))))})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/calibrate/label", methods=["POST"])
def api_calibrate_label():
    if (r := _need_core()):
        return r
    d = request.get_json(silent=True) or {}
    try:
        res = core.calibrator.label(int(d["a"]), int(d["b"]), bool(d["same"]), float(d["similarity"]), str(d["backend"]))
    except (KeyError, ValueError, TypeError):
        return jsonify({"ok": False, "error": "неполный ответ"}), 400
    return jsonify({"ok": True, **res})


@app.route("/api/calibrate/apply", methods=["POST"])
def api_calibrate_apply():
    if (r := _need_core()):
        return r
    t = core.calibrator.apply((request.get_json(silent=True) or {}).get("threshold", 0.82))
    return jsonify({"ok": True, "threshold": t})


@app.route("/api/calibrate/reset", methods=["POST"])
def api_calibrate_reset():
    if (r := _need_core()):
        return r
    return jsonify({"ok": True, "removed": core.calibrator.reset((request.get_json(silent=True) or {}).get("backend"))})


# ─── утренняя выгрузка ───────────────────────────────────────────────────────
@app.route("/api/morning/status")
def api_morning_status():
    if (r := _need_core()):
        return r
    from .system import autostart_enabled
    st = core.morning_status()
    try:
        st["autostart"] = autostart_enabled()
    except Exception:                                                            # noqa: BLE001
        st["autostart"] = None
    return jsonify({"ok": True, **st})


@app.route("/api/morning/run", methods=["POST"])
def api_morning_run():
    """Выполнить утреннюю выгрузку сейчас (проверка настроек)."""
    if (r := _need_core()):
        return r
    jid = core.queue.enqueue("morning_export", {}, dedupe_key="schedule:morning_export", priority=9, max_attempts=1)
    return jsonify({"ok": True, "job_id": jid})


# ─── полный текст статей ─────────────────────────────────────────────────────
@app.route("/api/fulltext/stats")
def api_fulltext_stats():
    if (r := _need_core()):
        return r
    return jsonify(core.fulltext.stats())


@app.route("/api/fulltext/backfill", methods=["POST"])
def api_fulltext_backfill():
    if (r := _need_core()):
        return r
    days = min(30, max(1, int((request.get_json(silent=True) or {}).get("days") or 7)))
    jid = core.queue.enqueue("fulltext", {"days": days}, dedupe_key="fulltext:backfill", priority=5, max_attempts=1)
    return jsonify({"ok": True, "job_id": jid})


# ─── фильтр мусора ───────────────────────────────────────────────────────────
@app.route("/api/filter/config")
def api_filter_config():
    from .services.filters import DEFAULT_STOP, DEFAULT_TOPIC
    f = settings.get("filter") or {}
    return jsonify({"stop": f.get("stop") or DEFAULT_STOP, "topic": f.get("topic") or DEFAULT_TOPIC,
                    "stop_default": not f.get("stop"), "topic_default": not f.get("topic"),
                    "enabled": bool(f.get("enabled", True))})


@app.route("/api/filter/sources")
def api_filter_sources():
    if (r := _need_core()):
        return r
    return jsonify({"ok": True, "sources": core.exports.filter.source_stats()})


@app.route("/api/filter/suggest")
def api_filter_suggest():
    if (r := _need_core()):
        return r
    eid = request.args.get("export_id", type=int)
    return jsonify({"ok": True, **core.exports.filter.suggestions(eid)})


def _refilter_reply(eid, extra: dict):
    """После нового правила — сразу почистить открытую выгрузку."""
    out = {"ok": True, **extra}
    if eid and core.exports.get(eid):
        svc = _svc_for(eid)
        try:
            out["refiltered"] = svc.refilter(eid)
        except ValueError as e:
            out["warning"] = str(e)
        out["review"] = svc.review(eid)
        out["export"] = _export_view(core.exports.get(eid))
    return jsonify(out)


@app.route("/api/filter/stop", methods=["POST"])
def api_filter_stop():
    if (r := _need_core()):
        return r
    d = request.get_json(silent=True) or {}
    try:
        core.exports.filter.add_stop(str(d.get("word") or ""))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return _refilter_reply(d.get("export_id"), {})


@app.route("/api/filter/source", methods=["POST"])
def api_filter_source():
    """{ids: [...], space_only: bool, export_id?} — «только про космос» для источников."""
    if (r := _need_core()):
        return r
    d = request.get_json(silent=True) or {}
    ids = [int(x) for x in (d.get("ids") or []) if str(x).isdigit()]
    for sid in ids:
        try:
            core.sources.update(sid, space_only=bool(d.get("space_only")))
        except ValueError:
            pass
    return _refilter_reply(d.get("export_id") if d.get("space_only") else None, {"updated": len(ids)})


@app.route("/api/export/<int:eid>/collect", methods=["POST"])
def api_export_collect(eid: int):
    path = ((request.get_json(silent=True) or {}).get("path") or "").strip() or None
    try:
        return jsonify({"ok": True, "export": _export_view(core.exports.attach_result(eid, path))})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/export/<int:eid>/open", methods=["POST"])
def api_export_open(eid: int):
    e = core.exports.get(eid) if core else None
    if not e:
        return jsonify({"ok": False, "error": "выгрузка не найдена"})
    target = (request.get_json(silent=True) or {}).get("what", "folder")
    path = Path(e["result_file"] if target == "result" and e.get("result_file") else e["folder"])
    try:
        if target == "result" and path.is_file():
            paths.open_in_file_manager(path)         # откроет DOCX в Word / Pages
        else:
            paths.open_in_file_manager(path if path.is_dir() else path.parent)
        return jsonify({"ok": True})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)[:200]})


@app.route("/api/export/<int:eid>/file/<what>")
def api_export_file(eid: int, what: str):
    e = core.exports.get(eid) if core else None
    key = {"csv": "csv_file", "prompt": "prompt_file", "result": "result_file"}.get(what)
    if not e or not key or not e.get(key) or not Path(e[key]).exists():
        return jsonify({"error": "not found"}), 404
    return send_file(e[key], as_attachment=True, download_name=Path(e[key]).name)


@app.route("/api/clipboard", methods=["POST"])
def api_clipboard():
    text = (request.get_json(silent=True) or {}).get("text", "")
    return jsonify({"ok": paths.copy_to_clipboard(text)})


@app.route("/api/chatgpt/open", methods=["POST"])
def api_chatgpt_open():
    """Открыть ChatGPT в браузере (режим «в браузере» или без окна программы)."""
    import webbrowser
    webbrowser.open(settings.get("export", "chatgpt_url") or "https://chatgpt.com/")
    return jsonify({"ok": True})


@app.route("/api/collect/status")
def api_collect_status():
    if (r := _need_core()):
        return r
    from .services.export import local_dt
    out = {}
    for kind in ("rss", "telegram"):
        h = core.sources.health(kind)
        oks = [x["last_ok_at"] for x in h if x["last_ok_at"]]
        last = local_dt(max(oks)) if oks else None
        out[kind] = {
            "sources": sum(1 for x in h if x["enabled"]),
            "problems": [x["name"] for x in h if x["enabled"] and x["problem"]],
            "last_ok": last.strftime("%d.%m %H:%M") if last else "",
            "new_24h": core.db.scalar(
                "SELECT COUNT(*) FROM items i JOIN sources s ON s.id=i.source_id WHERE s.kind=? "
                "AND i.origin='collect' AND i.fetched_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now','-1 day')",
                (kind,), 0),
            "auto": bool(settings.get("collect", "sites_auto" if kind == "rss" else "telegram_auto")),
        }
    out["active_jobs"] = core.db.scalar(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running') "
        "AND type IN ('collect_source','collect_telegram')", default=0)
    out["telegram_configured"] = tg.configured()
    return jsonify(out)


@app.route("/api/collect/now", methods=["POST"])
def api_collect_now():
    if (r := _need_core()):
        return r
    kinds = (request.get_json(silent=True) or {}).get("kinds") or ["rss", "telegram"]
    ids = []
    for k in kinds:
        if k == "telegram" and not tg.configured():
            continue
        ids += core.refresh_kind(k)
    tasks["collect_now"] = {"id": uuid.uuid4().hex, "ids": ids}
    return jsonify({"ok": True, "jobs": len(ids)})


@app.route("/api/collect/now/status")
def api_collect_now_status():
    t = tasks.get("collect_now")
    if not t or core is None:
        return jsonify({"status": "none"})
    s = core.jobs_summary(t["ids"])
    s["log"] = s["log"][-60:]
    return jsonify(s)


# ─── СЛК: словари, источники, перенос старого парсера ────────────────────────

@app.route("/api/slk/config")
def api_slk_config():
    from .services.slk import DEFAULT_MILITARY, DEFAULT_NAMES, DEFAULT_ROCKET
    c = settings.get("slk") or {}
    out = {}
    for k, default in (("names", DEFAULT_NAMES), ("rocket", DEFAULT_ROCKET), ("military", DEFAULT_MILITARY)):
        out[k] = (c.get(k) or "").strip() or default
        out[k + "_default"] = not (c.get(k) or "").strip()
    return jsonify(out)


@app.route("/api/slk/sources")
def api_slk_sources():
    """Источники СЛК со «здоровьем»: работает ли, сколько новостей, сколько без даты."""
    if (r := _need_core()):
        return r
    from .services.export import local_dt
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    counts = {r["source_id"]: r for r in core.db.query("""
        SELECT source_id, COUNT(*) AS n30,
               SUM(date_status = 'none') AS undated, SUM(date_status = 'baseline') AS archive,
               SUM(date_status = 'page') AS page_dated
        FROM items WHERE fetched_at >= ? GROUP BY source_id""", (since,))}
    out = []
    for h in core.sources.health():
        cfg = json.loads(h.get("config") or "{}")
        if h.get("scope") != "slk" and not cfg.get("slk_trusted"):
            continue
        c = counts.get(h["id"], {})
        last_ok = local_dt(h.get("last_ok_at"))
        out.append({"id": h["id"], "name": h["name"], "url": h["url"], "kind": h["kind"],
                    "category": h["category"], "enabled": bool(h["enabled"]),
                    "html": bool(cfg.get("html")), "trusted": bool(cfg.get("slk_trusted")),
                    "general": bool(cfg.get("general")),
                    "error": h.get("last_error") or "", "problem": bool(h.get("problem")),
                    "last_ok": last_ok.strftime("%d.%m %H:%M") if last_ok else "",
                    "n30": int(c.get("n30") or 0), "undated": int(c.get("undated") or 0),
                    "archive": int(c.get("archive") or 0), "page_dated": int(c.get("page_dated") or 0)})
    return jsonify({"ok": True, "sources": out})


@app.route("/api/slk/source", methods=["POST"])
@require_admin
def api_slk_source():
    if (r := _need_core()):
        return r
    d = request.get_json(silent=True) or {}
    try:
        core.sources.update(int(d.get("id") or 0), enabled=bool(d.get("enabled")))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True})


@app.route("/api/slk/collect", methods=["POST"])
def api_slk_collect():
    """Собрать только источники СЛК (проверка после настройки или переноса)."""
    if (r := _need_core()):
        return r
    ids = [core.collector.enqueue_source(s.id, priority=5) for s in core.sources.list(enabled=True)
           if s.scope == "slk" and s.url and (s.kind != "telegram" or tg.configured())]
    tasks["collect_now"] = {"id": uuid.uuid4().hex, "ids": ids}
    return jsonify({"ok": True, "jobs": len(ids)})


@app.route("/api/slk/import", methods=["POST"])
@require_admin
def api_slk_import():
    if (r := _need_core()):
        return r
    from .services.slk_import import import_slk
    folder = ((request.get_json(silent=True) or {}).get("path") or "").strip() or None
    try:
        return jsonify({"ok": True, **import_slk(core.sources, folder)})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)})


# ─── ДАННЫЕ: папка, резервная копия, импорт старой версии ────────────────────

def _dir_size(p: Path) -> int:
    total = 0
    for root, _d, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


@app.route("/api/data/info")
def api_data_info():
    return jsonify({
        "data_dir": str(DATA_DIR), "default_data_dir": str(paths.default_data_dir()),
        "size_mb": round(_dir_size(DATA_DIR) / 1024 / 1024, 1),
        "counts": {"parser": len(jobs), "dedup": len(dedup_jobs), "tg": len(tg_jobs),
                   "uploads": len(uploads_store),
                   "weeks": len([p for p in WEEKS_DIR.iterdir() if p.is_dir()]) if WEEKS_DIR.exists() else 0},
        "tg_db": core.tg_stats(),
        "core_db": str(core.db.path) if core else ""})


@app.route("/api/data/open", methods=["POST"])
def api_data_open():
    try:
        paths.open_in_file_manager(DATA_DIR)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]})


@app.route("/api/data/import_old", methods=["POST"])
@require_admin
def api_data_import_old():
    p = ((request.get_json(silent=True) or {}).get("path") or "").strip().strip('"')
    res = import_old_version(p, DATA_DIR, settings, tg)
    if res.get("ok"):
        load_history()
        if core is not None:                    # перенесённое — сразу в единую базу
            from .services.legacy_import import LegacyImporter
            from .sources import SOURCES as _BUILTIN
            rep_ = LegacyImporter(core.db, core.sources, DATA_DIR, settings, _BUILTIN).run()
            core.migrate_legacy_settings()
            core.apply_schedules()
            res["report"].append(f"Единая база: публикаций {rep_['items_total']}")
    return jsonify(res)


@app.route("/api/data/location", methods=["POST"])
@require_admin
def api_data_location():
    """Перенести папку данных. Копирует текущие данные, применяется после перезапуска."""
    d = request.get_json(silent=True) or {}
    new = (d.get("path") or "").strip().strip('"')
    if not new:
        paths.set_data_dir(None)
        return jsonify({"ok": True, "restart": True, "path": str(paths.default_data_dir())})
    target = Path(new).expanduser()
    try:
        target.mkdir(parents=True, exist_ok=True)
        if any(target.iterdir()) and not (target / "settings.json").exists():
            target = target / "SpaceDigest"
            target.mkdir(exist_ok=True)
        if target.resolve() != DATA_DIR.resolve() and not (target / "settings.json").exists():
            shutil.copytree(DATA_DIR, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("location.json"))
        paths.set_data_dir(str(target))
        return jsonify({"ok": True, "restart": True, "path": str(target)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]})


@app.route("/api/data/backup")
def api_data_backup():
    """ZIP: снимок базы, настройки, недельная база, история (без входа в Telegram и ChatGPT)."""
    from .services.maintenance import make_backup
    name = f"SpaceDigest_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    tmp = Path(tempfile.mkdtemp()) / name
    make_backup(DATA_DIR, tmp, core.db.backup if core is not None else None)
    return send_file(str(tmp), mimetype="application/zip", as_attachment=True, download_name=name)


@app.route("/api/data/restore", methods=["POST"])
def api_data_restore():
    """Загрузить резервную копию: применится при следующем запуске программы."""
    from .services.maintenance import schedule_restore
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "файл не выбран"}), 400
    tmp = Path(tempfile.mkdtemp()) / "restore.zip"
    f.save(tmp)
    try:
        info = schedule_restore(DATA_DIR, tmp)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, **info})


@app.route("/api/app/restart", methods=["POST"])
def api_app_restart():
    """Перезапуск: новый процесс дождётся завершения текущего и откроет окно заново."""
    import subprocess
    env = {**os.environ, "SPACEDIGEST_WAIT_PID": str(os.getpid())}
    frozen = getattr(sys, "frozen", False)
    args = [sys.executable] + ([] if frozen else [os.path.abspath(sys.argv[0])]) + sys.argv[1:]
    kw = {"creationflags": 0x00000008} if sys.platform == "win32" else {"start_new_session": True}
    subprocess.Popen(args, env=env, close_fds=True, **kw)
    QUIT.set()
    return jsonify({"ok": True})


# ─── обновления ──────────────────────────────────────────────────────────────
_update_cache: dict = {}


@app.route("/api/update/check")
def api_update_check():
    from .services.maintenance import check_update
    from . import VERSION
    repo = (settings.get("updates", "repo") or "").strip()
    if not repo:
        return jsonify({"ok": True, "configured": False, "current": VERSION})
    force = request.args.get("force") == "1"
    if not force and request.args.get("auto") == "1" and not settings.get("updates", "auto_check"):
        return jsonify({"ok": True, "configured": True, "current": VERSION, "skipped": True})
    c = _update_cache.get(repo)
    if c and not force and time.time() - c["at"] < 6 * 3600:
        return jsonify({"ok": True, "configured": True, **c["data"]})
    try:
        data = check_update(repo, VERSION)
    except Exception as e:                                                   # noqa: BLE001
        return jsonify({"ok": False, "configured": True, "current": VERSION,
                        "error": str(e)[:200] if isinstance(e, ValueError) else "нет связи с GitHub"})
    _update_cache[repo] = {"at": time.time(), "data": data}
    return jsonify({"ok": True, "configured": True, **data})


@app.route("/api/update/install", methods=["POST"])
def api_update_install():
    """Скачать установщик новой версии (в «Загрузки») и запустить его."""
    from .services.maintenance import download_installer, launch_installer
    repo = (settings.get("updates", "repo") or "").strip()
    c = _update_cache.get(repo)
    asset = (c or {}).get("data", {}).get("asset")
    if not asset:
        return jsonify({"ok": False, "error": "сначала проверьте обновления"}), 400
    if (tasks.get("update") or {}).get("status") == "running":
        return jsonify({"ok": True})
    st = tasks["update"] = {"status": "running", "progress": 0.0, "error": "", "file": ""}

    def work():
        try:
            path = download_installer(asset["url"], asset["name"], Path.home() / "Downloads",
                                      progress=lambda p: st.update(progress=round(p, 3)))
            st["file"] = str(path)
            launch_installer(path)
            st["status"] = "done"
            if sys.platform == "win32":                 # установщик заменит файлы программы
                threading.Timer(2.0, QUIT.set).start()
        except Exception as e:                                               # noqa: BLE001
            st.update(status="error", error=str(e)[:200])
    threading.Thread(target=work, daemon=True, name="update").start()
    return jsonify({"ok": True})


@app.route("/api/update/status")
def api_update_status():
    return jsonify(tasks.get("update") or {"status": "idle"})
