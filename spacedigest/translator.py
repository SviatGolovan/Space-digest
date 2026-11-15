"""
Translator — перевод новостей на русский язык.
===============================================
Провайдеры:
  • google — deep-translator / GoogleTranslator. Бесплатно, без ключа,
    автоопределение языка источника. Качество хорошее.
  • deepl  — deep-translator / DeeplTranslator. Профессиональное качество,
    требуется API-ключ (есть бесплатный тариф ~500 000 символов/мес).

Особенности:
  • Кэш переводов на процесс (одинаковый текст не переводится дважды) —
    ускоряет повторы и экономит лимиты API.
  • Пакетная отправка уникальных текстов.
  • Мягкая деградация: при любой ошибке (нет интернета, неверный ключ,
    лимит) возвращается ОРИГИНАЛ, приложение не падает.
  • Прогресс через callback.

Тяжёлые зависимости импортируются лениво, внутри функций.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

LogFn = Optional[Callable[[str], None]]
ProgressFn = Optional[Callable[[int, int], None]]  # (готово, всего)

# Кэш переводов: (provider, target, text) -> перевод
_CACHE: dict[tuple, str] = {}

# Лимит длины одного текста (Google ~5000 символов на запрос).
_MAX_LEN = 4800
# Размер пакета для translate_batch.
_BATCH = 20


def _log(log: LogFn, msg: str) -> None:
    if log:
        log(msg)


def _make_engine(provider: str, target: str, deepl_key: Optional[str]):
    """Ленивая инициализация движка перевода. Бросает исключение, если недоступно."""
    if provider == "deepl":
        from deep_translator import DeeplTranslator  # ленивый импорт
        if not deepl_key:
            raise ValueError("для DeepL нужен API-ключ")
        return DeeplTranslator(api_key=deepl_key, source="auto", target=target)
    from deep_translator import GoogleTranslator  # ленивый импорт
    return GoogleTranslator(source="auto", target=target)


class Translator:
    def __init__(self, provider: str = "google", target: str = "ru",
                 deepl_key: Optional[str] = None, log: LogFn = None):
        self.provider = provider if provider in ("google", "deepl") else "google"
        self.target = target
        self.deepl_key = deepl_key
        self.log = log
        self.available = True
        self._engine = None

    # ── низкоуровневый перевод списка строк (с кэшем и фолбэком) ──
    def _engine_lazy(self):
        if self._engine is None:
            self._engine = _make_engine(self.provider, self.target, self.deepl_key)
        return self._engine

    def _translate_batch_raw(self, texts: list[str]) -> list[str]:
        """
        Переводит пачку непустых строк. При ошибке пакета — пробует по одной.
        Если НЕ удалось перевести вообще ничего — бросает исключение
        (это сигнал «движок недоступен», обрабатывается уровнем выше).
        """
        engine = self._engine_lazy()  # может бросить (нет пакета / неверный ключ)
        try:
            out = engine.translate_batch(texts)
            return [o if o else src for o, src in zip(out, texts)]
        except Exception:
            result = []
            failures = 0
            for t in texts:
                try:
                    r = engine.translate(t)
                    result.append(r or t)
                except Exception:
                    failures += 1
                    result.append(t)  # временный фолбэк — оригинал
            if texts and failures == len(texts):
                raise RuntimeError("движок перевода недоступен")
            return result

    def translate_strings(self, texts: list[str],
                          progress: ProgressFn = None) -> dict[str, str]:
        """
        Переводит набор строк. Возвращает словарь {оригинал: перевод}.
        Пустые строки и уже закэшированные не отправляются повторно.
        """
        # Уникальные непустые тексты, которых ещё нет в кэше.
        uniq: list[str] = []
        seen: set[str] = set()
        for t in texts:
            t = (t or "").strip()
            if not t or t in seen:
                continue
            seen.add(t)
            key = (self.provider, self.target, t)
            if key not in _CACHE:
                uniq.append(t)

        total = len(uniq)
        done = 0
        if total and not self.available:
            # уже знаем, что движок недоступен — не пытаемся
            return {}

        for start in range(0, total, _BATCH):
            chunk = [t[:_MAX_LEN] for t in uniq[start:start + _BATCH]]
            try:
                translated = self._translate_batch_raw(chunk)
            except Exception as e:
                # Полный отказ движка (нет сети/пакета) — прекращаем, оставляем оригиналы.
                self.available = False
                _log(self.log, f"⚠ Перевод недоступен ({str(e)[:90]}). Оставляю оригиналы.")
                break
            for src_full, src_cut, tr in zip(uniq[start:start + _BATCH], chunk, translated):
                _CACHE[(self.provider, self.target, src_full)] = tr or src_full
            done += len(chunk)
            if progress:
                progress(done, total)

        # Собираем ответ ТОЛЬКО из успешно переведённого (есть в кэше).
        # Непереведённые строки не попадают в словарь → поля '_ru' для них
        # не заполняются, и в интерфейсе останется оригинал с явной пометкой в логе.
        result: dict[str, str] = {}
        for t in texts:
            tt = (t or "").strip()
            if tt:
                key = (self.provider, self.target, tt)
                if key in _CACHE:
                    result[tt] = _CACHE[key]
        return result

    # ── перевод полей статей ──
    def translate_articles(self, articles: list[dict],
                           fields: tuple = ("title", "summary"),
                           include_duplicate_of: bool = False,
                           progress: ProgressFn = None) -> int:
        """
        Заполняет у статей поля '<field>_ru'. Если include_duplicate_of — также
        переводит заголовок в article['duplicate_of']['title'] → ['title_ru'].
        Возвращает число переведённых уникальных строк.
        """
        # Собираем все тексты для перевода.
        texts: list[str] = []
        for a in articles:
            for f in fields:
                texts.append(a.get(f, ""))
            if include_duplicate_of:
                d = a.get("duplicate_of") or {}
                texts.append(d.get("title", ""))
                texts.append(d.get("summary", ""))

        mapping = self.translate_strings(texts, progress=progress)
        if not mapping:
            return 0

        for a in articles:
            for f in fields:
                src = (a.get(f) or "").strip()
                if src:
                    a[f + "_ru"] = mapping.get(src, src)
            if include_duplicate_of and a.get("duplicate_of"):
                d = a["duplicate_of"]
                dt = (d.get("title") or "").strip()
                if dt:
                    d["title_ru"] = mapping.get(dt, dt)
                ds = (d.get("summary") or "").strip()
                if ds:
                    d["summary_ru"] = mapping.get(ds, ds)

        return len(mapping)


def make_translator(provider: str = "google", deepl_key: Optional[str] = None,
                    target: str = "ru", log: LogFn = None) -> Translator:
    """Удобная фабрика: если задан ключ DeepL — используем DeepL, иначе Google."""
    if deepl_key:
        provider = "deepl"
    return Translator(provider=provider, target=target, deepl_key=deepl_key, log=log)
