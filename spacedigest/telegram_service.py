"""
Telegram внутри приложения (вместо отдельного FastAPI-сервиса на порту 8000).

* Один клиент Telethon живёт в собственном фоновом потоке со своим asyncio-циклом;
  все обращения идут через него, поэтому сбор и вход не спорят за файл сессии.
* Вход — из окна «Настройки»: телефон → код из Telegram → (если есть) пароль 2FA.
* Сбор постов делает ядро 4.0 (connectors/telegram.py → единая база):
  здесь только вход и чтение канала (fetch_channel).
"""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

LogFn = Optional[Callable[[str], None]]

CONNECT_TIMEOUT = 25          # сек на подключение к Telegram
CHANNEL_TIMEOUT = 300         # сек на сбор одного канала


def normalize_channel(s: str) -> str:
    """'@name' / 'https://t.me/name' / 'name/123' → 'name'."""
    s = (s or "").strip()
    for p in ("https://t.me/", "http://t.me/", "t.me/"):
        if s.startswith(p):
            s = s[len(p):]
            break
    s = s.lstrip("@").strip().strip("/")
    return s.split("/")[0].split("?")[0]


def _friendly_error(e: Exception) -> str:
    name = type(e).__name__
    msgs = {
        "PhoneNumberInvalidError": "Неверный номер телефона. Формат: +79991234567.",
        "PhoneNumberBannedError": "Этот номер заблокирован в Telegram.",
        "PhoneCodeInvalidError": "Неверный код. Проверьте сообщение от Telegram.",
        "PhoneCodeExpiredError": "Код устарел. Запросите новый.",
        "PasswordHashInvalidError": "Неверный пароль двухэтапной проверки.",
        "ApiIdInvalidError": "API ID / API Hash не подходят. Проверьте их на my.telegram.org.",
        "UsernameInvalidError": "Такого канала нет (неверное имя).",
        "UsernameNotOccupiedError": "Такого канала нет (имя никем не занято).",
        "ChannelPrivateError": "Канал закрытый — нужен доступ с вашего аккаунта.",
        "AuthKeyUnregisteredError": "Сессия Telegram недействительна — войдите заново.",
    }
    if isinstance(e, ConnectionError):
        return str(e)
    if isinstance(e, asyncio.TimeoutError):
        return "Telegram не ответил вовремя — попробуйте ещё раз."
    if name == "FloodWaitError":
        return f"Telegram просит подождать {getattr(e, 'seconds', '?')} сек (защита от частых запросов)."
    return msgs.get(name, f"{name}: {str(e)[:200]}")


class TelegramService:
    def __init__(self, data_dir: Path, settings):
        self.dir = Path(data_dir) / "telegram"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session_base = self.dir / "tg_session"          # Telethon добавит .session
        self.settings = settings

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client = None
        self._client_key: tuple | None = None
        self._op_lock: asyncio.Lock | None = None
        self._conn_lock: asyncio.Lock | None = None
        self._phone = ""
        self._phone_code_hash = ""
        self._me: str = ""

        self.busy = False            # совместимость статуса; сбор ведёт ядро
        self.last_refresh = ""
        self.last_error = ""

    # ─── фоновый asyncio-цикл ────────────────────────────────────────────────
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop and self._thread and self._thread.is_alive():
            return self._loop
        ready = threading.Event()

        def runner():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._op_lock = asyncio.Lock()
            self._conn_lock = asyncio.Lock()
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=runner, name="telegram-loop", daemon=True)
        self._thread.start()
        ready.wait(5)
        return self._loop                                   # type: ignore[return-value]

    def _run(self, coro, timeout: float = 120):
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout)

    def _api(self) -> tuple[int, str]:
        api_id = str(self.settings.get("telegram", "api_id") or "").strip()
        api_hash = str(self.settings.get("telegram", "api_hash") or "").strip()
        if not api_id.isdigit() or not api_hash:
            raise RuntimeError("Не заданы API ID и API Hash (Настройки → Telegram).")
        return int(api_id), api_hash

    async def _get_client(self):
        from telethon import TelegramClient                 # ленивый импорт
        api_id, api_hash = self._api()
        key = (api_id, api_hash)
        if self._client is not None and self._client_key != key:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
        if self._client is None:
            self._client = TelegramClient(str(self.session_base), api_id, api_hash,
                                          device_model="Space Digest",
                                          app_version="3", system_version="desktop",
                                          connection_retries=2, retry_delay=1, timeout=10)
            self._client_key = key
        if not self._client.is_connected():
            async with self._conn_lock:                      # type: ignore[union-attr]
                if not self._client.is_connected():
                    try:
                        # Telethon может «зависнуть», если сеть молча не отвечает
                        await asyncio.wait_for(self._client.connect(), CONNECT_TIMEOUT)
                    except (asyncio.TimeoutError, OSError) as e:
                        bad, self._client = self._client, None
                        try:
                            await asyncio.wait_for(bad.disconnect(), 5)
                        except Exception:
                            pass
                        raise ConnectionError("Нет связи с серверами Telegram. Проверьте интернет "
                                              "(или VPN/прокси, если Telegram заблокирован в сети).") from e
        return self._client

    # ─── статус и вход ───────────────────────────────────────────────────────
    def configured(self) -> bool:
        try:
            self._api()
            return True
        except RuntimeError:
            return False

    def status(self, check_auth: bool = True) -> dict:
        st = {
            "configured": self.configured(),
            "authorized": False,
            "me": self._me,
            "busy": self.busy,
            "last_refresh": self.last_refresh,
            "last_error": self.last_error,
            "auto_collect": bool(self.settings.get("telegram", "auto_collect")),
            "session_file": (self.session_base.with_suffix(".session")).exists(),
            "db": {"ok": True, "total": 0, "last_date": ""},   # заполняет ядро (единая база)
        }
        if check_auth and st["configured"] and (st["session_file"] or self._client is not None):
            try:
                st["authorized"], st["me"] = self._run(self._auth_state(), timeout=40)
            except Exception as e:                           # нет сети и т.п.
                st["auth_error"] = _friendly_error(e)
        return st

    async def _auth_state(self):
        client = await self._get_client()
        if not await client.is_user_authorized():
            self._me = ""
            return False, ""
        if not self._me:
            me = await client.get_me()
            self._me = ("@" + me.username) if getattr(me, "username", None) else \
                " ".join(filter(None, [me.first_name, me.last_name])) or str(me.id)
        return True, self._me

    def send_code(self, phone: str) -> dict:
        phone = (phone or "").strip().replace(" ", "").replace("-", "")
        if not phone:
            return {"ok": False, "error": "Введите номер телефона."}

        async def go():
            client = await self._get_client()
            if await client.is_user_authorized():
                return {"ok": True, "already": True}
            sent = await client.send_code_request(phone)
            self._phone, self._phone_code_hash = phone, sent.phone_code_hash
            return {"ok": True}
        try:
            return self._run(go(), timeout=60)
        except Exception as e:
            return {"ok": False, "error": _friendly_error(e)}

    def submit_code(self, code: str) -> dict:
        code = (code or "").strip().replace(" ", "")
        if not self._phone_code_hash:
            return {"ok": False, "error": "Сначала запросите код."}

        async def go():
            from telethon.errors import SessionPasswordNeededError
            client = await self._get_client()
            try:
                await client.sign_in(phone=self._phone, code=code,
                                     phone_code_hash=self._phone_code_hash)
            except SessionPasswordNeededError:
                return {"ok": False, "need_password": True}
            self._me = ""
            ok, me = await self._auth_state()
            return {"ok": ok, "me": me}
        try:
            return self._run(go(), timeout=60)
        except Exception as e:
            return {"ok": False, "error": _friendly_error(e)}

    def submit_password(self, password: str) -> dict:
        async def go():
            client = await self._get_client()
            await client.sign_in(password=password)
            self._me = ""
            ok, me = await self._auth_state()
            return {"ok": ok, "me": me}
        try:
            return self._run(go(), timeout=60)
        except Exception as e:
            return {"ok": False, "error": _friendly_error(e)}

    def logout(self) -> dict:
        async def go():
            client = await self._get_client()
            try:
                await client.log_out()
            finally:
                self._client = None
                self._me = ""
            return {"ok": True}
        try:
            return self._run(go(), timeout=30)
        except Exception as e:
            # даже если сеть недоступна — удаляем локальную сессию
            self._client = None
            self._me = ""
            try:
                self.session_base.with_suffix(".session").unlink(missing_ok=True)
            except Exception:
                pass
            return {"ok": True, "note": _friendly_error(e)}

    def reset_client(self) -> None:
        """Сбросить клиента (после смены API ID/Hash или импорта сессии)."""
        async def go():
            if self._client is not None:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
            self._client = None
            self._me = ""
        if self._loop:
            try:
                self._run(go(), timeout=15)
            except Exception:
                self._client = None

    # ─── сбор постов ─────────────────────────────────────────────────────────

    def fetch_channel(self, channel: str, min_id: int = 0,
                      min_date: datetime | None = None, limit: int = 5000) -> dict:
        """Прочитать посты канала новее min_id (и не старше min_date).
        Используется коннектором 4.0: сам в базу не пишет, только отдаёт данные.
        Возвращает {"username", "title", "public", "messages": [{id, date, text}]}."""
        ch = normalize_channel(channel)
        if not ch:
            raise RuntimeError("не указано имя канала")

        async def go():
            from telethon.tl.types import Message
            async with self._op_lock:                        # type: ignore[union-attr]
                client = await self._get_client()
                if not await client.is_user_authorized():
                    raise RuntimeError("Telegram не подключён: войдите в Настройках → Telegram.")
                entity = await client.get_entity(ch)
                username = getattr(entity, "username", None)
                msgs = []
                async for m in client.iter_messages(entity, limit=limit, min_id=int(min_id or 0)):
                    if not isinstance(m, Message) or m.id is None:
                        continue
                    d = m.date
                    if d is not None and d.tzinfo is None:
                        d = d.replace(tzinfo=timezone.utc)
                    if min_date is not None and d is not None and d < min_date:
                        break
                    msgs.append({"id": int(m.id), "date": d, "text": (m.message or "").strip()})
                return {"username": username or ch, "title": getattr(entity, "title", "") or "",
                        "public": bool(username), "messages": msgs}

        try:
            return self._run(asyncio.wait_for(go(), CHANNEL_TIMEOUT), timeout=CHANNEL_TIMEOUT + 30)
        except Exception as e:
            raise RuntimeError(_friendly_error(e)) from e



    def shutdown(self) -> None:
        async def go():
            if self._client is not None:
                await self._client.disconnect()
        if self._loop:
            try:
                self._run(go(), timeout=5)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
