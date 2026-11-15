"""
Space News Deduplicator
========================
Семантическая дедупликация новостей через эмбеддинги.

Основной движок — нейросеть paraphrase-multilingual-MiniLM-L12-v2 (понимает русский
и английский) в формате ONNX через fastembed: без torch, модель ~220 МБ скачивается
один раз в папку данных. Если модель недоступна (нет интернета при первом запуске) —
автоматически используется запасной вариант на TF-IDF (scikit-learn).
Алгоритм кластеризации одинаков для обоих бэкендов.

Структура «статьи» (dict) совместима с остальным проектом:
    {
        "published_at": "2024-06-15 08:30 UTC",
        "source_name":  "NASA",
        "title":        "...",
        "summary":      "...",
        "url":          "https://...",
        # служебные поля, добавляемые дедупликатором:
        "set_label":    "Парсер" | "Файл: news.csv",
        "set_kind":     "parser" | "file",
        "_idx":         <int>,   # стабильный индекс
    }

Тяжёлые зависимости (fastembed / onnxruntime / scikit-learn) импортируются ЛЕНИВО,
внутри функций, чтобы запуск приложения не тянул за собой нейросетевой стек.
"""
from __future__ import annotations

import csv
import io
import os
import re
import time
from typing import Callable, Optional

import numpy as np

# Многоязычная модель: та же, что и раньше (paraphrase-multilingual-MiniLM-L12-v2),
# но в формате ONNX через fastembed — без torch, ~220 МБ, скачивается один раз.
DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
FASTEMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Папка для моделей — задаёт приложение (data_dir/models).
MODELS_DIR: Optional[str] = None

# Кэш загруженной модели на процесс (загрузка — самый долгий шаг).
_MODEL_CACHE: dict = {}

LogFn = Optional[Callable[[str], None]]


def _log(log: LogFn, msg: str) -> None:
    if log:
        log(msg)


# ─── Подготовка текста ────────────────────────────────────────────────────────

def build_text(article: dict) -> str:
    """Текст для эмбеддинга: заголовок несёт основной смысл, аннотация уточняет."""
    title = (article.get("title") or "").strip()
    summary = (article.get("summary") or "").strip()
    text = f"{title}. {summary}".strip(" .")
    text = re.sub(r"\s+", " ", text)
    return text or title or summary


# ─── Нейросетевая модель: наличие и скачивание ──────────────────────────────

def neural_model_ready() -> bool:
    """Скачана ли ONNX-модель в папку моделей."""
    if not MODELS_DIR or not os.path.isdir(MODELS_DIR):
        return False
    for root, _dirs, files in os.walk(MODELS_DIR):
        if "paraphrase-multilingual-MiniLM-L12-v2" in root and any(f.endswith(".onnx") for f in files):
            return True
    return False


def neural_available() -> bool:
    """Установлен ли движок (fastembed) в этой сборке."""
    try:
        import fastembed  # noqa: F401
        return True
    except Exception:
        return False


_DOWNLOAD_FAILED_AT = 0.0      # когда последний раз не удалось скачать модель
_RETRY_AFTER = 15 * 60          # не пытаться качать снова раньше, чем через 15 мин


def _get_fastembed(log: LogFn, force: bool = False):
    global _DOWNLOAD_FAILED_AT
    from fastembed import TextEmbedding  # ленивый импорт
    model = _MODEL_CACHE.get("fastembed")
    if model is None:
        ready = neural_model_ready()
        if not ready and not force and time.time() - _DOWNLOAD_FAILED_AT < _RETRY_AFTER:
            raise RuntimeError("модель не скачана, а недавняя попытка скачать не удалась "
                               "(Настройки → Дедупликатор → «Скачать»)")
        _log(log, "Загрузка нейросетевой модели..." if ready
             else "Скачивание нейросетевой модели (~220 МБ, один раз)...")
        try:
            model = TextEmbedding(model_name=FASTEMBED_MODEL, cache_dir=MODELS_DIR)
        except Exception:
            if not ready:
                _DOWNLOAD_FAILED_AT = time.time()
            raise
        _MODEL_CACHE["fastembed"] = model
        _log(log, "Модель загружена.")
    return model


def download_neural_model(log: LogFn = None) -> None:
    """Скачать модель заранее (кнопка в Настройках)."""
    _get_fastembed(log, force=True)


# ─── Бэкенды эмбеддингов ───────────────────────────────────────────────────────

def _normalize(emb: np.ndarray) -> np.ndarray:
    emb = np.asarray(emb, dtype=np.float32)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return emb / norms


def _encode_neural(texts: list[str], model_name: str, log: LogFn):
    """ONNX (fastembed); если его нет, но установлен sentence-transformers — он."""
    try:
        model = _get_fastembed(log)
        _log(log, f"Векторизация {len(texts)} текстов (нейросеть, ONNX)...")
        return _normalize(np.array(list(model.embed(texts, batch_size=64)))), "neural"
    except ImportError:
        pass
    from sentence_transformers import SentenceTransformer  # ленивый импорт (режим разработки)
    model = _MODEL_CACHE.get(model_name)
    if model is None:
        _log(log, f"Загрузка модели «{model_name}» (sentence-transformers)...")
        model = SentenceTransformer(model_name)
        _MODEL_CACHE[model_name] = model
    _log(log, f"Векторизация {len(texts)} текстов (sentence-transformers)...")
    emb = model.encode(texts, batch_size=64, convert_to_numpy=True,
                       normalize_embeddings=True, show_progress_bar=False)
    return emb.astype(np.float32), "neural"


def _encode_tfidf(texts: list[str], log: LogFn):
    """Запасной вариант: TF-IDF. Матрица остаётся разреженной и уже L2-нормированной
    (раньше она разворачивалась в плотную и могла съедать гигабайты памяти)."""
    from sklearn.feature_extraction.text import TfidfVectorizer  # ленивый импорт

    _log(log, f"Векторизация {len(texts)} текстов (TF-IDF)...")
    vec = TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
        strip_accents="unicode",
        dtype=np.float32,
    )
    return vec.fit_transform(texts).tocsr()


def encode(texts: list[str], model_name: str, log: LogFn, engine: str = "auto"):
    """
    Возвращает (нормированные_векторы, имя_бэкенда).
    engine: auto — нейросеть, при любой ошибке TF-IDF; tfidf — сразу TF-IDF.
    """
    if not texts:
        return np.zeros((0, 1), dtype=np.float32), "none"
    if engine != "tfidf":
        try:
            emb, _ = _encode_neural(texts, model_name, log)
            return emb, "sentence-transformers"
        except Exception as e:  # нет модели / нет сети и т.п.
            _log(log, f"⚠ Нейросетевой движок недоступен ({str(e)[:90]}). Переход на TF-IDF.")
    return _encode_tfidf(texts, log), "tfidf"


# ─── Косинусная близость (плотные и разреженные матрицы) ───────────────────────

def _is_sparse(m) -> bool:
    return hasattr(m, "tocsr")


def _sims(block, vec) -> np.ndarray:
    """Косинус каждой строки block с вектором-строкой vec (всё уже нормировано)."""
    if _is_sparse(block):
        return np.asarray((block @ vec.T).toarray()).ravel()
    return block @ vec


def _row(m, i):
    return m[i] if not _is_sparse(m) else m[i:i + 1]


# ─── Выбор «оригинала» в кластере дублей ──────────────────────────────────────

def _kind_priority(article: dict, prefer_file_as_base: bool) -> int:
    """
    Приоритет «остаться оригиналом» по типу набора (МЕНЬШЕ = важнее):
      • файл-архив (если включён режим «файл — архив») — самый высокий;
      • сайты (парсер) — приоритетнее Telegram (по требованию);
      • Telegram;
      • обычный файл (когда он не помечен архивом) — самый низкий.
    """
    kind = article.get("set_kind")
    if kind == "file":
        return 0 if prefer_file_as_base else 3
    if kind == "parser":   # выгрузка с сайтов — приоритетная
        return 1
    if kind == "tg":
        return 2
    return 2


def _canonical_rank(article: dict, prefer_file_as_base: bool) -> tuple:
    """
    Чем МЕНЬШЕ кортеж, тем выше приоритет «остаться» (стать каноном кластера).
    Логика:
      1) приоритет по типу набора (см. _kind_priority): сайты важнее Telegram,
         файл-архив важнее всех;
      2) более ранняя дата публикации = первоисточник;
      3) при равенстве — более полная аннотация;
      4) стабильный индекс как финальный тай-брейкер (детерминизм).
    """
    date = (article.get("published_at") or "")[:16]  # YYYY-MM-DD HH:MM
    # пустую дату отправляем в конец (большая строка), чтобы датированные были «оригиналами»
    date_key = date if date else "9999-99-99 99:99"

    summary_len = len(article.get("summary") or "")
    return (_kind_priority(article, prefer_file_as_base), date_key,
            -summary_len, article.get("_idx", 0))


# ─── Ядро: жадная near-duplicate кластеризация по косинусной близости ─────────

def _dedup_pool(
    articles: list[dict],
    embeddings: np.ndarray,
    threshold: float,
    prefer_file_as_base: bool,
) -> tuple[list[dict], list[dict]]:
    """
    Дедупликация одного «пула» статей.
    Возвращает (kept, removed), где каждый removed содержит:
        duplicate_of  — каноническая статья, к которой он отнесён,
        similarity    — косинусная близость к ней.
    """
    n = len(articles)
    if n == 0:
        return [], []
    if n == 1:
        return [articles[0]], []

    # Порядок обработки: «лучшие кандидаты в оригинал» идут первыми.
    order = sorted(range(n), key=lambda i: _canonical_rank(articles[i], prefer_file_as_base))

    kept_pos: list[int] = []          # позиции (в исходном массиве) оставленных статей
    removed: list[dict] = []

    for i in order:
        if not kept_pos:
            kept_pos.append(i)
            continue
        # косинус к уже оставленным (эмбеддинги нормированы → dot == cos)
        sims = _sims(embeddings[kept_pos], _row(embeddings, i))
        best_local = int(np.argmax(sims))
        best_score = float(sims[best_local])
        if best_score >= threshold:
            canon = articles[kept_pos[best_local]]
            dup = dict(articles[i])
            dup["duplicate_of"] = {
                "title":       canon.get("title", ""),
                "summary":     canon.get("summary", ""),
                "source_name": canon.get("source_name", ""),
                "published_at": canon.get("published_at", ""),
                "url":         canon.get("url", ""),
                "set_label":   canon.get("set_label", ""),
                "_item_id":    canon.get("_item_id"),
            }
            dup["similarity"] = round(best_score, 4)
            removed.append(dup)
        else:
            kept_pos.append(i)

    kept = [articles[p] for p in kept_pos]
    return kept, removed


# ─── Парсинг входного CSV ──────────────────────────────────────────────────────

# Возможные имена столбцов (рус/англ), приводятся к нижнему регистру.
_COL_ALIASES = {
    "published_at": ["дата", "date", "published", "published_at", "pubdate", "время"],
    "source_name":  ["источник", "source", "source_name", "издание"],
    "title":        ["заголовок", "title", "headline", "название"],
    "summary":      ["новость", "summary", "description", "текст", "аннотация", "content"],
    "url":          ["ссылка", "url", "link", "href"],
}


def _match_header(headers: list[str]) -> dict:
    """Сопоставляет реальные заголовки CSV с полями статьи по именам."""
    norm = [h.strip().lower().lstrip("\ufeff") for h in headers]
    mapping: dict[str, int] = {}
    for field, aliases in _COL_ALIASES.items():
        for idx, h in enumerate(norm):
            if h in aliases and field not in mapping:
                mapping[field] = idx
                break
    return mapping


def parse_csv_articles(file_bytes: bytes, set_label: str) -> list[dict]:
    """
    Разбирает загруженный CSV (UTF-8 / UTF-8-BOM, разделитель , или ;) в список статей.
    Понимает заголовки по именам столбцов; если не распознаны — берёт по позициям
    (Дата, Источник, Заголовок, Новость, Ссылка) либо 4 столбца без даты.
    """
    text = file_bytes.decode("utf-8-sig", errors="replace")

    # Определяем разделитель.
    sample = text[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except Exception:
        if sample.count(";") > sample.count(","):
            delimiter = ";"

    reader = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        return []

    header = rows[0]
    mapping = _match_header(header)
    has_header = len(mapping) >= 2  # распознали хотя бы 2 столбца → первая строка это шапка
    data_rows = rows[1:] if has_header else rows

    def cell(row: list[str], field: str, positional: int) -> str:
        if field in mapping and mapping[field] < len(row):
            return (row[mapping[field]] or "").strip()
        if not has_header and 0 <= positional < len(row):
            return (row[positional] or "").strip()
        return ""

    # Позиционная схема: 5 столбцов (с датой) или 4 (без даты).
    width = max((len(r) for r in data_rows), default=0)
    if not has_header and width <= 4:
        pos = {"source_name": 0, "title": 1, "summary": 2, "url": 3, "published_at": -1}
    else:
        pos = {"published_at": 0, "source_name": 1, "title": 2, "summary": 3, "url": 4}

    articles: list[dict] = []
    for row in data_rows:
        art = {
            "published_at": cell(row, "published_at", pos["published_at"]),
            "source_name":  cell(row, "source_name",  pos["source_name"]) or "—",
            "title":        cell(row, "title",        pos["title"]),
            "summary":      cell(row, "summary",      pos["summary"]),
            "url":          cell(row, "url",          pos["url"]),
            "set_label":    set_label,
            "set_kind":     "file",
        }
        if art["title"] or art["summary"]:
            articles.append(art)
    return articles


# ─── Главная функция ───────────────────────────────────────────────────────────

def run_deduplication(
    parser_articles: Optional[list[dict]] = None,
    file_groups: Optional[list[dict]] = None,
    tg_articles: Optional[list[dict]] = None,
    reference_articles: Optional[list[dict]] = None,
    reference_label: str = "Недельная база",
    threshold: float = 0.82,
    cross_compare: bool = True,
    prefer_file_as_base: bool = True,
    model_name: str = DEFAULT_MODEL,
    engine: str = "auto",
    log: LogFn = None,
    encoder: Optional[Callable] = None,
    ref_threshold: Optional[float] = None,
) -> dict:
    """
    Запускает дедупликацию.

    parser_articles      — статьи из парсера сайтов (или None).
    tg_articles          — статьи из Telegram-парсера (или None).
    file_groups          — список {"label": str, "articles": [...]} из CSV-файлов.
    reference_articles   — ЭТАЛОН для сравнения (напр. недельная база). Эти статьи
                           НЕ попадают в результат и не меняются: всё, что в выгрузке
                           совпало с эталоном, выкидывается из выгрузки.
    threshold            — порог косинусной близости (выше → строже считаем дублем).
    cross_compare        — True: все включённые наборы объединяются и сверяются
                           перекрёстно; False: каждый набор чистится отдельно,
                           затем результаты складываются.
    prefer_file_as_base  — при совпадении с файлом оставлять запись из файла
                           (файл трактуется как архив известных новостей).
    encoder              — свой способ получить векторы: encoder(статьи, тексты, log) →
                           (векторы, имя_бэкенда); например, с кэшем в базе. По умолчанию encode().
    ref_threshold        — отдельный порог для сверки с эталоном (по умолчанию = threshold).

    Приоритет «оригинала» при перекрёстной сверке: файл-архив > сайты > Telegram.

    Возвращает dict с ключами: kept, removed, stats, backend.
    """
    # Собираем наборы и нумеруем стабильным индексом.
    sets: list[list[dict]] = []
    labels: list[str] = []

    if parser_articles:
        block = []
        for a in parser_articles:
            a = dict(a)
            a["set_label"] = "Сайты"
            a["set_kind"] = "parser"
            block.append(a)
        sets.append(block)
        labels.append("Сайты")

    if tg_articles:
        block = []
        for a in tg_articles:
            a = dict(a)
            a["set_label"] = "Telegram"
            a["set_kind"] = "tg"
            block.append(a)
        sets.append(block)
        labels.append("Telegram")

    for g in (file_groups or []):
        block = []
        for a in g.get("articles", []):
            a = dict(a)
            a.setdefault("set_label", g.get("label", "Файл"))
            a["set_kind"] = "file"
            block.append(a)
        if block:
            sets.append(block)
            labels.append(g.get("label", "Файл"))

    all_articles = [a for block in sets for a in block]
    for i, a in enumerate(all_articles):
        a["_idx"] = i

    total_in = len(all_articles)
    _log(log, f"На входе: {total_in} новостей из {len(sets)} наборов "
              f"({', '.join(labels) or 'нет данных'}).")

    if total_in == 0:
        return {"kept": [], "removed": [], "backend": "none",
                "stats": {"total_in": 0, "kept": 0, "removed": 0,
                          "cross_compare": cross_compare}}

    # Один раз векторизуем все тексты (даже в раздельном режиме — переиспользуем).
    # Эталонные тексты кодируем В ТОМ ЖЕ вызове, чтобы вектора были в одном
    # пространстве (важно для запасного TF-IDF, где словарь строится на лету).
    texts = [build_text(a) for a in all_articles]
    n_main = len(texts)
    ref_list = reference_articles or []
    if ref_list:
        texts = texts + [build_text(a) for a in ref_list]
    if encoder is not None:
        embeddings_all, backend = encoder(all_articles + list(ref_list), texts, log)
    else:
        embeddings_all, backend = encode(texts, model_name, log, engine=engine)
    embeddings = embeddings_all[:n_main]
    ref_emb = embeddings_all[n_main:] if ref_list else None

    _log(log, f"Бэкенд: {backend}. Порог близости: {threshold}. "
              f"Режим: {'перекрёстная сверка' if cross_compare else 'раздельно по наборам'}.")

    kept: list[dict] = []
    removed: list[dict] = []

    if cross_compare or len(sets) == 1:
        # Все статьи в общий пул.
        kept, removed = _dedup_pool(all_articles, embeddings, threshold, prefer_file_as_base)
    else:
        # Каждый набор чистится независимо; эмбеддинги берём по _idx.
        for block, label in zip(sets, labels):
            idxs = [a["_idx"] for a in block]
            sub_emb = embeddings[idxs]
            # переиндексация для _dedup_pool: используем локальные позиции
            sub_articles = block
            # подменим _idx на локальный для корректного тай-брейка внутри набора
            k, r = _dedup_pool(sub_articles, sub_emb, threshold, prefer_file_as_base)
            kept.extend(k)
            removed.extend(r)
            _log(log, f"  «{label}»: оставлено {len(k)}, убрано {len(r)}.")

    # ── Сверка с ЭТАЛОНОМ (недельная база): выкидываем из выгрузки всё, что уже
    #    есть в эталоне. Эталон в результат не попадает и не изменяется. ──
    ref_removed_count = 0
    ref_thr = threshold if ref_threshold is None else ref_threshold
    if ref_list and ref_emb is not None:
        survivors, ref_removed = [], []
        for a in kept:
            sims = _sims(ref_emb, _row(embeddings, a["_idx"]))
            best = int(np.argmax(sims)) if len(sims) else -1
            if best >= 0 and float(sims[best]) >= ref_thr:
                ref = ref_list[best]
                dup = dict(a)
                dup["duplicate_of"] = {
                    "title":        ref.get("title", ""),
                    "summary":      ref.get("summary", ""),
                    "source_name":  ref.get("source_name", ""),
                    "published_at": ref.get("published_at", ""),
                    "url":          ref.get("url", ""),
                    "set_label":    reference_label,
                    "_item_id":     ref.get("_item_id"),
                }
                dup["similarity"] = round(float(sims[best]), 4)
                dup["removed_by_reference"] = True
                ref_removed.append(dup)
            else:
                survivors.append(a)
        kept = survivors
        removed.extend(ref_removed)
        ref_removed_count = len(ref_removed)
        _log(log, f"Сверка с «{reference_label}»: убрано {ref_removed_count} "
                  f"уже известных новостей (эталон не изменялся).")

    # Сортировка результата по дате (как в основном экспорте).
    kept.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    removed.sort(key=lambda x: x.get("similarity", 0), reverse=True)

    stats = {
        "total_in":      total_in,
        "kept":          len(kept),
        "removed":       len(removed),
        "cross_compare": cross_compare,
        "threshold":     threshold,
        "backend":       backend,
        "removed_by_reference": ref_removed_count,
        "sets":          [{"label": l, "count": len(b)} for l, b in zip(labels, sets)],
    }
    _log(log, f"Готово. Оставлено {len(kept)}, удалено дублей {len(removed)}.")

    return {"kept": kept, "removed": removed, "stats": stats, "backend": backend}

