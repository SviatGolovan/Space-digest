"""Модели предметной области. Без зависимостей от веба, базы и сети."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

SOURCE_KINDS = ("rss", "telegram", "file")


@dataclass
class Source:
    id: int
    key: str
    kind: str
    name: str
    url: str = ""
    category: str = ""
    region: str = ""
    builtin: bool = False
    enabled: bool = True
    priority: int = 0
    config: dict = field(default_factory=dict)
    space_only: bool = False          # в выгрузку — только новости с космическими словами

    @classmethod
    def from_row(cls, r: dict) -> "Source":
        cfg = r.get("config") or "{}"
        return cls(id=r["id"], key=r["key"], kind=r["kind"], name=r["name"], url=r.get("url") or "",
                   category=r.get("category") or "", region=r.get("region") or "",
                   builtin=bool(r.get("builtin")), enabled=bool(r.get("enabled")),
                   priority=int(r.get("priority") or 0), space_only=bool(r.get("space_only")),
                   config=json.loads(cfg) if isinstance(cfg, str) else dict(cfg))


@dataclass
class SourceState:
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    resolved_url: Optional[str] = None
    cursor: Optional[str] = None


@dataclass
class RawItem:
    """То, что отдаёт коннектор: «сырая» публикация до нормализации."""
    external_id: str
    title: str = ""
    summary: str = ""            # может быть HTML — нормализует ingest
    body: str = ""
    url: str = ""
    author: str = ""
    published_at: Optional[datetime] = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    items: list[RawItem] = field(default_factory=list)
    not_modified: bool = False           # сервер ответил 304 — лента не менялась
    state: SourceState = field(default_factory=SourceState)
    note: str = ""                       # пояснение для лога (например, «найдена лента …»)


@dataclass
class IngestStats:
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0

    def __add__(self, o: "IngestStats") -> "IngestStats":
        return IngestStats(self.new + o.new, self.updated + o.updated,
                           self.unchanged + o.unchanged, self.skipped + o.skipped)
