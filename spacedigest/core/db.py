"""
База данных: один файл SQLite в папке данных.

* Отдельное соединение на каждый поток (sqlite3 не любит общие соединения).
* WAL: чтение не блокирует запись — интерфейс не «подвисает», пока идёт сбор.
* Транзакции явные: `with db.tx(): ...` (BEGIN IMMEDIATE, вложенные вызовы безопасны).
* Схема версионируется: файлы migrations/NNN_*.sql применяются по порядку,
  номер текущей версии хранится в PRAGMA user_version. Перед миграцией
  существующей базы делается резервная копия.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []
        self._all_lock = threading.Lock()

    # ─── соединения ──────────────────────────────────────────────────────────
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=15, isolation_level=None,
                                check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=15000")
            self._local.conn = c
            self._local.depth = 0
            with self._all_lock:
                self._all.append(c)
        return c

    def close(self) -> None:
        with self._all_lock:
            for c in self._all:
                try:
                    c.close()
                except Exception:
                    pass
            self._all.clear()
        self._local = threading.local()

    # ─── транзакции ──────────────────────────────────────────────────────────
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Транзакция на запись. Вложенные tx() становятся частью внешней."""
        c = self.conn()
        depth = getattr(self._local, "depth", 0)
        if depth == 0:
            c.execute("BEGIN IMMEDIATE")
        self._local.depth = depth + 1
        try:
            yield c
        except BaseException:
            self._local.depth = depth
            if depth == 0:
                c.execute("ROLLBACK")
            raise
        else:
            self._local.depth = depth
            if depth == 0:
                c.execute("COMMIT")

    # ─── короткие помощники ──────────────────────────────────────────────────
    def execute(self, sql: str, params: Iterable[Any] | dict = ()) -> sqlite3.Cursor:
        return self.conn().execute(sql, params)

    def query(self, sql: str, params: Iterable[Any] | dict = ()) -> list[dict]:
        return [dict(r) for r in self.conn().execute(sql, params).fetchall()]

    def one(self, sql: str, params: Iterable[Any] | dict = ()) -> Optional[dict]:
        r = self.conn().execute(sql, params).fetchone()
        return dict(r) if r else None

    def scalar(self, sql: str, params: Iterable[Any] | dict = (), default: Any = None) -> Any:
        r = self.conn().execute(sql, params).fetchone()
        return r[0] if r and r[0] is not None else default

    # ─── схема ───────────────────────────────────────────────────────────────
    def version(self) -> int:
        return int(self.scalar("PRAGMA user_version", default=0))

    @staticmethod
    def available_migrations() -> list[tuple[int, Path]]:
        out = []
        for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
            m = re.match(r"(\d+)_", p.name)
            if m:
                out.append((int(m.group(1)), p))
        return out

    def migrate(self) -> int:
        """Довести схему до последней версии. Возвращает итоговую версию."""
        current = self.version()
        pending = [(n, p) for n, p in self.available_migrations() if n > current]
        if not pending:
            return current
        if current > 0:
            self.backup(self.path.with_name(f"{self.path.name}.before-v{pending[-1][0]}.bak"))
        c = self.conn()
        for n, path in pending:
            sql = path.read_text(encoding="utf-8")
            log.info("Миграция базы: %s", path.name)
            try:
                c.executescript(f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {n};\nCOMMIT;")
            except Exception:
                if c.in_transaction:
                    c.execute("ROLLBACK")
                raise
        return self.version()

    def backup(self, target: Path) -> Path:
        dst = sqlite3.connect(target)
        try:
            self.conn().backup(dst)
        finally:
            dst.close()
        return target

    # ─── meta ────────────────────────────────────────────────────────────────
    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self.scalar("SELECT value FROM meta WHERE key = ?", (key,), default)

    def set_meta(self, key: str, value: str) -> None:
        self.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                     "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))
