"""
Space News Fetcher
Поддерживает RSS/Atom ленты и базовый HTML-парсинг.
Запуск из CLI:
    python fetcher.py --sources nasa spacenews --date-from 2024-01-01 --date-to 2024-12-31 --output news.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
import urllib.parse
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SpaceNewsBot/1.0; "
        "+https://github.com/yourproject/space-news-parser)"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}

NS = {
    "atom":    "http://www.w3.org/2005/Atom",
    "media":   "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc":      "http://purl.org/dc/elements/1.1/",
}


def _clean(text: Optional[str]) -> str:
    """Убираем HTML-теги и лишние пробелы."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return " ".join(text.split()).strip()


def _parse_date(raw: Optional[str]) -> str:
    """Приводим разные форматы дат к ISO-8601."""
    if not raw:
        return ""
    raw = raw.strip()
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            continue
    try:
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return raw


def _in_range(date_str: str, date_from: str, date_to: str) -> bool:
    """Попадает ли статья в диапазон дат. Сравнение по календарному дню,
    границы 'от' и 'до' — включительно."""
    if not date_str or (not date_from and not date_to):
        return True
    # Берём только дату (YYYY-MM-DD)
    article_date = date_str[:10]
    # Если дату не удалось привести к ISO (YYYY-MM-DD) — не отбрасываем статью,
    # иначе из-за нераспознанного формата терялись бы валидные новости.
    if len(article_date) != 10 or article_date[4] != "-" or not article_date[:4].isdigit():
        return True
    if date_from and article_date < date_from:   # < → день 'от' включительно
        return False
    if date_to and article_date > date_to:        # > → день 'до' включительно
        return False
    return True


def _get_text(element, *paths) -> str:
    """Пробуем несколько xpath-путей, возвращаем первый непустой результат."""
    for path in paths:
        el = element.find(path, NS)
        if el is not None and el.text:
            return el.text.strip()
    return ""


class SpaceNewsFetcher:
    def __init__(self, timeout: int = 15, delay: float = 1.0):
        self.timeout = timeout
        self.delay = delay
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(HEADERS)
        return session

    def _fetch_url(self, url: str) -> str:
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    @staticmethod
    def _looks_like_html(text: str) -> bool:
        head = text.lstrip()[:300].lower()
        return head.startswith("<!doctype html") or "<html" in head

    @staticmethod
    def _discover_feed_links(html: str, base_url: str) -> list[str]:
        """Ищет в HTML объявленные RSS/Atom-ленты:
        <link rel="alternate" type="application/rss+xml" href="...">."""
        links = []
        for m in re.finditer(r"<link\b[^>]*>", html[:200_000], re.I):
            tag = m.group(0)
            type_m = re.search(r"type\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
            if not type_m or "rss" not in type_m.group(1).lower() and "atom" not in type_m.group(1).lower():
                continue
            href_m = re.search(r"href\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
            if href_m:
                links.append(urllib.parse.urljoin(base_url, href_m.group(1)))
        # запасные типовые адреса лент
        for guess in ("feed/", "feed", "rss/", "rss", "rss.xml", "index.xml", "atom.xml"):
            links.append(urllib.parse.urljoin(base_url.rstrip("/") + "/", guess))
        # dedupe, сохранив порядок
        seen, out = set(), []
        for u in links:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    def _parse_rss(self, xml_text: str, source: dict, date_from: str, date_to: str) -> list[dict]:
        articles = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            raise ValueError(f"XML parse error: {e}")

        # Определяем, Atom или RSS
        is_atom = root.tag == "{http://www.w3.org/2005/Atom}feed" or "atom" in root.tag.lower()

        if is_atom:
            entries = root.findall("atom:entry", NS) or root.findall("{http://www.w3.org/2005/Atom}entry")
            for entry in entries:
                url = ""
                link_el = entry.find("atom:link[@rel='alternate']", NS) or entry.find("atom:link", NS)
                if link_el is not None:
                    url = link_el.get("href", "")

                title   = _clean(_get_text(entry, "atom:title"))
                summary = _clean(
                    _get_text(entry, "atom:summary", "atom:content", "content:encoded")
                )
                pub_raw = _get_text(entry, "atom:published", "atom:updated")
                pub     = _parse_date(pub_raw)

                if not _in_range(pub, date_from, date_to):
                    continue

                articles.append({
                    "source_name": source["name"],
                    "source_id":   source.get("id",""),
                    "title":       title,
                    "summary":     summary[:500] if summary else "",
                    "url":         url,
                    "published_at": pub,
                })
        else:
            channel = root.find("channel") or root
            items = channel.findall("item") if channel else []
            for item in items:
                url     = _get_text(item, "link", "guid")
                title   = _clean(_get_text(item, "title"))
                summary = _clean(
                    _get_text(item, "description", "content:encoded", "dc:description")
                )
                pub_raw = _get_text(item, "pubDate", "dc:date")
                pub     = _parse_date(pub_raw)

                if not _in_range(pub, date_from, date_to):
                    continue

                articles.append({
                    "source_name": source["name"],
                    "source_id":   source.get("id",""),
                    "title":       title,
                    "summary":     summary[:500] if summary else "",
                    "url":         url,
                    "published_at": pub,
                })

        return articles

    def fetch_source(self, source: dict, date_from: str = "", date_to: str = "") -> list[dict]:
        time.sleep(self.delay)
        text = self._fetch_url(source["url"])

        # Если по адресу отдали обычную страницу (HTML), а не RSS/Atom-ленту —
        # пробуем сами найти ленту, объявленную в этой странице.
        if self._looks_like_html(text):
            last_err = None
            for feed_url in self._discover_feed_links(text, source["url"])[:6]:
                try:
                    candidate = self._fetch_url(feed_url)
                    if self._looks_like_html(candidate):
                        continue
                    articles = self._parse_rss(candidate, source, date_from, date_to)
                    # нашли рабочую ленту — используем её
                    return articles
                except Exception as e:      # noqa: BLE001 — перебор кандидатов
                    last_err = e
                    continue
            raise ValueError(
                "по этому адресу открывается обычная страница, а не RSS/Atom-лента, "
                "и найти ленту автоматически не удалось. Укажите прямой адрес ленты "
                "(обычно .../feed/ или .../rss)."
            )

        try:
            return self._parse_rss(text, source, date_from, date_to)
        except ValueError:
            # Контент не HTML, но и не валидный XML — вероятно, лента битая/закрыта.
            raise ValueError(
                "ответ сервера не является корректной RSS/Atom-лентой. Проверьте адрес: "
                "нужна прямая ссылка на ленту (обычно .../feed/ или .../rss)."
            )

    def fetch_all(self, sources: list[dict], date_from: str = "", date_to: str = "") -> list[dict]:
        all_articles: list[dict] = []
        for source in sources:
            try:
                print(f"  Fetching {source['name']}...", end=" ", flush=True)
                articles = self.fetch_source(source, date_from, date_to)
                all_articles.extend(articles)
                print(f"{len(articles)} articles")
            except Exception as e:
                print(f"ERROR: {e}")
        return all_articles


# ─── CLI ─────────────────────────────────────────────────────────────────────

def cli_main():
    from spacedigest.sources import SOURCES  # noqa: CLI: python -m spacedigest.fetcher

    parser = argparse.ArgumentParser(
        description="Space News Parser — CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python fetcher.py
  python fetcher.py --sources nasa spacenews universetoday
  python fetcher.py --date-from 2024-06-01 --date-to 2024-06-30
  python fetcher.py --output my_news.csv
        """,
    )
    parser.add_argument(
        "--sources", nargs="+",
        help="Source IDs to fetch (default: all enabled). Available: " +
             ", ".join(s["id"] for s in SOURCES),
    )
    parser.add_argument("--date-from", default="", help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--date-to",   default="", help="End date YYYY-MM-DD (inclusive)")
    parser.add_argument("--output",    default="space_news.csv", help="Output CSV filename")
    parser.add_argument("--delay",     type=float, default=1.0,  help="Delay between requests (sec)")
    args = parser.parse_args()

    selected = [s for s in SOURCES if (
        (args.sources and s["id"] in args.sources) or
        (not args.sources and s["enabled"])
    )]

    if not selected:
        print("No sources selected. Use --sources or check SOURCES list.")
        return

    print(f"\n🚀 Space News Parser")
    print(f"   Sources:    {len(selected)}")
    print(f"   Date range: {args.date_from or 'any'} → {args.date_to or 'any'}")
    print(f"   Output:     {args.output}\n")

    fetcher = SpaceNewsFetcher(delay=args.delay)
    articles = fetcher.fetch_all(selected, args.date_from, args.date_to)
    articles.sort(key=lambda x: x.get("published_at", ""), reverse=True)

    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(["Дата", "Источник", "Заголовок", "Новость", "Ссылка"])
        for a in articles:
            writer.writerow([
                a.get("published_at", ""),
                a.get("source_name", ""),
                a.get("title", ""),
                a.get("summary", ""),
                a.get("url", ""),
            ])

    print(f"\n✅ Done! {len(articles)} articles saved to {args.output}")


if __name__ == "__main__":
    cli_main()
