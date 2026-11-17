"""
Единое хранилище настроек — один файл settings.json в папке данных.

Заменяет прежние admin_config.json, tg_config.json, data/custom_sources.json,
.env Telegram-сервиса и поля «DeepL-ключ», которые раньше вводились на каждой
странице. Все изменения идут через окно «Настройки».
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path

DEFAULTS: dict = {
    "general": {
        "open_in": "window",          # window | browser
        "start_page": "/home",        # /home | /export | / | /tg | /dedup
        "first_run_done": False,
        "animations": True,           # анимированный фон и эффекты интерфейса
        "autostart": False,           # запускать вместе с компьютером (окно свёрнуто)
        "theme": "light",             # light | dark | system
    },
    "fetch": {
        "timeout": 15,                # сек на запрос к ленте
        "delay": 1.0,                 # пауза между источниками
    },
    "collect": {                      # автосбор 4.0 (в фоне, в единую базу)
        "sites_auto": True,
        "sites_minutes": 60,
        "telegram_auto": False,       # включится при переключении экрана Telegram на ядро 4.0
        "telegram_minutes": 30,
        "fulltext": True,             # дотягивать полный текст со страницы, если лента дала только анонс
        "fulltext_min": 600,          # «анонс» — текст короче стольких символов
    },
    "sources": {
        "overrides": {},              # {id: true/false} — «включён по умолчанию» для встроенных
        "custom": [],                 # свои источники
    },
    "export": {                       # выгрузка для ChatGPT
        "folder": "",                 # пусто = Документы/Space Digest/Выгрузки
        "dedup": True,                # убирать повторы перед выгрузкой
        "reference_days": 7,          # сверять с выгрузками за последние N дней
        "prompt": "",                 # пусто = промпт по умолчанию (prompts/digest_default.txt)
        "chatgpt_url": "https://chatgpt.com/",
        "chatgpt_in_app": True,       # открывать ChatGPT в окне программы (иначе — в браузере)
    },
    "slk": {                          # дайджест по РН сверхлёгкого класса
        "period_days": 14,            # новые дни выгрузки
        "overlap_days": 7,            # + дни перекрытия с прошлым поиском
        "folder": "",                 # пусто = Документы/Space Digest/Выгрузки СЛК
        "dedup": True,                # сводить версии одного события в одну строку
        "reference_days": 30,         # с какими прошлыми выгрузками СЛК сверять повторы
        "prompt": "",                 # пусто = встроенный промпт (prompts/slk_default.txt)
        "prefilter": True,            # мягкий предфильтр перед ChatGPT
        "names": "",                  # пусто = встроенные словари (services/slk.py)
        "rocket": "",
        "military": "",
    },
    "morning": {                      # утренняя выгрузка: сбор + подготовка CSV к нужному часу
        "enabled": False,
        "time": "09:00",              # по Москве
        "notify": True,               # системное уведомление, когда готово
    },
    "updates": {
        "repo": "",                   # GitHub owner/name, где публикуются установщики
        "auto_check": True,           # проверять при запуске (не чаще раза в 6 часов)
    },
    "filter": {                       # фильтр мусора перед выгрузкой
        "enabled": True,
        "stop": "",                   # стоп-слова, по одному в строке; пусто = список по умолчанию
        "topic": "",                  # слова «про космос» для источников с фильтром; пусто = по умолчанию
    },
    "translation": {
        "default_on": False,          # тумблер «Переводить» включён при открытии страниц
        "provider": "google",         # google | deepl
        "deepl_key": "",
    },
    "telegram": {
        "api_id": "",
        "api_hash": "",
        "channels": [],               # управляемый список каналов (без @)
        "lookback_days": 7,           # глубина сбора
        "auto_collect": False,        # фоновый сбор
        "poll_minutes": 30,
    },
    "dedup": {
        "threshold": 0.82,
        "cross_compare": True,
        "prefer_file_as_base": True,
        "engine": "auto",             # auto | neural | tfidf
    },
    "security": {
        "password_hash": "",          # pbkdf2; пусто = настройки без пароля
    },
}

# Поля, которые не уходят в «публичные» настройки рабочих страниц.
SECRET_PATHS = {("translation", "deepl_key"), ("telegram", "api_hash"),
                ("security", "password_hash")}


def _deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def hash_password(pw: str) -> str:
    if not pw:
        return ""
    salt = secrets.token_hex(8)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode(), 120_000)
    return f"pbkdf2${salt}${dk.hex()}"


def check_password(pw: str, stored: str) -> bool:
    if not stored:
        return True
    try:
        _, salt, hexd = stored.split("$", 2)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", (pw or "").encode("utf-8"), salt.encode(), 120_000)
    return hmac.compare_digest(dk.hex(), hexd)


class Settings:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data = copy.deepcopy(DEFAULTS)
        self.load()

    # ── чтение/запись ──
    def load(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    self._data = _deep_merge(DEFAULTS, raw)
                except Exception:
                    # битый файл не должен ронять приложение — сохраняем копию
                    try:
                        self.path.replace(self.path.with_suffix(".broken.json"))
                    except Exception:
                        pass
                    self._data = copy.deepcopy(DEFAULTS)
            else:
                self._data = copy.deepcopy(DEFAULTS)
                self.save()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    # ── доступ ──
    def all(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def get(self, section: str, key: str | None = None, default=None):
        with self._lock:
            sec = self._data.get(section, {})
            if key is None:
                return copy.deepcopy(sec)
            return copy.deepcopy(sec.get(key, default))

    def update(self, patch: dict) -> dict:
        """Частичное обновление {section: {key: value}} с проверкой типов по DEFAULTS."""
        with self._lock:
            clean: dict = {}
            for section, values in (patch or {}).items():
                if section not in DEFAULTS or not isinstance(values, dict):
                    continue
                for key, val in values.items():
                    if key not in DEFAULTS[section]:
                        continue
                    ref = DEFAULTS[section][key]
                    try:
                        if isinstance(ref, bool):
                            val = bool(val)
                        elif isinstance(ref, int):
                            val = int(val)
                        elif isinstance(ref, float):
                            val = float(val)
                        elif isinstance(ref, str):
                            val = "" if val is None else str(val).strip()
                        elif isinstance(ref, list):
                            val = list(val or [])
                        elif isinstance(ref, dict):
                            val = dict(val or {})
                    except (TypeError, ValueError):
                        continue
                    clean.setdefault(section, {})[key] = val
            self._data = _deep_merge(self._data, clean)
            self._validate()
            self.save()
            return self.all()

    def _validate(self) -> None:
        d = self._data
        d["dedup"]["threshold"] = min(0.99, max(0.5, float(d["dedup"]["threshold"])))
        d["telegram"]["lookback_days"] = min(90, max(1, int(d["telegram"]["lookback_days"])))
        d["telegram"]["poll_minutes"] = min(24 * 60, max(5, int(d["telegram"]["poll_minutes"])))
        d["fetch"]["timeout"] = min(120, max(3, int(d["fetch"]["timeout"])))
        d["fetch"]["delay"] = min(10.0, max(0.0, float(d["fetch"]["delay"])))
        d["export"]["reference_days"] = min(30, max(0, int(d["export"]["reference_days"])))
        d["slk"]["period_days"] = min(90, max(1, int(d["slk"].get("period_days") or 14)))
        d["slk"]["overlap_days"] = min(30, max(0, int(d["slk"].get("overlap_days") or 0)))
        d["slk"]["reference_days"] = min(120, max(0, int(d["slk"].get("reference_days") or 0)))
        for k in ("names", "rocket", "military"):
            d["slk"][k] = str(d["slk"].get(k) or "")[:20000]
        if not str(d["export"]["chatgpt_url"]).startswith(("http://", "https://")):
            d["export"]["chatgpt_url"] = "https://chatgpt.com/"
        d["collect"]["sites_minutes"] = min(24 * 60, max(15, int(d["collect"]["sites_minutes"])))
        d["collect"]["telegram_minutes"] = min(24 * 60, max(10, int(d["collect"]["telegram_minutes"])))
        d["collect"]["fulltext_min"] = min(5000, max(100, int(d["collect"].get("fulltext_min") or 600)))
        if d["translation"]["provider"] not in ("google", "deepl"):
            d["translation"]["provider"] = "google"
        try:
            from .core.scheduler import parse_hhmm
            h, m = parse_hhmm(d["morning"].get("time") or "09:00")
            d["morning"]["time"] = f"{h:02d}:{m:02d}"
        except (ValueError, TypeError):
            d["morning"]["time"] = "09:00"
        if d["general"].get("theme") not in ("light", "dark", "system"):
            d["general"]["theme"] = "light"
        for k in ("stop", "topic"):
            d["filter"][k] = str(d["filter"].get(k) or "")[:20000]
        if d["dedup"]["engine"] not in ("auto", "neural", "tfidf"):
            d["dedup"]["engine"] = "auto"
        if d["general"]["open_in"] not in ("window", "browser"):
            d["general"]["open_in"] = "window"

    # ── пароль ──
    def password_set(self) -> bool:
        return bool(self.get("security", "password_hash"))

    def set_password(self, pw: str) -> None:
        with self._lock:
            self._data["security"]["password_hash"] = hash_password(pw)
            self.save()

    def verify_password(self, pw: str) -> bool:
        return check_password(pw, self.get("security", "password_hash") or "")

    # ── вид для фронтенда ──
    def public(self) -> dict:
        """Без секретов — для рабочих страниц."""
        d = self.all()
        for sec, key in SECRET_PATHS:
            d.get(sec, {}).pop(key, None)
        d["translation"]["has_deepl_key"] = bool(self.get("translation", "deepl_key"))
        d["telegram"]["has_api"] = bool(self.get("telegram", "api_id")) and \
            bool(self.get("telegram", "api_hash"))
        d["security"] = {"protected": self.password_set()}
        return d

    def for_editor(self) -> dict:
        """Для окна «Настройки» (после разблокировки): всё, кроме хеша пароля."""
        d = self.all()
        d["security"] = {"protected": self.password_set()}
        return d
