"""
Где лежат файлы приложения.

* resource_dir() — шаблоны/статика (внутри установленного приложения или рядом с кодом).
* data_dir()     — данные пользователя: история, недельная база, Telegram, настройки.
    Windows : %APPDATA%\\SpaceDigest
    macOS   : ~/Library/Application Support/SpaceDigest
    Linux   : ~/.local/share/SpaceDigest
  Папку можно перенести в настройках — тогда в стандартной папке остаётся
  только location.json с новым путём.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import APP_ID


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "spacedigest"          # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def default_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / APP_ID


def _location_file() -> Path:
    return default_data_dir() / "location.json"


def data_dir() -> Path:
    """Текущая папка данных (учитывает перенос и переменную SPACEDIGEST_DATA)."""
    env = os.environ.get("SPACEDIGEST_DATA")
    if env:
        p = Path(env).expanduser()
    else:
        p = default_data_dir()
        loc = _location_file()
        if loc.exists():
            try:
                custom = json.loads(loc.read_text(encoding="utf-8")).get("data_dir")
                if custom:
                    p = Path(custom).expanduser()
            except Exception:
                pass
    p.mkdir(parents=True, exist_ok=True)
    return p


def set_data_dir(new_path: str | None) -> None:
    """Запоминает новую папку данных (вступает в силу после перезапуска).
    None / пустая строка — вернуть стандартную."""
    d = default_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    loc = _location_file()
    if not new_path:
        if loc.exists():
            loc.unlink()
        return
    loc.write_text(json.dumps({"data_dir": str(Path(new_path).expanduser())},
                              ensure_ascii=False, indent=2), encoding="utf-8")


def open_in_file_manager(path: str | Path) -> None:
    """Открыть папку в Проводнике / Finder."""
    import subprocess
    path = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path)                                   # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def copy_to_clipboard(text: str) -> bool:
    """Скопировать текст в системный буфер обмена (Windows / macOS / Linux)."""
    import subprocess
    try:
        if sys.platform.startswith("win"):
            # clip.exe понимает Юникод только в UTF-16 с BOM
            subprocess.run(["clip"], input=b"\xff\xfe" + text.encode("utf-16-le"), check=True,
                           creationflags=0x08000000)               # без окна консоли
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True,
                           env={**os.environ, "LANG": "en_US.UTF-8"})
        else:
            for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
                try:
                    subprocess.run(cmd, input=text.encode("utf-8"), check=True)
                    return True
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
            return False
        return True
    except Exception:
        return False
