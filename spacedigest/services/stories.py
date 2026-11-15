"""
Сюжет = одно событие из нескольких источников.

В CSV для ChatGPT сюжет — одна строка: полный текст основной версии плюс те предложения
других версий, которых в основной нет (цифры, сроки, компании, цитаты). Так повторы не
съедают факты, а ChatGPT не тратит силы на одинаковые тексты.

Новизна предложения считается без нейросети, по словам: предложение «новое», если ни одно
предложение основной версии (и уже добавленных) не совпадает с ним по словам на 60 % и больше.
"""
from __future__ import annotations

import re

MIN_SENTENCE = 25          # короче — подписи, хэштеги, «Подробнее:»
MAX_EXTRA_PER_SOURCE = 1200
MAX_EXTRA_TOTAL = 3000
SIMILAR = 0.6

_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_WORD = re.compile(r"[\w\-]+", re.UNICODE)
# Служебные фразы: призывы подписаться, реклама, подписи к фото — фактов в них нет.
_NOISE = re.compile(r"(подпи[сш]|присоединяйтесь|наш[а-я]* канал|в курсе событий|подробнее|"
                    r"читать (далее|полностью)|read more|subscribe|follow us|реклама|erid|"
                    r"источник:|фото:|photo:|the post .* appeared first|^#|^@)", re.IGNORECASE)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SPLIT.split(text or "") if s and s.strip()]


def _words(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if len(w) > 2 or w.isdigit()}


def _is_noise(s: str) -> bool:
    if len(s) < MIN_SENTENCE or _NOISE.search(s):
        return True
    words = s.split()
    links = sum(1 for w in words if w.startswith(("http", "@", "#", "t.me/")))
    return links * 2 >= len(words)


def novel_sentences(base_texts: list[str], other: str) -> list[str]:
    """Предложения из other, которых по смыслу (по словам) нет в base_texts."""
    known = [_words(s) for t in base_texts for s in sentences(t)]
    known = [k for k in known if k]
    out: list[str] = []
    for s in sentences(other):
        if _is_noise(s):
            continue
        w = _words(s)
        if not w:
            continue
        if any(len(w & k) / len(w) >= SIMILAR for k in known):
            continue
        out.append(s)
        known.append(w)
    return out


def _clip(parts: list[str], limit: int) -> str:
    text, total = [], 0
    for p in parts:
        if total + len(p) > limit:
            break
        text.append(p)
        total += len(p) + 1
    return " ".join(text)


def merge_text(main_text: str, others: list[tuple[str, str]]) -> tuple[str, list[int]]:
    """main_text + «[Дополнительно: Источник] новые предложения» для каждой другой версии.
    others — [(название источника, полный текст)], в порядке важности.
    Возвращает (текст, сколько символов добавила каждая версия)."""
    blocks, base, budget, added = [main_text.strip()], [main_text], MAX_EXTRA_TOTAL, []
    for source, text in others:
        extra = _clip(novel_sentences(base, text), min(MAX_EXTRA_PER_SOURCE, budget)) if budget > 0 else ""
        added.append(len(extra))
        if not extra:
            continue
        blocks.append(f"[Дополнительно: {source}]\n{extra}")
        base.append(extra)
        budget -= len(extra)
    return "\n\n".join(b for b in blocks if b), added
