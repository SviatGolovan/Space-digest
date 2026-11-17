"""
Замер дедупликатора на размеченных парах из реальных выгрузок (bench/pairs_*.json).

Данные: CSV выгрузок в bench/data/ и разметка пар по ссылкам в bench/labels_*.json.
Запуск — GitHub Actions → «Dedup benchmark» (запускается сам, когда меняется bench/) или локально:
    pip install sentence-transformers numpy
    python bench/dedup_bench.py bench --out bench/results

Что сравнивается:
  * модели (Sentence-Transformers): текущая MiniLM и более сильные многоязычные;
  * какой текст сравнивать: заголовок; заголовок + начало текста (~как сейчас: заголовок + анонс);
    заголовок + больше текста;
  * предохранители: окно по датам и «разные номера в заголовках — не склеивать».

Метрики (на размеченных парах; same — одно событие, diff — разные, related — один сюжет):
  найдено повторов (recall по same), ложные склейки (diff выше порога), сколько related склеено,
  и по всему корпусу — сколько неразмеченных пар выше порога (их нужно доразметить).
Итог — таблица в $GITHUB_STEP_SUMMARY и JSON с неразмеченными парами для доразметки.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

import numpy as np

MODELS = [
    # (имя, префикс для текстов, примерный вес ONNX int8 в установщике, комментарий)
    ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "", 120, "текущая"),
    ("intfloat/multilingual-e5-small", "query: ", 120, ""),
    ("intfloat/multilingual-e5-base", "query: ", 280, ""),
    ("sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "", 280, ""),
    ("sentence-transformers/LaBSE", "", 470, "тяжелее бюджета"),
    ("BAAI/bge-m3", "", 570, "тяжелее бюджета, для сравнения"),
]
TEXTS = {
    "title": lambda r: r["title"],
    "title+300": lambda r: f"{r['title']}. {r['text'][:300]}",     # ≈ как сейчас: заголовок + анонс
    "title+800": lambda r: f"{r['title']}. {r['text'][:800]}",
}
YEAR = re.compile(r"^(19|20)\d\d$")


def numbers(title: str) -> set[str]:
    return {n for n in re.findall(r"\b\d+(?:[.,]\d+)?\b", title or "") if not YEAR.match(n)}


def guard_numbers(a: dict, b: dict) -> bool:
    """True — склеивать можно. Разные номера в обоих заголовках (миссия 98 / 99) — нельзя."""
    na, nb = numbers(a["title"]), numbers(b["title"])
    return not (na and nb and not (na & nb))


def days_apart(a: dict, b: dict) -> float:
    fa, fb = (datetime.fromisoformat(x["date"].replace(" ", "T")[:16]) for x in (a, b))
    return abs((fa - fb).total_seconds()) / 86400


def encode(model_name: str, prefix: str, texts: list[str]) -> np.ndarray:
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(model_name, device="cpu")
    emb = m.encode([prefix + t for t in texts], batch_size=32, normalize_embeddings=True,
                   show_progress_bar=False, convert_to_numpy=True)
    return emb.astype(np.float32)


def evaluate(items, pairs, emb, window_days, use_guard):
    sims = emb @ emb.T
    lab = {}
    for p in pairs:
        lab[(min(p["a"], p["b"]), max(p["a"], p["b"]))] = p["label"]
    n = len(items)
    # все пары корпуса в окне дат (для «неразмеченных выше порога»)
    ts = np.array([datetime.fromisoformat(x["date"].replace(" ", "T")[:16]).timestamp() for x in items]) / 86400
    allowed = np.triu(np.abs(ts[:, None] - ts[None, :]) <= window_days, 1)
    if use_guard:
        nums = [numbers(x["title"]) for x in items]
        for i, j in np.argwhere(allowed & (sims >= 0.5)):
            if nums[i] and nums[j] and not (nums[i] & nums[j]):
                allowed[i, j] = False
    rows = []
    for thr in np.round(np.arange(0.55, 0.99, 0.01), 2):
        tp = fn = fp = rel = 0
        for (a, b), l in lab.items():
            hit = int(bool(allowed[a, b]) and float(sims[a, b]) >= thr)
            if l == "same":
                tp += hit; fn += not hit
            elif l == "diff":
                fp += hit
            else:
                rel += hit
        above = np.argwhere(np.triu(allowed & (sims >= thr), 1))
        unl = int(sum(1 for a, b in above if (int(a), int(b)) not in lab))
        rows.append({"thr": float(thr), "tp": tp, "fn": fn, "fp": fp, "related": rel, "unlabeled_above": unl})
    return sims, allowed, rows


def best_story(rows):
    """«Один сюжет»: находка — same или related, ошибка — diff. Подсказка, поэтому ошибка весит как пропуск."""
    return max(rows, key=lambda r: (r["tp"] + r["related"] - r["fp"], -r["fp"]))


def best(rows, n_same):
    """Порог с лучшим F (ложная склейка в 1,5 раза хуже пропуска — как в «Подборе порога»)."""
    def score(r):
        cost = r["fn"] + 1.5 * r["fp"]
        return (-cost, r["tp"])
    return max(rows, key=score)


def load(folder: str) -> tuple[list[dict], list[dict]]:
    """Новости из всех CSV в data/ (одна строка на ссылку, без SCMP) и пары из labels_*.json."""
    import csv
    import glob
    items, by_url = [], {}
    for path in sorted(glob.glob(os.path.join(folder, "data", "*.csv")), key=os.path.getsize, reverse=True):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                url = r.get("Ссылка") or ""
                if not url or url in by_url or (r.get("Источник") or "").startswith("South China"):
                    continue
                by_url[url] = len(items)
                items.append({"date": r["Дата публикации"], "source": r["Источник"], "title": r["Заголовок"],
                              "text": (r.get("Полный текст") or "")[:1500], "url": url})
    pairs, missing = [], 0
    for path in sorted(glob.glob(os.path.join(folder, "labels_*.json"))):
        for p in json.load(open(path, encoding="utf-8"))["pairs"]:
            if p["a"] in by_url and p["b"] in by_url:
                pairs.append({"a": by_url[p["a"]], "b": by_url[p["b"]], "label": p["label"]})
            else:
                missing += 1
    if missing:
        print(f"Пар без новости в CSV: {missing}")
    return items, pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="папка bench/ (data/*.csv и labels_*.json)")
    ap.add_argument("--out", default="bench/results")
    ap.add_argument("--models", default="all", help="через запятую номера моделей (0 — текущая)")
    args = ap.parse_args()
    items, pairs = load(args.folder)
    os.makedirs(args.out, exist_ok=True)
    n_same = sum(p["label"] == "same" for p in pairs)
    n_rel = sum(p["label"] == "related" for p in pairs)
    n_diff = sum(p["label"] == "diff" for p in pairs)
    pick = range(len(MODELS)) if args.models == "all" else [int(x) for x in args.models.split(",")]
    print(f"Новостей {len(items)}, пар {len(pairs)}: одно событие {n_same}, "
          f"один сюжет {sum(p['label'] == 'related' for p in pairs)}, разные {sum(p['label'] == 'diff' for p in pairs)}")
    results, review = [], []
    for mi in pick:
        name, prefix, size, note = MODELS[mi]
        for tname, tf in TEXTS.items():
            if size > 470 and tname != "title+300":
                continue                                      # тяжёлые — только для справки
            t0 = time.time()
            try:
                emb = encode(name, prefix, [tf(r) for r in items])
            except Exception as e:                                         # noqa: BLE001
                print(f"!! {name}: {e}")
                break
            secs = time.time() - t0
            for window, guard in ((365, False), (4, False), (4, True)):
                sims, allowed, rows = evaluate(items, pairs, emb, window, guard)
                b = best(rows, n_same)
                cur = next(r for r in rows if abs(r["thr"] - 0.82) < 1e-6)
                res = {"model": name, "note": note, "size_mb": size, "text": tname,
                       "window": window, "guard": guard, "encode_s": round(secs, 1),
                       "at_082": cur, "best": b, "best_story": best_story(rows), "curve": rows}
                results.append(res)
                print(f"{name.split('/')[-1]:<44} {tname:<10} окно={window:<3} предохр={'да' if guard else 'нет'} | "
                      f"0.82: найдено {cur['tp']}/{n_same}, ложных {cur['fp']} | "
                      f"лучший {b['thr']:.2f}: найдено {b['tp']}/{n_same}, ложных {b['fp']}, "
                      f"сюжет {b['related']}, неразмеч. {b['unlabeled_above']}")
                if window == 4 and guard:
                    above = np.argwhere(np.triu(allowed & (sims >= b["thr"]), 1))
                    lab = {(min(p["a"], p["b"]), max(p["a"], p["b"])) for p in pairs}
                    for a, c in above:
                        if (int(a), int(c)) not in lab:
                            review.append({"model": name, "text": tname, "sim": round(float(sims[a, c]), 3),
                                           "a": int(a), "b": int(c), "a_title": items[a]["title"],
                                           "b_title": items[c]["title"]})
    json.dump({"results": results, "to_label": review},
              open(os.path.join(args.out, "result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    for summ in filter(None, (os.environ.get("GITHUB_STEP_SUMMARY"), os.path.join(args.out, "result.md"))):
        with open(summ, "a" if summ != os.path.join(args.out, "result.md") else "w", encoding="utf-8") as f:
            f.write(f"## Замер дедупликатора\n\nПар «одно событие»: {n_same}. Ложная склейка весит 1,5 пропуска.\n\n")
            f.write("| Модель | Текст | Окно, дн | Предохр. | При 0.82: найдено / ложных | Лучший порог | Найдено | Ложных | Сюжет склеено | Неразмеч. выше порога |\n")
            f.write("|---|---|---|---|---|---|---|---|---|---|\n")
            for r in results:
                b, c = r["best"], r["at_082"]
                f.write(f"| {r['model'].split('/')[-1]} {r['note']} | {r['text']} | {r['window'] if r['window'] < 365 else '—'} | "
                        f"{'да' if r['guard'] else 'нет'} | {c['tp']} / {c['fp']} | {b['thr']:.2f} | {b['tp']} | {b['fp']} | "
                        f"{b['related']} | {b['unlabeled_above']} |\n")
            f.write(f"\n## Один сюжет (столбец «Связанные строки»)\n\nНаходка — пара «одно событие» ({n_same}) или "
                    f"«один сюжет» ({n_rel}); ошибка — «разные» ({n_diff}). Только окно 4 дня с предохранителем.\n\n")
            f.write("| Модель | Текст | Порог | Одно событие | Один сюжет | Всего найдено | Ошибок | Неразмеч. выше порога |\n")
            f.write("|---|---|---|---|---|---|---|---|\n")
            for r in results:
                if not (r["window"] == 4 and r["guard"]):
                    continue
                st = r["best_story"]
                f.write(f"| {r['model'].split('/')[-1]} {r['note']} | {r['text']} | {st['thr']:.2f} | {st['tp']} | "
                        f"{st['related']} | {st['tp'] + st['related']} из {n_same + n_rel} | {st['fp']} из {n_diff} | "
                        f"{st['unlabeled_above']} |\n")
                for thr in (0.74, 0.76, 0.78, 0.80):
                    c = next((x for x in r["curve"] if abs(x["thr"] - thr) < 1e-6), None)
                    if c and "MiniLM" in r["model"] and r["text"] == "title+300":
                        f.write(f"|  ↳ при {thr:.2f} | | | {c['tp']} | {c['related']} | {c['tp'] + c['related']} | "
                                f"{c['fp']} | {c['unlabeled_above']} |\n")


if __name__ == "__main__":
    sys.exit(main())
