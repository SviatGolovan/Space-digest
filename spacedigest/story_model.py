"""
Модель «один сюжет»: multilingual-e5-small (ONNX, int8, ~120 МБ) для столбца «Связанные строки».

Почему отдельная модель. Склейку повторов делает MiniLM (deduplicator.py) — она точная,
но пропускает новости об одном событии, написанные разными словами. Замер на выгрузках
ноября 2026 (bench/) показал: e5-small по заголовкам лучше всех в бюджете находит такие
пары, в том числе русский ↔ английский, но с теми же «соседними» событиями (анонс и итог
пуска) она тоже близка. Поэтому её ответ — не склейка, а подсказка: строки одного сюжета
отмечаются номерами, решает ChatGPT по промпту.

Работает на onnxruntime + tokenizers (идут вместе с fastembed), без PyTorch.
Файлы модели: в установщике — <ресурсы>/models/multilingual-e5-small; иначе скачиваются
один раз в <данные>/models/multilingual-e5-small (Hugging Face, репозиторий Xenova).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

MODEL_ID = "multilingual-e5-small"
HF_REPO = "Xenova/multilingual-e5-small"
FILES = {"model.onnx": "onnx/model_quantized.onnx", "tokenizer.json": "tokenizer.json"}
PREFIX = "query: "                 # e5 обучена с префиксом; для сравнения текстов — query:
MAX_TOKENS = 128
LogFn = Optional[Callable[[str], None]]

_lock = threading.Lock()
_cache: dict = {}


def bundled_dir() -> Path:
    from .paths import resource_dir
    return resource_dir() / "models" / MODEL_ID


def user_dir() -> Path:
    from . import deduplicator
    base = Path(deduplicator.MODELS_DIR) if deduplicator.MODELS_DIR else Path.home() / ".spacedigest-models"
    return base / MODEL_ID


def model_dir() -> Optional[Path]:
    for d in (bundled_dir(), user_dir()):
        if all((d / name).is_file() for name in FILES):
            return d
    return None


def ready() -> bool:
    return model_dir() is not None


def download(target: Optional[Path] = None, log: LogFn = None) -> Path:
    """Скачать файлы модели (сборка установщика или первый запуск без встроенной модели)."""
    from huggingface_hub import hf_hub_download
    target = Path(target) if target else user_dir()
    target.mkdir(parents=True, exist_ok=True)
    for name, remote in FILES.items():
        if (target / name).is_file():
            continue
        if log:
            log(f"Скачивание модели сюжетов: {remote}…")
        got = hf_hub_download(HF_REPO, remote)
        tmp = target / (name + ".part")
        with open(got, "rb") as src, open(tmp, "wb") as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)
        os.replace(tmp, target / name)
    return target


def _load(log: LogFn = None):
    with _lock:
        if "session" in _cache:
            return _cache["session"], _cache["tokenizer"]
        d = model_dir()
        if d is None:
            if os.environ.get("SPACEDIGEST_NO_MODEL_DOWNLOAD"):        # тесты и сборка: без сети
                raise RuntimeError("модель сюжетов не установлена")
            d = download(log=log)
        import onnxruntime as ort
        from tokenizers import Tokenizer
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) - 1))   # окну — свободное ядро
        session = ort.InferenceSession(str(d / "model.onnx"), opts, providers=["CPUExecutionProvider"])
        tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        tok.enable_truncation(MAX_TOKENS)
        tok.enable_padding(pad_id=tok.token_to_id("<pad>") or 1, pad_token="<pad>")
        _cache.update(session=session, tokenizer=tok)
        return session, tok


def encode(texts: list[str], log: LogFn = None, batch: int = 32) -> np.ndarray:
    """Нормированные векторы (N × 384): mean pooling по маске, как в sentence-transformers."""
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    session, tok = _load(log)
    names = {i.name for i in session.get_inputs()}
    out = []
    for k in range(0, len(texts), batch):
        enc = tok.encode_batch([PREFIX + (t or "") for t in texts[k:k + batch]])
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in names:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = session.run(None, feed)[0]                       # (B, L, 384)
        m = mask[..., None].astype(np.float32)
        vec = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
        vec /= np.clip(np.linalg.norm(vec, axis=1, keepdims=True), 1e-12, None)
        out.append(vec.astype(np.float32))
    return np.vstack(out)


if __name__ == "__main__":                                        # сборка: python -m spacedigest.story_model <папка>
    import sys
    path = download(Path(sys.argv[1]) if len(sys.argv) > 1 else None, log=print)
    v = encode(["SpaceX catches Starship", "SpaceX поймала Starship башней", "Курс рубля"])
    print(path, "sims:", round(float(v[0] @ v[1]), 3), round(float(v[0] @ v[2]), 3))
