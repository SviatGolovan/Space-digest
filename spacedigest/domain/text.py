"""Нормализация текста и ссылок — общая для всех источников."""
from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# ─── HTML → текст ─────────────────────────────────────────────────────────────

_DROP_BLOCKS = re.compile(r"<(script|style|noscript|iframe|svg|template)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_COMMENTS = re.compile(r"<!--.*?-->", re.S)
_BREAKS = re.compile(r"<\s*(br|hr)\b[^>]*>", re.I)
_BLOCK_END = re.compile(r"</\s*(p|div|section|article|blockquote|h[1-6]|ul|ol|table|tr|figure|figcaption|pre)\s*>", re.I)
_BLOCK_START = re.compile(r"<\s*(p|div|section|article|blockquote|h[1-6]|table|tr|figure|pre)\b[^>]*>", re.I)
_LI = re.compile(r"<\s*li\b[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\u00a0\u2009\u202f]+")
_INVISIBLE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]")   # нулевой ширины, мягкий перенос

# Хвосты, которые WordPress и подобные движки дописывают в ленту
_TAILS = (
    re.compile(r"\s*The post .{1,400}? appeared first on .{1,200}?\.?\s*$", re.S),
    re.compile(r"\s*(Continue reading|Read more|Читать далее|Подробнее)\s*(→|»|\.\.\.|…)?\s*$", re.I),
    re.compile(r"\s*\[(…|\.\.\.|&#8230;)\]\s*$"),
)


_MOJIBAKE = re.compile("[\u00c2\u00c3\u00e2\u00d0\u00d1][\u0080-\u00bf\u2018-\u203a\u20ac\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u02c6\u02dc\u2122]")


def fix_mojibake(s: str | None) -> str:
    """«planetâ€™s», «ÐšÐ¾ÑÐ¼Ð¾Ñ» — UTF-8, прочитанный как Latin-1/CP1252 (бывает в RSS).
    Чиним, только если починка однозначна: всё перекодировалось и «мусора» стало меньше."""
    if not s or not _MOJIBAKE.search(s):
        return s or ""
    for enc in ("cp1252", "latin-1"):
        try:
            fixed = s.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if len(_MOJIBAKE.findall(fixed)) < len(_MOJIBAKE.findall(s)):
            return fixed
    # смешанный текст: чиним по фрагментам
    def part(m: re.Match) -> str:
        frag = m.group(0)
        for enc in ("cp1252", "latin-1"):
            try:
                return frag.encode(enc).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        return frag
    return re.sub("(?:[\u00c2-\u00f4][\u0080-\u00bf\u2018-\u203a\u20ac\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u02c6\u02dc\u2122\u0081\u008d\u008f\u0090\u009d]{1,3})+", part, s)


def html_to_text(raw: str | None) -> str:
    """HTML (или текст с сущностями) → читаемый текст с абзацами."""
    if not raw:
        return ""
    s = str(raw)
    if "<" in s:
        s = _COMMENTS.sub(" ", s)
        s = _DROP_BLOCKS.sub(" ", s)
        s = _BREAKS.sub("\n", s)
        s = _LI.sub("\n• ", s)
        s = _BLOCK_START.sub("\n\n", s)
        s = _BLOCK_END.sub("\n\n", s)
        s = _TAGS.sub(" ", s)
    s = html.unescape(html.unescape(s))          # бывают дважды экранированные ленты
    s = _INVISIBLE.sub("", s.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [_SPACES.sub(" ", ln).strip() for ln in s.split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln:
            out.append(ln)
        elif out and out[-1] != "":
            out.append("")
    text = "\n".join(out).strip()
    for rx in _TAILS:
        text = rx.sub("", text).strip()
    return text


def one_line(s: str | None) -> str:
    """Свернуть в одну строку (заголовки)."""
    return _SPACES.sub(" ", html_to_text(s).replace("\n", " ")).strip()


# ─── ссылки ───────────────────────────────────────────────────────────────────

_TRACKING_PARAMS = {
    "fbclid", "gclid", "yclid", "dclid", "msclkid", "igshid", "mc_cid", "mc_eid", "_ga", "_gl",
    "ref", "ref_src", "ref_url", "cmpid", "cmp", "ncid", "sr_share", "spm", "share", "from",
    "rss", "feed", "output", "s_cid", "icid", "partner", "src",
}


def canonical_url(url: str | None) -> str:
    """Ключ для сравнения ссылок: без трекинга, www, фрагмента, лишних слешей и /amp."""
    if not url:
        return ""
    u = url.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
        return u
    try:
        parts = urlsplit(u)
    except ValueError:
        return u
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m.") and host.count(".") >= 2:
        host = host[2:]
    port = parts.port
    if port and port not in (80, 443):
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    path = re.sub(r"/amp/?$", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
             and k.lower() != "amp"]
    query.sort()
    return urlunsplit(("https", host, path, urlencode(query), ""))


# ─── отпечаток содержимого и язык ─────────────────────────────────────────────

def _norm_for_hash(s: str) -> str:
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def content_hash(title: str, text: str) -> str:
    """Отпечаток содержания: одинаковые тексты с разной разметкой дают один хеш."""
    h = hashlib.sha1()
    h.update(_norm_for_hash(title).encode("utf-8"))
    h.update(b"\x00")
    h.update(_norm_for_hash(text)[:5000].encode("utf-8"))
    return h.hexdigest()


def guess_lang(text: str) -> str:
    """Грубое определение языка: ru / en / '' (для решения, нужен ли перевод)."""
    sample = (text or "")[:2000]
    cyr = len(re.findall(r"[а-яёА-ЯЁ]", sample))
    lat = len(re.findall(r"[a-zA-Z]", sample))
    if cyr + lat < 20:
        return ""
    return "ru" if cyr >= lat else "en"
