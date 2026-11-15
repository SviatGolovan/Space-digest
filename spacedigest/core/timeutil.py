"""Время: всё внутри программы хранится в UTC в формате 2026-11-14T09:30:00Z."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

ISO = "%Y-%m-%dT%H:%M:%SZ"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return to_iso(utcnow())


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime(ISO)


def from_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.strptime(s, ISO).replace(tzinfo=timezone.utc)


def iso_after(minutes: float = 0, seconds: float = 0) -> str:
    return to_iso(utcnow() + timedelta(minutes=minutes, seconds=seconds))


_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%d %H:%M UTC",          # формат дат 3.0 (сайты)
    "%Y-%m-%d %H:%M:%S.%f",        # news.db Telegram (SQLAlchemy)
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",              # TG-выборки 3.0
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%Y-%m-%d",
)


def parse_any(raw: Optional[str]) -> Optional[datetime]:
    """Разобрать дату из любой встречающейся формы. Без часового пояса — считаем UTC."""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)              # лишние знаки дробных секунд
    s = re.sub(r"([+-]\d\d):(\d\d)$", r"\1\2", s)       # +03:00 → +0300 для strptime
    for fmt in _FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0)
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0)
    except Exception:
        return None
