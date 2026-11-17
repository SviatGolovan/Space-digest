"""
Страница новостей без RSS: разбор карточек на сайте компании.

Перенесено из парсера СЛК 3.1 с одним важным изменением. Раньше карточка без даты
проходила любой фильтр по периоду, и при первом сборе сайт отдавал весь свой архив
как «свежие» новости (так в дайджест попали материалы Space Energy 2023–2025 годов).
Теперь дата карточки передаётся как есть или не передаётся вовсе, а решает приём:
  * дата из карточки помечается как 'card' и потом сверяется со страницей статьи;
  * без даты новость получает пометку «дата не подтверждена», а при первом сборе
    источника — «архив сайта» и в выгрузки не идёт (см. services/ingest.py).

Три уровня разбора: заданный CSS-селектор → <article> и типовые классы → самая
большая группа ссылок с общим началом пути.
"""
from __future__ import annotations

import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from ..domain.models import RawItem

ITEM_LIMIT = 40

NAV_LABELS = {
    "перейти", "подробнее", "читать далее", "читать полностью", "далее",
    "все новости", "больше новостей", "смотреть все", "показать ещё",
    "назад", "вперёд", "вперед", "главная", "контакты", "о компании",
    "о нас", "продукты", "услуги", "продукты и услуги", "вакансии",
    "партнёры", "партнеры", "карьера", "документы", "закупки", "пресса",
    "сми о нас", "галерея", "видео", "фото", "поиск", "войти", "регистрация",
    "политика конфиденциальности", "карта сайта", "версия для слабовидящих",
    "more", "read more", "learn more", "all news", "view all", "back",
    "home", "about", "about us", "contacts", "careers", "products",
    "services", "privacy policy", "sitemap", "search", "login",
}
BAD_SCHEMES = ("tel:", "mailto:", "javascript:", "#", "sms:", "skype:")
RE_PHONE = re.compile(r"^[\+\d][\d\s\-()]{6,}$")
RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
RE_URLISH = re.compile(r"^(https?://|www\.)", re.I)
RE_ERROR_PAGE = re.compile(
    r"(error\s*[45]\d\d|that.s an error|404 not found|page not found|"
    r"страница не найдена|доступ запрещ|access denied|forbidden)", re.I)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11,
    "декабря": 12, "янв": 1, "фев": 2, "мар": 3, "апр": 4, "июн": 6, "июл": 7,
    "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}


# ─── даты ────────────────────────────────────────────────────────────────────

def _mk(y: int, mo: int, d: int) -> Optional[datetime]:
    try:
        dt = datetime(y, mo, d, 12, 0, tzinfo=timezone.utc)   # полдень: день не «съедет» по поясам
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    if dt.year < 2000 or (dt - now).days > 2:                 # дата из будущего — это не публикация
        return None
    return dt


def date_from_text(text: str) -> Optional[datetime]:
    """«March 5, 2026», «5 марта 2026», «2026-03-05», «05.03.2026»."""
    if not text:
        return None
    t = text.strip()
    m = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", t)
    if m:
        return _mk(*(int(x) for x in m.groups()))
    m = re.search(r"([A-Za-zА-Яа-яЁё]+)\.?\s+(\d{1,2}),?\s+(20\d{2})", t)
    if m and (mo := _MONTHS.get(m.group(1).lower())):
        return _mk(int(m.group(3)), mo, int(m.group(2)))
    m = re.search(r"(\d{1,2})\s+([A-Za-zА-Яа-яЁё]+)\.?,?\s+(20\d{2})", t)
    if m and (mo := _MONTHS.get(m.group(2).lower())):
        return _mk(int(m.group(3)), mo, int(m.group(1)))
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b", t)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        if mo > 12:
            d, mo = mo, d
        return _mk(y, mo, d)
    return None


def parse_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:                                                      # noqa: BLE001
        return date_from_text(raw)


# ─── отсев служебных ссылок ──────────────────────────────────────────────────

def _clean(text: Optional[str]) -> str:
    return " ".join((text or "").split()).strip()


def is_junk_title(title: str, href: str = "", min_words: int = 3) -> bool:
    """Телефон, почта, пункт меню, «Подробнее», страница ошибки — не новость."""
    t = (title or "").strip()
    if not t:
        return True
    low = t.lower().strip(" .:!—–-«»\"'")
    if RE_PHONE.match(t) or RE_EMAIL.match(t) or RE_URLISH.match(t) or low in NAV_LABELS:
        return True
    if any(low.startswith(lbl + " ") for lbl in ("перейти", "читать", "смотреть", "показать",
                                                  "подробнее", "read more", "learn more", "view all")):
        return True
    if RE_ERROR_PAGE.search(t) or (href or "").strip().lower().startswith(BAD_SCHEMES):
        return True
    words = [w for w in re.split(r"[\s—–-]+", t) if len(w) > 1]
    return len(words) < min_words or not re.search(r"[A-Za-zА-Яа-яЁё]{3,}", t)


def reject_error_page(html: str) -> Optional[str]:
    """Сайт отдал страницу ошибки с кодом 200 → текст ошибки, иначе None."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html[:8000], re.I | re.S)
    head = _clean(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""
    if head and RE_ERROR_PAGE.search(head):
        return f"сайт вернул страницу ошибки: «{head[:70]}»"
    return None


# ─── разбор ──────────────────────────────────────────────────────────────────

def _item(title: str, summary: str, href: str, pub: Optional[datetime]) -> RawItem:
    return RawItem(external_id=href[:1000] or "h:" + hashlib.sha1(title.encode()).hexdigest(),
                   title=title, summary=summary[:1500], url=href, published_at=pub,
                   date_from="card" if pub else None)


def _soup(html: str):
    from bs4 import BeautifulSoup
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:                                                      # noqa: BLE001
        return BeautifulSoup(html, "html.parser")


def _card_date(node) -> Optional[datetime]:
    t = node.find("time")
    if t is not None:
        d = parse_date(t.get("datetime") or t.get_text(" "))
        if d:
            return d
    return date_from_text(node.get_text(" ")[:400])


def parse_listing(html: str, base_url: str, item_selector: str = "") -> list[RawItem]:
    """Карточки новостей со страницы. Пустой список — карточек не нашлось."""
    soup = _soup(html)
    for junk in soup(["script", "style", "nav", "footer", "header", "form", "noscript"]):
        junk.decompose()
    blocks = []
    if item_selector:
        try:
            blocks = soup.select(item_selector)
        except Exception:                                                  # noqa: BLE001
            blocks = []
    if not blocks:
        blocks = soup.find_all("article")
    if not blocks:
        rx = re.compile(r"(news|post|card|item|entry|article|press|release|blog)", re.I)
        blocks = [el for el in soup.find_all(["div", "li", "section"], class_=rx)
                  if el.find("a", href=True)]

    out: list[RawItem] = []
    seen: set[str] = set()
    base_norm = base_url.rstrip("/")
    for block in blocks:
        link = block.find("a", href=True)
        if not link:
            continue
        href = urllib.parse.urljoin(base_url, link["href"])
        if href in seen or href.rstrip("/") == base_norm:
            continue
        head = block.find(["h1", "h2", "h3", "h4"])
        title = _clean(head.get_text(" ")) if head else _clean(link.get_text(" "))
        if len(title) < 20 or is_junk_title(title, href):
            continue
        summary = ""
        for p in block.find_all("p"):
            txt = _clean(p.get_text(" "))
            if txt and txt != title and len(txt) > len(summary):
                summary = txt
        seen.add(href)
        out.append(_item(title, summary, href, _card_date(block)))
        if len(out) >= ITEM_LIMIT:
            break
    return out or _parse_clusters(soup, base_url)


def _parse_clusters(soup, base_url: str) -> list[RawItem]:
    """Сайты без семантической вёрстки: самая большая группа ссылок с общим началом пути."""
    base = urllib.parse.urlparse(base_url)
    host = base.netloc.replace("www.", "")
    clusters: dict[str, list] = {}
    for link in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(base_url, link["href"])
        u = urllib.parse.urlparse(href)
        if u.netloc and u.netloc.replace("www.", "") != host:
            continue
        path = u.path.rstrip("/")
        if not path or path == base.path.rstrip("/"):
            continue
        segments = [s for s in path.split("/") if s]
        if len(segments) < 2:
            continue
        title = _clean(link.get_text(" "))
        if len(title) < 20:
            head = link.find(["h1", "h2", "h3", "h4"])
            title = _clean(head.get_text(" ")) if head else title
        if len(title) < 20 or is_junk_title(title, href, min_words=4):
            continue
        key = segments[0] + "/" + re.sub(r"\d+", "#", segments[1])[:12]
        clusters.setdefault(key, []).append((href, title, link))
    if not clusters:
        return []

    def rank(kv):
        key, links = kv
        bonus = 2 if re.search(r"(news|press|article|post|media|novosti|release|blog|smi)", key, re.I) else 0
        return len(links) + bonus * 3, bonus

    _, links = max(clusters.items(), key=rank)
    if len(links) < 3:
        return []
    hrefs = {h for h, _, _ in links}
    out, seen = [], set()
    for href, title, link in links:
        if href in seen:
            continue
        seen.add(href)
        pub, summary, node = None, "", link
        for _ in range(4):                     # к карточке, но не выше общего контейнера списка
            parent = node.parent
            if parent is None:
                break
            own = sum(1 for a in parent.find_all("a", href=True)
                      if urllib.parse.urljoin(base_url, a["href"]) in hrefs)
            if own > 1:
                break
            node = parent
            pub = pub or _card_date(node)
            if not summary:
                for para in node.find_all("p"):
                    txt = _clean(para.get_text(" "))
                    if txt and txt != title and len(txt) >= 20:
                        summary = txt
                        break
            if pub and summary:
                break
        out.append(_item(title, summary, href, pub))
        if len(out) >= ITEM_LIMIT:
            break
    return out
