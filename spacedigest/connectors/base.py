"""
Коннектор — единственное место, где программа знает, *откуда* берутся новости.
Новый тип источника = новый класс с методом fetch(); остальной конвейер не меняется.
"""
from __future__ import annotations

from typing import Callable, Optional, Protocol

from ..domain.models import FetchResult, Source, SourceState

LogFn = Optional[Callable[[str], None]]


class Connector(Protocol):
    kind: str

    def fetch(self, source: Source, state: SourceState, log: LogFn = None) -> FetchResult:
        """Скачать всё, что источник отдаёт сейчас. Фильтрации по датам здесь нет:
        что уже есть в базе, отсеет приём (ingest)."""
        ...


class ConnectorError(Exception):
    """Понятная пользователю ошибка источника (показывается в «здоровье» источника)."""
