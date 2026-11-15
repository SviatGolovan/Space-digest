"""
Перенос данных из прежней версии («ВЕРСИЯ 2»: space_parser + tg_news_site).

Достаточно указать любую папку, внутри которой они лежат (например «ВЕРСИЯ 2»
или «ПАРСЕРЫ»). Переносится:
  • история выгрузок, дедупликаций, загруженных CSV, TG-сборов;
  • недельная база (с объединением, если неделя уже есть);
  • свои источники сайтов;
  • пароль на настройки (если в новой версии он ещё не задан);
  • Telegram: API ID/Hash из .env, список каналов, вход (tg_session.session),
    все посты из news.db.
Ничего в старой папке не изменяется.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def _find_dirs(root: Path, max_depth: int = 5):
    """Ищет папки space_parser (сайты) и tg_news_site (Telegram)."""
    parser_dirs, tg_dirs = [], []
    root = Path(root)
    for cur, dirs, files in os.walk(root):
        depth = len(Path(cur).relative_to(root).parts)
        # не лезем в виртуальные окружения и кэши
        dirs[:] = [d for d in dirs if d not in (".venv", "venv", "__pycache__", "node_modules",
                                                 "site-packages", ".git")]
        if depth > max_depth:
            dirs[:] = []
            continue
        fs = set(files)
        if "deduplicator.py" in fs or ("app.py" in fs and "data" in dirs) or "admin_config.json" in fs:
            parser_dirs.append(Path(cur))
        if "news.db" in fs or "tg_session.session" in fs or \
                ("app" in dirs and (Path(cur) / "app" / "tg_fetcher.py").exists()):
            tg_dirs.append(Path(cur))
    return parser_dirs, tg_dirs


def _read_env(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _copy_tree_skip_existing(src: Path, dst: Path) -> int:
    n = 0
    if not src.is_dir():
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.json"):
        t = dst / f.name
        if not t.exists():
            shutil.copy2(f, t)
            n += 1
    return n


def _article_key(a: dict) -> str:
    u = (a.get("url") or "").strip()
    if u:
        return "u:" + u
    return "t:" + "|".join([a.get("source_name", ""), a.get("title", ""), a.get("published_at", "")])


def _merge_weeks(src: Path, dst: Path) -> tuple[int, int]:
    """Возвращает (недель обработано, новостей добавлено)."""
    weeks = added = 0
    if not src.is_dir():
        return 0, 0
    for wk in sorted(p for p in src.iterdir() if p.is_dir()):
        sj = wk / "articles.json"
        if not sj.exists():
            continue
        try:
            new = json.loads(sj.read_text(encoding="utf-8"))
        except Exception:
            continue
        tdir = dst / wk.name
        tdir.mkdir(parents=True, exist_ok=True)
        tj = tdir / "articles.json"
        pool = []
        if tj.exists():
            try:
                pool = json.loads(tj.read_text(encoding="utf-8"))
            except Exception:
                pool = []
        keys = {_article_key(a) for a in pool}
        for a in new:
            k = _article_key(a)
            if k not in keys:
                keys.add(k)
                pool.append(a)
                added += 1
        tj.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
        try:
            from .exporters import articles_to_csv
            (tdir / f"{wk.name}.csv").write_text(articles_to_csv(pool, lang="orig"),
                                                 encoding="utf-8", newline="")
        except Exception:
            pass
        weeks += 1
    return weeks, added


def import_old_version(root: str, data_dir: Path, settings, tg_service) -> dict:
    root_p = Path(root).expanduser()
    if not root_p.is_dir():
        return {"ok": False, "error": f"Папка не найдена: {root}"}
    parser_dirs, tg_dirs = _find_dirs(root_p)
    report: list[str] = []
    if not parser_dirs and not tg_dirs:
        return {"ok": False, "error": "В этой папке не найдено ни space_parser, ни tg_news_site. "
                                      "Укажите папку «ВЕРСИЯ 2» (или ту, где они лежат)."}

    data_dir = Path(data_dir)
    # ── сайты / дедуп / недели ──
    for pdir in parser_dirs:
        d = pdir / "data"
        if d.is_dir():
            for sub in ("jobs", "dedup", "uploads", "tg"):
                n = _copy_tree_skip_existing(d / sub, data_dir / sub)
                if n:
                    report.append(f"История «{sub}»: перенесено {n} файлов")
            w, a = _merge_weeks(d / "weeks", data_dir / "weeks")
            if w:
                report.append(f"Недельная база: {w} недель, добавлено {a} новостей")
            cs = d / "custom_sources.json"
            if cs.exists():
                try:
                    old = json.loads(cs.read_text(encoding="utf-8"))
                    cur = settings.get("sources", "custom") or []
                    urls = {s.get("url") for s in cur}
                    added = [s for s in old if isinstance(s, dict) and s.get("url") not in urls]
                    if added:
                        settings.update({"sources": {"custom": cur + added}})
                        report.append(f"Свои источники: +{len(added)}")
                except Exception:
                    pass
        ac = pdir / "admin_config.json"
        if ac.exists() and not settings.password_set():
            try:
                pw = (json.loads(ac.read_text(encoding="utf-8")).get("password") or "").strip()
                if pw:
                    settings.set_password(pw)
                    report.append("Пароль на настройки перенесён из admin_config.json")
            except Exception:
                pass
        tc = pdir / "tg_config.json"
        if tc.exists():
            try:
                cfg = json.loads(tc.read_text(encoding="utf-8"))
                chans = list(dict.fromkeys((settings.get("telegram", "channels") or [])
                                           + [c for c in cfg.get("channels", []) if c]))
                settings.update({"telegram": {"channels": chans}})
                dbp = Path(cfg.get("db_path") or "")
                if dbp.name == "news.db" and dbp.exists() and dbp.parent not in tg_dirs:
                    tg_dirs.append(dbp.parent)
            except Exception:
                pass

    # ── Telegram ──
    session_imported = False
    for tdir in tg_dirs:
        env = _read_env(tdir / ".env")
        patch = {}
        if env.get("TG_API_ID") and not settings.get("telegram", "api_id"):
            patch["api_id"] = env["TG_API_ID"]
        if env.get("TG_API_HASH") and not settings.get("telegram", "api_hash"):
            patch["api_hash"] = env["TG_API_HASH"]
        if env.get("TG_CHANNELS"):
            extra = [c.strip() for c in env["TG_CHANNELS"].split(",") if c.strip()]
            patch["channels"] = list(dict.fromkeys((settings.get("telegram", "channels") or []) + extra))
        if patch:
            settings.update({"telegram": patch})
            if "api_id" in patch:
                report.append("Telegram: API ID и API Hash перенесены из .env")
        sess = tdir / "tg_session.session"
        target = tg_service.session_base.with_suffix(".session")
        if sess.exists() and not session_imported and not target.exists():
            tg_service.reset_client()
            shutil.copy2(sess, target)
            session_imported = True
            report.append("Telegram: вход (tg_session.session) перенесён — заново входить не нужно")
        db = tdir / "news.db"
        if db.exists():
            try:
                n = tg_service.import_db(db)
                report.append(f"Telegram: из news.db добавлено постов — {n}")
            except Exception as e:
                report.append(f"⚠ news.db не прочитана: {str(e)[:120]}")

    if not report:
        report.append("Нашёл старые папки, но переносить нечего (всё уже есть).")
    return {"ok": True, "report": report,
            "found": {"parser": [str(p) for p in parser_dirs], "tg": [str(p) for p in tg_dirs]}}
