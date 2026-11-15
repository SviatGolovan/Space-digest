"""
Telegram-канал как источник. Клиент Telethon и вход живут в TelegramService;
коннектор только просит посты и превращает их в RawItem.

Сбор инкрементальный: курсор = последний собранный id поста. Посты сохраняются
одной транзакцией после чтения всего канала, поэтому прерванный сбор не оставляет «дыр».
"""
from __future__ import annotations

from datetime import timedelta
from typing import Callable

from ..core.timeutil import utcnow
from ..domain.models import FetchResult, RawItem, Source, SourceState
from .base import ConnectorError, LogFn

TITLE_LEN = 118


def title_from_text(text: str) -> str:
    first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    return (first[:TITLE_LEN - 1] + "…") if len(first) > TITLE_LEN else first


class TelegramConnector:
    kind = "telegram"

    def __init__(self, service, lookback_days: Callable[[], int]):
        self.service = service
        self.lookback_days = lookback_days

    def fetch(self, source: Source, state: SourceState, log: LogFn = None) -> FetchResult:
        channel = source.url or source.key.split(":", 1)[-1]
        try:
            min_id = int(state.cursor or 0)
        except ValueError:
            min_id = 0
        min_date = utcnow() - timedelta(days=max(1, int(self.lookback_days() or 7)))
        try:
            data = self.service.fetch_channel(channel, min_id=min_id, min_date=min_date)
        except RuntimeError as e:
            raise ConnectorError(str(e)) from e

        username = data["username"]
        items, empty = [], 0
        for m in data["messages"]:
            text = m["text"]
            if not text:                 # фото/видео без подписи — не новость
                empty += 1
                continue
            items.append(RawItem(
                external_id=str(m["id"]), title=title_from_text(text), body=text,
                url=f"https://t.me/{username}/{m['id']}" if data["public"] else "",
                published_at=m["date"]))
        max_id = max([m["id"] for m in data["messages"]] + [min_id])
        new_state = SourceState(cursor=str(max_id))
        note = f"@{username}: постов {len(items)}" + (f", без текста {empty}" if empty else "")
        return FetchResult(items=items, state=new_state, note=note)
