"""
Перенос настроек старого «Парсера СЛК» (3.x) в Space Digest.

Что переносится:
  * свои источники (data/custom_sources.json) — как источники СЛК (scope = slk);
  * исправленные адреса встроенных (data/source_overrides.json) — поверх списка СЛК.
Что не переносится и почему:
  * ключи и бюджет Gemini/GigaChat — работа с ChatGPT теперь ручная, ключи не нужны;
  * промпт — встроенный промпт СЛК обновлён (проверка дат, повторы); свой текст можно
    вставить в Настройки → СЛК, он сохранится поверх встроенного;
  * недельные выгрузки и история — у Space Digest своя история выгрузок в общей базе.

Папка старого парсера: Windows — %APPDATA%\\SLK Parser, macOS —
~/Library/Application Support/SLK Parser, Linux — ~/.local/share/slk-parser.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from .sources import SourceRepo


def default_dir() -> Optional[Path]:
    env = os.environ.get("SLK_HOME")
    cands = [Path(env).expanduser()] if env else []
    if sys.platform == "darwin":
        cands.append(Path.home() / "Library" / "Application Support" / "SLK Parser")
    elif os.name == "nt":
        cands.append(Path(os.environ.get("APPDATA") or Path.home()) / "SLK Parser")
    else:
        cands.append(Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "slk-parser")
    for c in cands:
        if c.is_dir():
            return c
    return None


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _find(root: Path, name: str) -> Optional[Path]:
    """Файл лежит в data/ (3.1) или прямо в папке (ранние версии и выбор папки data/ вручную)."""
    for p in (root / "data" / name, root / name):
        if p.is_file():
            return p
    return None


def import_slk(repo: SourceRepo, folder: Optional[str] = None) -> dict:
    root = Path(folder).expanduser() if folder else default_dir()
    if not root or not root.is_dir():
        raise ValueError("папка старого парсера СЛК не найдена — выберите её вручную "
                         "(Windows: %APPDATA%\\SLK Parser)")
    report = {"folder": str(root), "added": 0, "exists": 0, "urls_fixed": 0, "skipped": [], "notes": []}

    custom = _load(p) if (p := _find(root, "custom_sources.json")) else None
    for s in custom if isinstance(custom, list) else []:
        url, name = str(s.get("url") or "").strip(), str(s.get("name") or "").strip()
        if not url.startswith(("http://", "https://")) or not name:
            report["skipped"].append(name or url or "?")
            continue
        if repo.db.one("SELECT 1 FROM sources WHERE kind = 'rss' AND url = ?", (url,)):
            report["exists"] += 1
            continue
        cfg: dict = {}
        if (s.get("type") or "rss") == "html":
            cfg["html"] = True
        if s.get("item_selector"):
            cfg["item_selector"] = s["item_selector"]
        if s.get("filter") is False:
            cfg["slk_trusted"] = True
        else:
            cfg["fulltext"] = "match"
        key = "slk_custom_" + "".join(ch for ch in str(s.get("id") or name).lower() if ch.isalnum())[:40]
        if repo.by_key(key):
            key += "_" + str(abs(hash(url)) % 10000)
        repo._insert(key=key, kind="rss", name=name, url=url, category="СЛК · Свои",
                     region=str(s.get("region") or ""), enabled=bool(s.get("enabled", True)),
                     config=cfg, scope="slk")
        report["added"] += 1

    overrides = _load(p) if (p := _find(root, "source_overrides.json")) else None
    if not overrides and (p := _find(root, "sources_overrides.json")):
        overrides = _load(p)
    for sid, ov in (overrides or {}).items() if isinstance(overrides, dict) else []:
        if not isinstance(ov, dict) or not str(ov.get("url") or "").startswith(("http://", "https://")):
            continue
        src = repo.by_key("slk_" + sid)
        if not src or src.url == ov["url"]:
            continue
        cfg = dict(src.config)
        cfg["html"] = (ov.get("type") or "html") == "html"
        cfg["url_override"] = ov["url"]
        repo.db.execute("UPDATE sources SET url = ?, config = ? WHERE id = ?",
                        (ov["url"], json.dumps(cfg, ensure_ascii=False), src.id))
        repo.reset_state(src.id)
        report["urls_fixed"] += 1

    if _find(root, "gemini_config.json"):
        report["notes"].append("ключи ИИ (Gemini и др.) не переносятся: ChatGPT теперь используется вручную")
    prompts = _load(root / "prompts.json")
    if isinstance(prompts, (list, dict)) and prompts:
        report["notes"].append("промпты старого парсера не переносятся: встроенный промпт СЛК обновлён; "
                               "свой текст можно вставить в Настройки → СЛК")
    return report
