"""
Выгрузка для ChatGPT: «всё новое с прошлой выгрузки» одним действием.

1. Отбор: новости, пришедшие в базу после прошлой выгрузки (водяной знак по времени
   поступления, поэтому опоздавшие публикации не теряются), или за выбранные даты.
2. Сюжеты: версии одного события с разных сайтов и каналов сводятся в одну строку CSV —
   полный текст основной версии + новые факты остальных (services/stories.py).
   То, что уже выгружалось за последние N дней, в CSV не идёт (заменяет «недельную базу»).
3. Проверка: можно отделить ошибочно сведённую версию, вернуть «уже было» или убрать строку —
   CSV пересобирается из базы за доли секунды.
4. Файлы: CSV с полным текстом и промпт с подставленным периодом — в папку выгрузки.
5. Результат: готовый DOCX от ChatGPT забирается из «Загрузок» в ту же папку.
"""
from __future__ import annotations

import csv
import io
import shutil
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from ..core.db import Database
from ..core.timeutil import from_iso, iso_after, now_iso, to_iso
from ..domain.text import fix_mojibake
from ..paths import resource_dir
from .filters import ContentFilter
from .stories import merge_text
from .vectors import VectorCache

LogFn = Optional[Callable[[str], None]]
PERIOD_VAR = "{{ПЕРИОД}}"
CSV_COLUMNS = ["ID", "Дата публикации", "Источник", "Тип источника", "Заголовок",
               "Полный текст", "Ссылка", "Другие источники"]
STATES = ("main", "merged", "known", "excluded", "filtered")
# Для «уже было в прошлой выгрузке» порог строже: такая новость в CSV не попадает совсем,
# а версия внутри сюжета лишь дописывает факты в основную строку.
KNOWN_MARGIN = 0.04
KIND_LABEL = {"rss": "Сайт", "telegram": "Telegram", "file": "Файл"}


def default_prompt() -> str:
    return (resource_dir() / "prompts" / "digest_default.txt").read_text(encoding="utf-8")


def local_dt(iso: Optional[str]) -> Optional[datetime]:
    dt = from_iso(iso)
    return dt.astimezone() if dt else None          # часовой пояс компьютера


def local_day_bounds(date_from: str, date_to: str) -> tuple[str, str]:
    """Локальные даты [from; to] включительно → границы в UTC [начало; конец)."""
    tz = datetime.now().astimezone().tzinfo
    start = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=tz)
    end = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=tz) + timedelta(days=1)
    return to_iso(start), to_iso(end)


def full_text(row: dict) -> str:
    """Полный текст для ChatGPT: тело статьи; анонс добавляется, если в теле его нет."""
    # fix_mojibake — для уже сохранённых новостей с «кракозябрами» (новые чинятся при приёме)
    body, summary = fix_mojibake((row.get("body") or "").strip()), fix_mojibake((row.get("summary") or "").strip())
    if body and summary and summary[:60].rstrip("…. ") not in body:
        return f"{summary}\n\n{body}"
    return body or summary


class ExportService:
    def __init__(self, db: Database, settings, deduper: Optional[Callable] = None,
                 downloads_dir: Optional[Path] = None, export_root: Optional[Path] = None,
                 vectors: Optional[VectorCache] = None):
        self.db = db
        self.vectors = vectors or VectorCache(db)
        self.filter = ContentFilter(db, settings)
        self.settings = settings
        self._deduper = deduper
        self.downloads_dir = Path(downloads_dir) if downloads_dir else Path.home() / "Downloads"
        self._export_root = Path(export_root) if export_root else None

    # ─── настройки ───────────────────────────────────────────────────────────
    def cfg(self, key: str, default=None):
        return self.settings.get("export", key, default)

    def export_root(self) -> Path:
        if self._export_root:
            return self._export_root
        custom = (self.cfg("folder") or "").strip()
        if custom:
            return Path(custom).expanduser()
        docs = Path.home() / "Documents"
        return (docs if docs.exists() else Path.home()) / "Space Digest" / "Выгрузки"

    def prompt_template(self) -> str:
        return (self.cfg("prompt") or "").strip() or default_prompt()

    def render_prompt(self, period_from: str, period_to: str) -> str:
        period = period_from if period_from == period_to else f"{period_from} - {period_to}"
        return self.prompt_template().replace(PERIOD_VAR, period)

    # ─── отбор ───────────────────────────────────────────────────────────────
    def last(self) -> Optional[dict]:
        return self.db.one("SELECT * FROM exports ORDER BY id DESC LIMIT 1")

    def select(self, mode: str = "since_last", date_from: str = "", date_to: str = "",
               kinds: tuple[str, ...] = ("rss", "telegram"),
               until: Optional[str] = None) -> tuple[list[dict], dict]:
        until = until or now_iso()
        kinds = tuple(k for k in kinds if k in KIND_LABEL) or ("rss", "telegram")
        info: dict = {"mode": mode, "until": until}
        where = [f"s.kind IN ({','.join('?' * len(kinds))})", "i.fetched_at <= ?"]
        params: list = [*kinds, until]
        last = self.last() if mode == "since_last" else None
        if mode == "since_last" and last:
            where += ["i.fetched_at > ?", "i.origin = 'collect'"]
            params.append(last["fetched_until"])
            info["since"] = last["fetched_until"]
        else:
            if mode == "since_last":            # первая выгрузка: вчера и сегодня
                today = datetime.now().astimezone().date()
                date_from, date_to = (today - timedelta(days=1)).isoformat(), today.isoformat()
                info["fallback"] = True
            if not date_from or not date_to:
                raise ValueError("укажите даты «с» и «по»")
            lo, hi = local_day_bounds(date_from, date_to)
            where += ["i.published_at >= ?", "i.published_at < ?"]
            params += [lo, hi]
            info.update(date_from=date_from, date_to=date_to)
        rows = self.db.query(f"""
            SELECT i.id, i.source_id, i.title, i.summary, i.body, i.url, i.published_at, i.fetched_at,
                   s.name AS source_name, s.kind AS kind, s.key AS source_key
            FROM items i JOIN sources s ON s.id = i.source_id
            WHERE {' AND '.join(where)}
            ORDER BY i.published_at DESC, i.id DESC
        """, params)
        return rows, info

    def preview(self, mode="since_last", date_from="", date_to="", kinds=("rss", "telegram")) -> dict:
        rows, info = self.select(mode, date_from, date_to, kinds)
        _, dropped = self.filter.split(rows)
        by_source: dict[str, int] = {}
        for r in rows:
            by_source[r["source_name"]] = by_source.get(r["source_name"], 0) + 1
        dates = [d for d in (local_dt(r["published_at"]) for r in rows) if d]
        return {
            **info,
            "total": len(rows),
            "filtered": len(dropped),
            "by_kind": {k: sum(1 for r in rows if r["kind"] == k) for k in ("rss", "telegram")},
            "by_source": sorted(by_source.items(), key=lambda x: -x[1]),
            "period_from": min(dates).date().isoformat() if dates else "",
            "period_to": max(dates).date().isoformat() if dates else "",
            "sample": [{"title": r["title"], "source": r["source_name"], "kind": r["kind"],
                        "published": local_dt(r["published_at"]).strftime("%d.%m %H:%M")
                        if r["published_at"] else "", "url": r["url"],
                        "filtered": dropped.get(r["id"])} for r in rows[:300]],
            "last_export": self.last(),
        }

    # ─── повторы ─────────────────────────────────────────────────────────────
    def reference_rows(self, days: int, exclude: set[int]) -> list[dict]:
        if days <= 0:
            return []
        rows = self.db.query("""
            SELECT DISTINCT i.id, i.title, i.summary, i.body, i.url, i.published_at,
                   s.name AS source_name, s.kind AS kind
            FROM export_items ei JOIN exports e ON e.id = ei.export_id
            JOIN items i ON i.id = ei.item_id JOIN sources s ON s.id = i.source_id
            WHERE ei.state IN ('main', 'merged') AND e.created_at >= ?
        """, (iso_after(minutes=-days * 1440),))
        return [r for r in rows if r["id"] not in exclude]

    @staticmethod
    def _article(r: dict) -> dict:
        text = full_text(r)
        return {"_item_id": r["id"], "title": r["title"], "summary": text[:1500],
                "source_name": r["source_name"], "url": r["url"],
                "published_at": (r["published_at"] or "")[:16].replace("T", " ")}

    def dedupe(self, rows: list[dict], log: LogFn = None) -> dict[int, tuple[str, Optional[int], Optional[float]]]:
        """Роли повторов: {id: (state, id основной версии, близость)}; state — merged или known.
        Новости, которых нет в ответе, — основные (main)."""
        dedup = self._deduper
        if dedup is None:
            from ..deduplicator import run_deduplication as dedup
        ids = {r["id"] for r in rows}
        days = int(self.cfg("reference_days", 7) or 0)
        ref = self.reference_rows(days, ids)
        if len(rows) < 2 and not ref:
            return {}
        if log and ref:
            log(f"Сверка с прошлыми выгрузками: {len(ref)} новостей за {days} дн.")
        sites = [self._article(r) for r in rows if r["kind"] != "telegram"]
        tg = [self._article(r) for r in rows if r["kind"] == "telegram"]
        dd = self.settings.get("dedup") or {}
        thr = float(dd.get("threshold", 0.82))
        res = dedup(parser_articles=sites or None, tg_articles=tg or None,
                    reference_articles=[self._article(r) for r in ref] or None,
                    reference_label="Прошлые выгрузки", threshold=thr,
                    ref_threshold=min(0.97, thr + KNOWN_MARGIN),
                    cross_compare=True, prefer_file_as_base=False,
                    encoder=self.vectors.encoder(dd.get("engine", "auto")), log=log)
        out: dict[int, tuple[str, Optional[int], Optional[float]]] = {}
        for a in res["removed"]:
            canon = (a.get("duplicate_of") or {}).get("_item_id")
            state = "merged" if canon in ids and not a.get("removed_by_reference") else "known"
            out[a["_item_id"]] = (state, canon, a.get("similarity"))
        return out

    # ─── файлы ───────────────────────────────────────────────────────────────
    # ─── сюжеты ──────────────────────────────────────────────────────────────
    def _export_rows(self, export_id: int) -> list[dict]:
        rows = self.db.query("""
            SELECT ei.item_id AS id, ei.state, ei.duplicate_of, ei.similarity, ei.row_no, ei.reason,
                   i.source_id, i.title, i.summary, i.body, i.url, i.published_at,
                   s.name AS source_name, s.kind AS kind
            FROM export_items ei JOIN items i ON i.id = ei.item_id JOIN sources s ON s.id = i.source_id
            WHERE ei.export_id = ?
        """, (export_id,))
        rows.sort(key=lambda r: (r["published_at"] or "", r["id"]), reverse=True)
        return rows

    @staticmethod
    def _children(rows: list[dict]) -> dict[int, list[dict]]:
        """Версии сюжета: сначала сайты, затем более полные тексты."""
        ch: dict[int, list[dict]] = defaultdict(list)
        for r in rows:
            if r["state"] == "merged" and r["duplicate_of"] is not None:
                ch[r["duplicate_of"]].append(r)
        for lst in ch.values():
            lst.sort(key=lambda r: (r["kind"] == "telegram", -len(full_text(r))))
        return ch

    @staticmethod
    def story(main: dict, others: list[dict]) -> tuple[str, list[int]]:
        return merge_text(full_text(main), [(o["source_name"], full_text(o)) for o in others])

    def csv_text(self, rows: list[dict]) -> str:
        """rows — все новости выгрузки с ролями; в CSV идут основные, версии — внутрь них."""
        children = self._children(rows)
        out = io.StringIO()
        w = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        w.writerow(CSV_COLUMNS)
        n = 0
        for r in rows:
            if r["state"] != "main":
                continue
            n += 1
            others = children.get(r["id"], [])
            text, _ = self.story(r, others)
            d = local_dt(r["published_at"])
            w.writerow([n, d.strftime("%Y-%m-%d %H:%M") if d else "", r["source_name"],
                        KIND_LABEL.get(r["kind"], r["kind"]), fix_mojibake(r["title"]), text, r["url"],
                        "\n".join(f"{o['source_name']}: {o['url']}" for o in others)])
        return "\ufeff" + out.getvalue()                  # BOM — корректно открывается в Excel

    def write_csv(self, export_id: int) -> dict:
        """Пересобрать CSV выгрузки из базы (после подготовки и после правок)."""
        e = self.get(export_id)
        if not e:
            raise ValueError("выгрузка не найдена")
        rows = self._export_rows(export_id)
        mains = [r for r in rows if r["state"] == "main"]
        try:
            Path(e["csv_file"]).write_text(self.csv_text(rows), encoding="utf-8", newline="")
        except PermissionError:
            raise ValueError("CSV открыт в другой программе (например, Excel) — закройте его и повторите")
        counts = {s: sum(1 for r in rows if r["state"] == s) for s in STATES}
        with self.db.tx():
            self.db.execute("UPDATE export_items SET row_no = NULL WHERE export_id = ?", (export_id,))
            for n, r in enumerate(mains, start=1):
                self.db.execute("UPDATE export_items SET row_no = ? WHERE export_id = ? AND item_id = ?",
                                (n, export_id, r["id"]))
            self.db.execute("UPDATE exports SET items_exported = ?, duplicates_removed = ? WHERE id = ?",
                            (counts["main"], counts["merged"] + counts["known"], export_id))
        return counts

    def prepare(self, mode: str = "since_last", date_from: str = "", date_to: str = "",
                kinds=("rss", "telegram"), dedupe: Optional[bool] = None, log: LogFn = None) -> dict:
        until = now_iso()
        rows, info = self.select(mode, date_from, date_to, tuple(kinds), until=until)
        if not rows:
            raise ValueError("нет новых новостей для выгрузки" if mode == "since_last"
                             else "за выбранные даты новостей нет")
        if log:
            log(f"Отобрано новостей: {len(rows)} (сайты {sum(r['kind'] != 'telegram' for r in rows)}, "
                f"Telegram {sum(r['kind'] == 'telegram' for r in rows)})")
        passed, dropped = self.filter.split(rows)
        if log and dropped:
            log(f"Фильтр мусора отсеял: {len(dropped)} (вернуть можно во вкладке «Отфильтровано»)")
        if not passed:
            raise ValueError("все отобранные новости отсеяны фильтром мусора (Настройки → Фильтр мусора)")
        roles: dict[int, tuple[str, Optional[int], Optional[float]]] = {}
        if self.cfg("dedup", True) if dedupe is None else dedupe:
            roles = self.dedupe(passed, log)
        kept = [r for r in passed if r["id"] not in roles]
        if not kept:
            raise ValueError("все отобранные новости уже были в прошлых выгрузках")
        if log and roles:
            merged = sum(1 for v in roles.values() if v[0] == "merged")
            log(f"Сюжетов из нескольких источников: {len({v[1] for v in roles.values() if v[0] == 'merged'})} "
                f"(сведено версий: {merged}); уже было в прошлых выгрузках: {len(roles) - merged}")
        dates = [d for d in (local_dt(r["published_at"]) for r in kept) if d]
        p_from, p_to = min(dates).date().isoformat(), max(dates).date().isoformat()

        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        folder = self.export_root() / stamp
        n = 2
        while folder.exists():
            folder = self.export_root() / f"{stamp}_{n}"; n += 1
        folder.mkdir(parents=True)
        base = f"news_{p_from}" if p_from == p_to else f"news_{p_from}_{p_to}"
        csv_path = folder / f"{base}.csv"
        prompt = self.render_prompt(p_from, p_to)
        prompt_path = folder / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")

        with self.db.tx():
            cur = self.db.execute("""
                INSERT INTO exports (created_at, mode, period_from, period_to, fetched_until, kinds,
                    items_selected, folder, csv_file, prompt_file)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (until, "since_last" if mode == "since_last" else "dates", p_from, p_to, until,
                  ",".join(kinds), len(rows), str(folder), str(csv_path), str(prompt_path)))
            eid = int(cur.lastrowid)
            for r in rows:
                state, dup_of, sim = roles.get(r["id"], ("main", None, None))
                reason = dropped.get(r["id"])
                if reason:
                    state = "filtered"
                self.db.execute("INSERT INTO export_items (export_id, item_id, state, duplicate_of, similarity, reason) "
                                "VALUES (?,?,?,?,?,?)", (eid, r["id"], state, dup_of, sim, reason))
        counts = self.write_csv(eid)
        if log:
            log(f"Готово: {csv_path.name} ({counts['main']} строк), период {p_from} – {p_to}")
        return {**self.get(eid), "prompt": prompt, "info": info}

    # ─── проверка выгрузки ───────────────────────────────────────────────────
    @staticmethod
    def _brief(r: dict) -> dict:
        d = local_dt(r["published_at"])
        return {"id": r["id"], "title": r["title"], "source": r["source_name"], "kind": r["kind"],
                "url": r["url"], "published": d.strftime("%d.%m %H:%M") if d else "",
                "similarity": r.get("similarity"), "chars": len(full_text(r))}

    def review(self, export_id: int) -> dict:
        rows = self._export_rows(export_id)
        children = self._children(rows)
        stories, known, excluded, filtered = [], [], [], []
        for r in rows:
            if r["state"] in ("main", "excluded"):
                others = children.get(r["id"], [])
                _, added = self.story(r, others)
                item = {**self._brief(r), "n": r["row_no"],
                        "others": [{**self._brief(o), "added": a} for o, a in zip(others, added)]}
                (stories if r["state"] == "main" else excluded).append(item)
            elif r["state"] == "known":
                known.append({**self._brief(r), "match": self._known_match(r["duplicate_of"], export_id),
                              "others": [self._brief(o) for o in children.get(r["id"], [])]})
            elif r["state"] == "filtered":
                filtered.append({**self._brief(r), "reason": r["reason"], "source_id": r["source_id"]})
        stories.sort(key=lambda x: x["n"] or 0)
        return {"stories": stories, "known": known, "excluded": excluded, "filtered": filtered,
                "counts": {"rows": len(stories), "multi": sum(1 for s in stories if s["others"]),
                           "merged": sum(len(s["others"]) for s in stories),
                           "known": len(known), "excluded": len(excluded), "filtered": len(filtered)}}

    def _known_match(self, item_id: Optional[int], export_id: int) -> Optional[dict]:
        if item_id is None:
            return None
        r = self.db.one("""
            SELECT i.title, i.url, s.name AS source, e.created_at AS exported_at
            FROM items i JOIN sources s ON s.id = i.source_id
            LEFT JOIN export_items ei ON ei.item_id = i.id AND ei.export_id < ? AND ei.state IN ('main','merged')
            LEFT JOIN exports e ON e.id = ei.export_id
            WHERE i.id = ? ORDER BY e.id DESC LIMIT 1
        """, (export_id, item_id))
        if r and r["exported_at"]:
            r["exported"] = local_dt(r["exported_at"]).strftime("%d.%m")
        return r

    def refilter(self, export_id: int) -> int:
        """Применить текущий фильтр к строкам выгрузки (после нового правила). → сколько отсеяно."""
        check = self.filter.checker()
        hits = [(check(r), r["id"]) for r in self._export_rows(export_id) if r["state"] == "main"]
        hits = [(reason, iid) for reason, iid in hits if reason]
        mains = self.db.scalar("SELECT COUNT(*) FROM export_items WHERE export_id = ? AND state = 'main'", (export_id,))
        if hits and len(hits) >= mains:
            raise ValueError("правило отсеяло бы все строки выгрузки — проверьте его")
        if hits:
            with self.db.tx():
                for reason, iid in hits:
                    self.db.execute("UPDATE export_items SET state = 'filtered', reason = ? "
                                    "WHERE export_id = ? AND item_id = ?", (reason, export_id, iid))
            self.write_csv(export_id)
        return len(hits)

    TRANSITIONS = {"separate": (("merged",), "main"), "restore": (("known", "filtered"), "main"),
                   "exclude": (("main",), "excluded"), "include": (("excluded",), "main")}

    def change(self, export_id: int, item_id: int, action: str) -> dict:
        """Правка выгрузки: separate — версию в отдельную строку; restore — вернуть «уже было»
        или отсеянное фильтром;
        exclude / include — убрать строку из CSV / вернуть. CSV пересобирается сразу."""
        if action not in self.TRANSITIONS:
            raise ValueError("неизвестное действие")
        src, dst = self.TRANSITIONS[action]
        cur = self.db.one("SELECT state FROM export_items WHERE export_id = ? AND item_id = ?",
                          (export_id, item_id))
        if not cur:
            raise ValueError("новости нет в этой выгрузке")
        if cur["state"] not in src:
            raise ValueError("состояние новости уже изменилось — обновите список")
        sql = "UPDATE export_items SET state = ?" + (", duplicate_of = NULL" if action == "separate" else "")
        with self.db.tx():
            self.db.execute(sql + " WHERE export_id = ? AND item_id = ?", (dst, export_id, item_id))
            if action == "exclude" and not self.db.scalar(
                    "SELECT COUNT(*) FROM export_items WHERE export_id = ? AND state = 'main'", (export_id,)):
                raise ValueError("нельзя убрать последнюю строку выгрузки")
        self.write_csv(export_id)
        return self.review(export_id)

    # ─── история и результат ─────────────────────────────────────────────────
    def get(self, export_id: int) -> Optional[dict]:
        return self.db.one("SELECT * FROM exports WHERE id = ?", (export_id,))

    def list(self, limit: int = 30) -> list[dict]:
        return self.db.query("SELECT * FROM exports ORDER BY id DESC LIMIT ?", (limit,))

    def find_result(self, export_id: int) -> Optional[Path]:
        """Самый свежий DOCX, появившийся после подготовки выгрузки: в «Загрузках»
        или прямо в папке выгрузки (если при скачивании выбрали её). Файл, который ещё
        записывается (изменён меньше 2 секунд назад или пустой), пропускается."""
        e = self.get(export_id)
        if not e:
            return None
        since = from_iso(e["created_at"]).timestamp() - 120
        now = datetime.now().timestamp()
        cands = []
        for d in (self.downloads_dir, Path(e["folder"])):
            if not d.is_dir():
                continue
            for p in d.glob("*.docx"):
                try:
                    st = p.stat()
                except OSError:
                    continue
                if not p.name.startswith("~$") and st.st_mtime >= since and st.st_size > 0 \
                        and now - st.st_mtime >= 2:
                    cands.append((st.st_mtime, p))
        return max(cands)[1] if cands else None

    def attach_result(self, export_id: int, path: Optional[str] = None) -> dict:
        e = self.get(export_id)
        if not e:
            raise ValueError("выгрузка не найдена")
        src = Path(path) if path else self.find_result(export_id)
        if not src or not src.is_file():
            raise ValueError("в «Загрузках» нет нового DOCX. Скачайте файл из ChatGPT и нажмите ещё раз")
        folder = Path(e["folder"])
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / src.name
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        self.db.execute("UPDATE exports SET result_file=?, status='done' WHERE id=?", (str(dst), export_id))
        return self.get(export_id)                         # type: ignore[return-value]
