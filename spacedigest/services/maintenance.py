"""
Сохранность данных и обновления.

Резервная копия: снимок базы через SQLite backup API (согласованный даже во время сбора),
настройки, недельная база и история. Без входа в Telegram (*.session), моделей и служебных копий.

Восстановление выполняется при следующем запуске — пока программа работает, файлы базы открыты.
Текущие данные перед восстановлением откладываются в папку «_до_восстановления_<дата>».

Обновления: последний релиз GitHub; скачивается установщик для своей системы и запускается.
Папка данных лежит отдельно от программы, поэтому установка новой версии её не трогает.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

DB_NAME = "spacedigest.db"
PENDING = "restore_pending.zip"
SKIP_DIRS = {"models", "logs", "webview"}     # webview — вход в ChatGPT, в копию не кладём
SKIP_SUFFIX = (".session", ".session-journal", ".tmp", ".bak", "-wal", "-shm")
SKIP_FILES = {"location.json", "runtime.json", PENDING, DB_NAME}


# ─── резервная копия ─────────────────────────────────────────────────────────
def make_backup(data_dir: Path, target: Path, db_backup: Optional[Callable[[Path], Path]] = None) -> Path:
    """ZIP с данными. db_backup(path) — снимок открытой базы (Database.backup)."""
    data_dir = Path(data_dir)
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        snap = Path(tmp) / DB_NAME
        if db_backup:
            db_backup(snap)
        elif (data_dir / DB_NAME).exists():
            shutil.copy2(data_dir / DB_NAME, snap)
        if snap.exists():
            z.write(snap, DB_NAME)
        for root, dirs, files in os.walk(data_dir):
            rel_root = Path(root).relative_to(data_dir)
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith("_до_восстановления")]
            for f in files:
                if (rel_root == Path(".") and f in SKIP_FILES) or f.endswith(SKIP_SUFFIX):
                    continue
                full = Path(root) / f
                z.write(full, full.relative_to(data_dir))
        z.writestr("backup.json", json.dumps({"created": datetime.now().isoformat(timespec="seconds"),
                                              "app": "Space Digest"}, ensure_ascii=False))
    return target


def check_backup(path: Path) -> dict:
    """Проверить архив до восстановления: это наша копия и база в ней читается."""
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            bad = [n for n in names if n.startswith(("/", "\\")) or ".." in Path(n).parts]
            if bad:
                raise ValueError("архив содержит недопустимые пути")
            if DB_NAME not in names and "settings.json" not in names:
                raise ValueError("это не резервная копия Space Digest")
            meta = json.loads(z.read("backup.json")) if "backup.json" in names else {}
            return {"files": len(names), "has_db": DB_NAME in names, "created": meta.get("created", "")}
    except zipfile.BadZipFile:
        raise ValueError("файл повреждён или это не ZIP")


def schedule_restore(data_dir: Path, archive: Path) -> dict:
    info = check_backup(archive)
    shutil.copy2(archive, Path(data_dir) / PENDING)
    return info


def apply_pending_restore(data_dir: Path, log: Callable[[str], None] = print) -> Optional[Path]:
    """Вызывается при запуске до открытия базы. → папка, куда отложены прежние данные."""
    data_dir = Path(data_dir)
    pending = data_dir / PENDING
    if not pending.exists():
        return None
    try:
        check_backup(pending)
    except ValueError as e:
        log(f"Восстановление отменено: {e}")
        pending.rename(pending.with_suffix(".bad"))
        return None
    aside = data_dir / f"_до_восстановления_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    aside.mkdir()
    keep = {PENDING, "location.json", "models", "logs", "webview", aside.name}
    for p in list(data_dir.iterdir()):
        if p.name in keep or p.name.startswith("_до_восстановления") or p.suffix == ".session":
            continue
        shutil.move(str(p), aside / p.name)
    with zipfile.ZipFile(pending) as z:
        for n in z.namelist():
            if n == "backup.json":
                continue
            z.extract(n, data_dir)
    for sess in aside.rglob("*.session"):                     # вход в Telegram сохраняем
        dst = data_dir / sess.relative_to(aside)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sess, dst)
    pending.unlink()
    log(f"Данные восстановлены из резервной копии; прежние — в {aside.name}")
    return aside


# ─── обновления ──────────────────────────────────────────────────────────────
def parse_version(v: str) -> tuple:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in nums[:3]) + (0,) * (3 - len(nums[:3]))


def platform_asset(assets: list[dict], system: str = "", machine: str = "") -> Optional[dict]:
    """Выбрать установщик под систему: .exe для Windows, .dmg (Apple Silicon / Intel) для Mac."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    names = [(a, a.get("name", "")) for a in assets]
    if system == "Windows":
        return next((a for a, n in names if n.lower().endswith(".exe")), None)
    if system == "Darwin":
        dmgs = [(a, n) for a, n in names if n.lower().endswith(".dmg")]
        arm = machine in ("arm64", "aarch64")
        pref = [(a, n) for a, n in dmgs if (("apple" in n.lower() or "arm" in n.lower()) == arm)]
        return (pref or dmgs or [(None, "")])[0][0]
    return None


def check_update(repo: str, current: str, http_get=None) -> dict:
    """Последний релиз репозитория owner/name на GitHub."""
    repo = (repo or "").strip().strip("/")
    m = re.match(r"^(?:https?://github\.com/)?([\w.-]+/[\w.-]+?)(?:\.git)?$", repo)
    if not m:
        raise ValueError("укажите репозиторий в виде owner/name")
    if http_get is None:
        import requests
        http_get = lambda url: requests.get(url, timeout=15,                       # noqa: E731
                                            headers={"Accept": "application/vnd.github+json"})
    r = http_get(f"https://api.github.com/repos/{m.group(1)}/releases/latest")
    if getattr(r, "status_code", 200) == 404:
        raise ValueError("в репозитории ещё нет опубликованных версий")
    r.raise_for_status()
    rel = r.json()
    latest = rel.get("tag_name") or rel.get("name") or ""
    asset = platform_asset(rel.get("assets") or [])
    return {"current": current, "latest": latest.lstrip("v"),
            "available": parse_version(latest) > parse_version(current),
            "notes": (rel.get("body") or "")[:3000], "url": rel.get("html_url", ""),
            "asset": {"name": asset["name"], "url": asset["browser_download_url"], "size": asset.get("size", 0)}
            if asset else None}


def download_installer(url: str, name: str, target_dir: Path, progress=None, http_get=None) -> Path:
    if not re.match(r"^https://(github\.com|objects\.githubusercontent\.com|release-assets\.githubusercontent\.com)/", url):
        raise ValueError("установщик можно скачать только с GitHub")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / re.sub(r"[^\w.\-]", "_", name)
    if http_get is None:
        import requests
        http_get = lambda u: requests.get(u, timeout=60, stream=True)              # noqa: E731
    with http_get(url) as r:
        r.raise_for_status()
        total, done = int(r.headers.get("content-length") or 0), 0
        part = target.with_suffix(target.suffix + ".part")
        with open(part, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
        part.replace(target)
    return target


def launch_installer(path: Path) -> None:
    """Windows — запустить установщик (он сам закроет и обновит программу); Mac — открыть DMG."""
    if sys.platform == "win32":
        os.startfile(str(path))                                   # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", str(path)])
    else:
        raise ValueError("автоустановка доступна только на Windows и macOS")
