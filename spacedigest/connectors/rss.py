"""
RSS/Atom — полный текст публикации, без обрезки.

Отличия от парсера 3.0:
* разбор через feedparser: все версии RSS/Atom, кодировки, «битые» ленты;
* сохраняются и анонс (description), и полный текст (content:encoded / atom:content);
* сохраняется guid — дубли в одной ленте узнаются, даже если поменялась ссылка;
* условные запросы (ETag / Last-Modified): неизменившаяся лента не скачивается заново;
* если в источнике указана обычная страница, лента ищется в ней и запоминается.
"""
from __future__ import annotations

import calendar
import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..domain.models import FetchResult, RawItem, Source, SourceState
from .base import ConnectorError, LogFn

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SpaceNewsBot/1.0; "
                  "+https://github.com/yourproject/space-news-parser)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


def build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=2, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"], raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update(HEADERS)
    return s


def looks_like_html(head: bytes) -> bool:
    h = head.lstrip()[:400].lower()
    return h.startswith(b"<!doctype html") or b"<html" in h


def discover_feed_links(html: str, base_url: str) -> list[str]:
    """<link rel="alternate" type="application/rss+xml"> + типовые адреса лент."""
    links = []
    for m in re.finditer(r"<link\b[^>]*>", html[:300_000], re.I):
        tag = m.group(0)
        t = re.search(r"type\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
        if not t or ("rss" not in t.group(1).lower() and "atom" not in t.group(1).lower()):
            continue
        h = re.search(r"href\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
        if h:
            links.append(urllib.parse.urljoin(base_url, h.group(1)))
    for guess in ("feed/", "feed", "rss/", "rss", "rss.xml", "index.xml", "atom.xml"):
        links.append(urllib.parse.urljoin(base_url.rstrip("/") + "/", guess))
    return list(dict.fromkeys(links))


def _struct_to_dt(st) -> Optional[datetime]:
    if not st:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)
    except (OverflowError, ValueError, TypeError):
        return None


def entries_to_items(parsed) -> list[RawItem]:
    items: list[RawItem] = []
    for e in parsed.entries:
        url = e.get("link") or ""
        title = e.get("title") or ""
        summary = e.get("summary") or e.get("description") or ""
        contents = [c.get("value") or "" for c in (e.get("content") or [])]
        body = max(contents, key=len) if contents else ""
        published = _struct_to_dt(e.get("published_parsed") or e.get("updated_parsed")
                                  or e.get("created_parsed"))
        ext = (e.get("id") or e.get("guid") or url or "").strip()
        if not ext:
            ext = "h:" + hashlib.sha1(f"{title}|{published}".encode("utf-8")).hexdigest()
        tags = [t.get("term") for t in (e.get("tags") or []) if t.get("term")]
        items.append(RawItem(external_id=ext[:1000], title=title, summary=summary, body=body,
                             url=url, author=e.get("author") or "", published_at=published,
                             extra={"tags": tags} if tags else {}))
    return items


class RssConnector:
    kind = "rss"

    def __init__(self, timeout: int = 15, session: Optional[requests.Session] = None):
        self.timeout = timeout
        self.session = session or build_session()

    def _get(self, url: str, state: Optional[SourceState] = None) -> requests.Response:
        headers = {}
        if state is not None:
            if state.etag:
                headers["If-None-Match"] = state.etag
            if state.last_modified:
                headers["If-Modified-Since"] = state.last_modified
        try:
            resp = self.session.get(url, headers=headers, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise ConnectorError(f"сайт не ответил за {self.timeout} с")
        except requests.exceptions.ConnectionError as e:
            raise ConnectorError(f"нет соединения с сайтом ({type(e).__name__})")
        if resp.status_code == 304:
            return resp
        if resp.status_code >= 400:
            raise ConnectorError(f"сайт вернул ошибку HTTP {resp.status_code}")
        return resp

    def _parse(self, content: bytes, content_type: str):
        import feedparser  # ленивый импорт
        parsed = feedparser.parse(content, response_headers={"content-type": content_type or ""})
        if not parsed.entries and getattr(parsed, "bozo", False) and not parsed.feed:
            raise ConnectorError("ответ не является RSS/Atom-лентой. Нужна прямая ссылка на "
                                 "ленту (обычно …/feed/ или …/rss)")
        return parsed

    def _listing(self, source: Source, resp, new_state: SourceState) -> FetchResult:
        """Страница новостей без RSS → карточки (connectors/html_page.py)."""
        from .html_page import parse_listing, reject_error_page
        enc = getattr(resp, "encoding", None)
        if not enc or enc.lower() == "iso-8859-1":          # requests по умолчанию для text/html без charset
            try:
                resp.encoding = getattr(resp, "apparent_encoding", None) or "utf-8"
            except AttributeError:
                pass
        html = resp.text
        if (err := reject_error_page(html)):
            raise ConnectorError(err)
        items = parse_listing(html, getattr(resp, "url", "") or source.url, source.config.get("item_selector", ""))
        if not items:
            raise ConnectorError("страница открылась, но новостных карточек на ней не найдено — "
                                 "проверьте адрес раздела новостей")
        new_state.resolved_url = "html"
        new_state.etag = new_state.last_modified = None       # страницы без ленты качаем целиком
        undated = sum(1 for i in items if i.published_at is None)
        note = f"страница новостей: карточек {len(items)}" + (f", без даты {undated}" if undated else "")
        return FetchResult(items=items, state=new_state, note=note)

    def fetch(self, source: Source, state: SourceState, log: LogFn = None) -> FetchResult:
        url = source.url if state.resolved_url == "html" else (state.resolved_url or source.url)
        if not url:
            raise ConnectorError("у источника не указан адрес")
        resp = self._get(url, state)
        new_state = SourceState(etag=state.etag, last_modified=state.last_modified,
                                resolved_url=state.resolved_url)
        if resp.status_code == 304:
            return FetchResult(not_modified=True, state=new_state)

        note = ""
        if looks_like_html(resp.content[:512]):
            html_mode = bool(source.config.get("html"))
            if html_mode and state.resolved_url == "html":
                return self._listing(source, resp, new_state)
            # По адресу — обычная страница. Ищем ленту и запоминаем её.
            found = None
            for cand in discover_feed_links(resp.text, url)[:6]:
                try:
                    r2 = self._get(cand)
                    if r2.status_code == 304 or looks_like_html(r2.content[:512]):
                        continue
                    parsed = self._parse(r2.content, r2.headers.get("Content-Type", ""))
                    if parsed.entries:
                        found = (cand, r2, parsed)
                        break
                except ConnectorError:
                    continue
            if not found:
                if html_mode:                      # сайт без ленты: разбираем саму страницу
                    res = self._listing(source, resp, new_state)
                    res.state.resolved_url = "html"   # в следующий раз ленту не ищем
                    return res
                raise ConnectorError("по адресу открывается обычная страница, а найти в ней "
                                     "RSS/Atom-ленту не удалось. Укажите прямой адрес ленты")
            url, resp, parsed = found
            new_state.resolved_url = url
            note = f"найдена лента {url}"
        else:
            parsed = self._parse(resp.content, resp.headers.get("Content-Type", ""))

        new_state.etag = resp.headers.get("ETag") or None
        new_state.last_modified = resp.headers.get("Last-Modified") or None
        return FetchResult(items=entries_to_items(parsed), state=new_state, note=note)
