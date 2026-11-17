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

import os

import csv
import io
import json
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
from .story import StoryLinker, related_json
from .vectors import VectorCache

LogFn = Optional[Callable[[str], None]]
PERIOD_VAR = "{{ПЕРИОД}}"
CSV_COLUMNS = ["ID", "Дата публикации", "Источник", "Тип источника", "Заголовок",
               "Полный текст", "Ссылка", "Другие источники", "Связанные строки"]
# СЛК: плюс проверка даты и отметка о повторе из прошлого дайджеста
SLK_COLUMNS = ["ID", "Дата публикации", "Дата проверена", "Источник", "Тип источника", "Заголовок",
               "Полный текст", "Ссылка", "Другие источники", "Связанные строки", "Было в прошлом дайджесте"]
DATE_LABEL = {None: "по ленте", "": "по ленте", "page": "по странице статьи",
              "card": "по карточке на сайте"}
PROFILES = ("space", "slk")
STATES = ("main", "merged", "known", "excluded", "filtered")
# Для «уже было в прошлой выгрузке» порог строже: такая новость в CSV не попадает совсем,
# а версия внутри сюжета лишь дописывает факты в основную строку.
KNOWN_MARGIN = 0.04
KIND_LABEL = {"rss": "Сайт", "telegram": "Telegram", "file": "Файл"}


def default_prompt(profile: str = "space") -> str:
    name = "slk_default.txt" if profile == "slk" else "digest_default.txt"
    return (resource_dir() / "prompts" / name).read_text(encoding="utf-8")


def date_check_label(r: dict) -> str:
    """Как определена дата новости — для колонки «Дата проверена» и для экрана проверки."""
    st = r.get("date_status")
    if st in ("none", "baseline"):
        seen = local_dt(r.get("fetched_at") or r.get("published_at"))
        return ("НЕ ПОДТВЕРЖДЕНА — у новости на сайте нет даты; впервые замечена "
                + (seen.strftime("%d.%m.%Y") if seen else "недавно"))
    return DATE_LABEL.get(st, "по ленте")


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
    """profile = space — общий дайджест (раздел настроек «export»);
    profile = slk — дайджест по РН сверхлёгкого класса (раздел «slk»): своё окно дат с
    перекрытием, свой предфильтр, свой промпт и своя история выгрузок в той же базе."""

    def __init__(self, db: Database, settings, deduper: Optional[Callable] = None,
                 downloads_dir: Optional[Path] = None, export_root: Optional[Path] = None,
                 vectors: Optional[VectorCache] = None, profile: str = "space",
                 story_encoder: Optional[Callable] = None):
        assert profile in PROFILES, profile
        self.db = db

        self.profile = profile
        self.section = "slk" if profile == "slk" else "export"
        self.vectors = vectors or VectorCache(db)
        self.linker = StoryLinker(db, settings, encode=story_encoder, vectors=self.vectors, article=self._article)
        if profile == "slk":
            from .slk import SlkFilter
            self.filter = SlkFilter(db, settings)
        else:
            self.filter = ContentFilter(db, settings)
        self.settings = settings
        self._deduper = deduper
        self.downloads_dir = Path(downloads_dir) if downloads_dir else Path.home() / "Downloads"
        self._export_root = Path(export_root) if export_root else None

    # ─── настройки ───────────────────────────────────────────────────────────
    def cfg(self, key: str, default=None):
        return self.settings.get(self.section, key, default)

    @property
    def slk(self) -> bool:
        return self.profile == "slk"

    def export_root(self) -> Path:
        if self._export_root:
            return self._export_root
        custom = (self.cfg("folder") or "").strip()
        if custom:
            return Path(custom).expanduser()
        docs = Path.home() / "Documents"
        return (docs if docs.exists() else Path.home()) / "Space Digest" / \
            ("Выгрузки СЛК" if self.slk else "Выгрузки")

    def prompt_template(self) -> str:
        return (self.cfg("prompt") or "").strip() or default_prompt(self.profile)

    def window(self, today: Optional[str] = None) -> dict:
        """СЛК: новые N дней + M дней перекрытия с прошлым поиском (по умолчанию 14 + 7)."""
        period = max(1, int(self.cfg("period_days", 14) or 14))
        overlap = max(0, int(self.cfg("overlap_days", 7) or 0))
        end = datetime.strptime(today, "%Y-%m-%d").date() if today else datetime.now().astimezone().date()
        new_from = end - timedelta(days=period - 1)
        start = new_from - timedelta(days=overlap)
        return {"date_from": start.isoformat(), "date_to": end.isoformat(),
                "new_from": new_from.isoformat(), "period_days": period, "overlap_days": overlap}

    def render_prompt(self, period_from: str, period_to: str, new_from: str = "") -> str:
        period = period_from if period_from == period_to else f"{period_from} - {period_to}"
        text = self.prompt_template().replace(PERIOD_VAR, period)
        if self.slk:
            nf = new_from or period_from
            overlap_to = (datetime.strptime(nf, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()
            text = (text.replace("{{НОВЫЙ_ПЕРИОД}}", f"{nf} - {period_to}")
                        .replace("{{ПЕРЕКРЫТИЕ}}", "нет" if nf <= period_from else f"{period_from} - {overlap_to}"))
        return text

    # ─── отбор ───────────────────────────────────────────────────────────────
    def last(self) -> Optional[dict]:
        return self.db.one("SELECT * FROM exports WHERE profile = ? ORDER BY id DESC LIMIT 1",
                           (self.profile,))

    def select(self, mode: str = "since_last", date_from: str = "", date_to: str = "",
               kinds: tuple[str, ...] = ("rss", "telegram"),
               until: Optional[str] = None) -> tuple[list[dict], dict]:
        until = until or now_iso()
        kinds = tuple(k for k in kinds if k in KIND_LABEL) or ("rss", "telegram")
        info: dict = {"mode": mode, "until": until}
        # Архив сайта, собранный при первом заходе (дата неизвестна), в выгрузки не идёт
        where = [f"s.kind IN ({','.join('?' * len(kinds))})", "i.fetched_at <= ?",
                 "s.scope IN ('all', ?)", "COALESCE(i.date_status, '') <> 'baseline'"]
        params: list = [*kinds, until, self.profile]
        if self.slk and mode in ("window", "since_last"):
            w = self.window()
            mode, date_from, date_to = "dates", w["date_from"], w["date_to"]
            info.update(window=w)
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
                   i.date_status, s.name AS source_name, s.kind AS kind, s.key AS source_key
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
                        "undated": r.get("date_status") == "none",
                        "filtered": dropped.get(r["id"])} for r in rows[:300]],
            "undated": sum(1 for r in rows if r.get("date_status") == "none"),
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
            WHERE ei.state IN ('main', 'merged') AND e.created_at >= ? AND e.profile = ?
        """, (iso_after(minutes=-days * 1440), self.profile))
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
        days = int(self.cfg("reference_days", 30 if self.slk else 7) or 0)
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
                    encoder=self.vectors.encoder(dd.get("engine", "auto")), log=log,
                    window_days=float(dd.get("window_days", 4) or 0) or None,
                    number_guard=bool(dd.get("number_guard", True)))
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
                   ei.note, ei.related, i.source_id, i.title, i.summary, i.body, i.url, i.published_at,
                   i.fetched_at, i.date_status, s.name AS source_name, s.kind AS kind
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
        w.writerow(SLK_COLUMNS if self.slk else CSV_COLUMNS)
        numbers = {r["id"]: k for k, r in enumerate((r for r in rows if r["state"] == "main"), start=1)}
        n = 0
        for r in rows:
            if r["state"] != "main":
                continue
            n += 1
            try:
                rel_ids = json.loads(r.get("related") or "[]")
            except ValueError:
                rel_ids = []
            related = ", ".join(str(numbers[i]) for i in sorted(rel_ids, key=lambda i: numbers.get(i, 0))
                                if i in numbers)
            others = children.get(r["id"], [])
            text, _ = self.story(r, others)
            d = local_dt(r["published_at"])
            date = d.strftime("%Y-%m-%d %H:%M") if d else ""
            if r.get("date_status") in ("page", "card", "none"):
                date = date[:10]                          # время у таких дат не имеет смысла
            other = "\n".join(f"{o['source_name']}: {o['url']}" for o in others)
            if self.slk:
                w.writerow([n, date, date_check_label(r), r["source_name"],
                            KIND_LABEL.get(r["kind"], r["kind"]), fix_mojibake(r["title"]), text, r["url"],
                            other, related, r.get("note") or ""])
            else:
                w.writerow([n, date, r["source_name"], KIND_LABEL.get(r["kind"], r["kind"]),
                            fix_mojibake(r["title"]), text, r["url"], other, related])
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
        fname, fwhere = (("Предфильтр СЛК", "Настройки → Дайджест СЛК") if self.slk
                         else ("Фильтр мусора", "Настройки → Фильтр мусора"))
        if log and dropped:
            log(f"{fname} отсеял: {len(dropped)} (вернуть можно во вкладке «Отфильтровано»)")
        if not passed:
            raise ValueError(f"все отобранные новости отсеяны: {fname.lower()} ({fwhere})")
        roles: dict[int, tuple[str, Optional[int], Optional[float]]] = {}
        if self.cfg("dedup", True) if dedupe is None else dedupe:
            roles = self.dedupe(passed, log)
        notes: dict[int, str] = {}
        if self.slk:
            # СЛК: окно дат перекрывается с прошлым поиском, поэтому повторы ожидаемы. Они не
            # выбрасываются, а идут в CSV с отметкой — решает ChatGPT (есть ли новый факт).
            notes = self.previous_notes([r["id"] for r in passed])
            for iid, (state, canon, sim) in list(roles.items()):
                if state == "known":
                    prev = self.previous_notes([canon]).get(canon) if canon else None
                    notes.setdefault(iid, (prev or "похожая новость была в прошлом дайджесте")
                                     + " (тот же сюжет из другого источника)")
                    del roles[iid]
        kept = [r for r in passed if r["id"] not in roles]
        if not kept:
            raise ValueError("все отобранные новости уже были в прошлых выгрузках")
        if log and roles:
            merged = sum(1 for v in roles.values() if v[0] == "merged")
            log(f"Сюжетов из нескольких источников: {len({v[1] for v in roles.values() if v[0] == 'merged'})} "
                f"(сведено версий: {merged}); уже было в прошлых выгрузках: {len(roles) - merged}")
        if log and notes:
            log(f"Было в прошлых дайджестах СЛК: {len(notes)} — остаются в CSV с отметкой")
        undated = sum(1 for r in kept if r.get("date_status") == "none")
        if log and undated:
            log(f"Без даты на сайте: {undated} — в CSV с пометкой «НЕ ПОДТВЕРЖДЕНА», ChatGPT проверит поиском")
        related = self.linker.link(kept, log)
        dates = [d for d in (local_dt(r["published_at"]) for r in kept) if d]
        p_from, p_to = min(dates).date().isoformat(), max(dates).date().isoformat()
        win = info.get("window")
        if win:
            p_from, p_to = win["date_from"], win["date_to"]
        elif self.slk and info.get("date_from"):
            p_from, p_to = info["date_from"], info["date_to"]

        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        folder = self.export_root() / stamp
        n = 2
        while folder.exists():
            folder = self.export_root() / f"{stamp}_{n}"; n += 1
        folder.mkdir(parents=True)
        stem = "slk_news" if self.slk else "news"
        base = f"{stem}_{p_from}" if p_from == p_to else f"{stem}_{p_from}_{p_to}"
        csv_path = folder / f"{base}.csv"
        prompt = self.render_prompt(p_from, p_to, (win or {}).get("new_from", ""))
        prompt_path = folder / "prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")

        with self.db.tx():
            cur = self.db.execute("""
                INSERT INTO exports (created_at, mode, period_from, period_to, fetched_until, kinds,
                    items_selected, folder, csv_file, prompt_file, profile)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (until, "since_last" if mode == "since_last" and not self.slk else "dates", p_from, p_to,
                  until, ",".join(kinds), len(rows), str(folder), str(csv_path), str(prompt_path),
                  self.profile))
            eid = int(cur.lastrowid)
            for r in rows:
                state, dup_of, sim = roles.get(r["id"], ("main", None, None))
                reason = dropped.get(r["id"])
                if reason:
                    state = "filtered"
                self.db.execute("INSERT INTO export_items (export_id, item_id, state, duplicate_of, similarity, "
                                "reason, note, related) VALUES (?,?,?,?,?,?,?,?)",
                                (eid, r["id"], state, dup_of, sim, reason, notes.get(r["id"]),
                                 related_json(related.get(r["id"], []))))
        counts = self.write_csv(eid)
        if log:
            log(f"Готово: {csv_path.name} ({counts['main']} строк), период {p_from} – {p_to}")
        return {**self.get(eid), "prompt": prompt, "info": info}

    def previous_notes(self, item_ids: list[int]) -> dict[int, str]:
        """СЛК: какие из новостей уже были в прошлых выгрузках СЛК → «дайджест СЛК от 30.10.2026»."""
        out: dict[int, str] = {}
        ids = [i for i in item_ids if i]
        for k in range(0, len(ids), 500):
            part = ids[k:k + 500]
            for r in self.db.query(f"""
                SELECT ei.item_id, MAX(e.created_at) AS at
                FROM export_items ei JOIN exports e ON e.id = ei.export_id
                WHERE e.profile = ? AND ei.state IN ('main', 'merged')
                  AND ei.item_id IN ({','.join('?' * len(part))})
                GROUP BY ei.item_id""", (self.profile, *part)):
                d = local_dt(r["at"])
                out[r["item_id"]] = f"да, выгрузка СЛК от {d.strftime('%d.%m.%Y') if d else '—'}"
        return out

    # ─── проверка выгрузки ───────────────────────────────────────────────────
    @staticmethod
    def _brief(r: dict) -> dict:
        d = local_dt(r["published_at"])
        return {"id": r["id"], "title": r["title"], "source": r["source_name"], "kind": r["kind"],
                "url": r["url"], "published": d.strftime("%d.%m %H:%M") if d else "",
                "similarity": r.get("similarity"), "chars": len(full_text(r)),
                "note": r.get("note") or "",
                "related": len(json.loads(r.get("related") or "[]")),
                "undated": r.get("date_status") == "none",
                "date_check": DATE_LABEL.get(r.get("date_status")) if r.get("date_status") in ("page", "card") else ""}

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
        return self.db.query("SELECT * FROM exports WHERE profile = ? ORDER BY id DESC LIMIT ?",
                             (self.profile, limit))

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
            try:
                entries = os.scandir(d)                    # дешевле glob: без лишних stat
            except OSError:
                continue
            with entries:
                for de in entries:
                    name = de.name
                    if not name.lower().endswith(".docx") or name.startswith("~$"):
                        continue
                    try:
                        st = de.stat()
                    except OSError:
                        continue
                    if st.st_mtime >= since and st.st_size > 0 and now - st.st_mtime >= 2:
                        cands.append((st.st_mtime, Path(de.path)))
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
