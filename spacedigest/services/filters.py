"""
Фильтр мусора перед выгрузкой.

Два понятных правила, никакой «чёрной магии»:
1. Стоп-слова (для всех источников): реклама, промокоды, розыгрыши — такая новость
   в CSV не идёт.
2. «Только про космос» (включается для отдельного источника): новость ленты общего
   профиля проходит, только если в заголовке или тексте есть космическое слово.

Ничего не удаляется: отсеянное лежит во вкладке «Отфильтровано» и возвращается одной кнопкой.

Синтаксис слов (по одному в строке): «ракет*» — слово и все его формы,
«ESA» — только целое слово, «магнитн* бур*» — фраза. Регистр не важен. # — комментарий.

Подсказки строятся из данных: доля «некосмических» новостей у источника за 30 дней
и слова, которые часто встречаются в том, что пользователь убирал вручную.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Optional

from ..core.db import Database
from ..core.timeutil import iso_after

DEFAULT_STOP = """# Реклама и промо (в рекламе в РФ обязательна метка erid)
erid
#реклама
на правах рекламы
промокод*
розыгрыш*
"""

DEFAULT_TOPIC = """# Русские
косм*
спутни*
ракет*
орбит*
лун*
марс*
МКС
ЦУП
роскосм*
космодром*
байконур*
плесецк*
космонавт*
астронавт*
тайконавт*
телескоп*
планет*
экзопланет*
межпланет*
астероид*
комет*
метеор*
галактик*
звезд*
звёзд*
солнц*
солнечн*
вселенн*
запуск*
пуск*
стартов*
носител*
ЖРД
РДТТ
ДЗЗ
ГЛОНАСС
союз-*
союз мс*
прогресс мс*
ангар*
протон-*
тяньгун*
шэньчжоу*
чанъэ*
тяньвэнь*
артемид*
магнитн* бур*
черн* дыр*
чёрн* дыр*
аэрокосм*
астро*
обсерватор*
затмени*
полярн* сияни*
ночн* неб*
квазар*
пульсар*
сверхнов*
нейтрино
темн* матери*
тёмн* матери*
гравитационн* волн*
юпитер*
сатурн*
венер*
нептун*
плутон*
уэбб*
хаббл*
# English
space*
satellit*
rocket*
orbit*
launch*
lunar
moon*
mars
martian
astronaut*
cosmonaut*
taikonaut*
telescop*
planet*
exoplanet*
asteroid*
comet*
meteor*
galax*
nebula*
black hole*
solar
sun
stellar
star
stars
nova
supernova*
neutrino*
pulsar*
quasar*
brown dwarf*
white dwarf*
dark matter
dark energy
gravitational wave*
aurora*
eclipse*
observator*
astro*
cosmos
dark sky*
night sky
universe
cosmic
cosmolog*
Jupiter
Saturn
Venus
Neptune
Pluto
JWST
Webb
Hubble
constellation*
earth observation
direct-to-device
D2D
LEO
GEO
MEO
GNSS
GPS
Galileo
BeiDou
GLONASS
ISS
NASA
ESA
JAXA
ISRO
CNSA
SpaceX
Starship
Starlink
Blue Origin
Rocket Lab
ULA
Ariane*
Falcon*
New Glenn
Soyuz
Tiangong
Shenzhou
Tianwen*
Artemis
payload*
ground station*
mission control
"""

FILTERED_LABEL = "Отфильтровано"


def compile_words(text: str) -> Optional[re.Pattern]:
    parts = []
    for line in (text or "").splitlines():
        w = line.strip()
        if not w or w == "#" or w.startswith("# "):      # «# …» — комментарий, «#реклама» — слово
            continue
        stem = w.endswith("*")
        body = re.escape(w.rstrip("*")).replace(r"\*", r"\w*").replace(r"\ ", r"\s+")
        parts.append(r"(?<!\w)" + body + (r"" if stem else r"(?!\w)"))
    return re.compile("|".join(parts), re.IGNORECASE) if parts else None


def words_list(text: str) -> list[str]:
    return [l.strip() for l in (text or "").splitlines() if l.strip() and not l.strip().startswith("# ")]


class ContentFilter:
    def __init__(self, db: Database, settings):
        self.db = db
        self.settings = settings

    # ─── настройки ───────────────────────────────────────────────────────────
    def cfg(self) -> dict:
        return self.settings.get("filter") or {}

    def stop_text(self) -> str:
        return self.cfg().get("stop") or DEFAULT_STOP

    def topic_text(self) -> str:
        return self.cfg().get("topic") or DEFAULT_TOPIC

    def enabled(self) -> bool:
        return bool(self.cfg().get("enabled", True))

    # ─── проверка ────────────────────────────────────────────────────────────
    @staticmethod
    def _text(row: dict) -> str:
        return f"{row.get('title') or ''}\n{(row.get('body') or '')[:6000]}\n{(row.get('summary') or '')[:2000]}"

    def checker(self):
        """Функция row → причина отсева или None. Правила компилируются один раз на выгрузку."""
        stop, topic = compile_words(self.stop_text()), compile_words(self.topic_text())
        space_only = {r["id"] for r in self.db.query("SELECT id FROM sources WHERE space_only = 1")}

        def check(row: dict) -> Optional[str]:
            text = self._text(row)
            if stop and (m := stop.search(text)):
                return f"стоп-слово «{m.group(0).strip()}»"
            if topic and row.get("source_id") in space_only and not topic.search(text):
                return "не про космос (у источника включено «только про космос»)"
            return None
        return check

    def split(self, rows: list[dict]) -> tuple[list[dict], dict[int, str]]:
        """→ (прошедшие, {id: причина отсева})."""
        if not self.enabled() or not rows:
            return rows, {}
        check = self.checker()
        kept, dropped = [], {}
        for r in rows:
            reason = check(r)
            if reason:
                dropped[r["id"]] = reason
            else:
                kept.append(r)
        return kept, dropped

    # ─── статистика и подсказки ──────────────────────────────────────────────
    def source_stats(self, days: int = 30) -> list[dict]:
        """По каждому источнику: сколько новостей за N дней и какая доля без космических слов."""
        topic = compile_words(self.topic_text())
        since = iso_after(minutes=-days * 1440)
        stats: dict[int, dict] = {}
        for s in self.db.query("SELECT id, name, kind, enabled, space_only FROM sources WHERE kind != 'file'"):
            stats[s["id"]] = {"id": s["id"], "name": s["name"], "kind": s["kind"], "enabled": bool(s["enabled"]),
                              "space_only": bool(s["space_only"]), "total": 0, "off_topic": 0, "examples": []}
        for r in self.db.query("""
                SELECT source_id, title, substr(COALESCE(body, ''), 1, 6000) AS body,
                       substr(COALESCE(summary, ''), 1, 2000) AS summary
                FROM items WHERE COALESCE(published_at, fetched_at) >= ?""", (since,)):
            st = stats.get(r["source_id"])
            if not st:
                continue
            st["total"] += 1
            if topic and not topic.search(self._text(r)):
                st["off_topic"] += 1
                if len(st["examples"]) < 3:
                    st["examples"].append(r["title"][:110])
        out = []
        for st in stats.values():
            st["share"] = round(st["off_topic"] / st["total"], 3) if st["total"] else 0.0
            st["recommended"] = st["total"] >= 10 and st["share"] >= 0.4
            out.append(st)
        out.sort(key=lambda x: (not x["recommended"], -x["share"], x["name"].lower()))
        return out

    _TOKEN = re.compile(r"[^\W\d_]{4,}", re.UNICODE)

    def suggest_stop(self, days: int = 30, min_count: int = 3) -> list[dict]:
        """Слова, которые повторяются в убранном вручную (минимум в 3 новостях) и почти не
        встречаются в остальном (не чаще 1 из 500). Космические слова не предлагаются никогда:
        убрали новость о высадке на Луну — это не повод отсеивать все «высадки»."""
        since = iso_after(minutes=-days * 1440)
        excl = self.db.query("""
            SELECT DISTINCT i.id, i.title, substr(COALESCE(i.body, ''), 1, 1500) AS body
            FROM export_items ei JOIN exports e ON e.id = ei.export_id JOIN items i ON i.id = ei.item_id
            WHERE ei.state = 'excluded' AND e.created_at >= ?""", (since,))
        if len(excl) < min_count:
            return []
        ex_ids = {r["id"] for r in excl}
        stop, topic = compile_words(self.stop_text()), compile_words(self.topic_text())

        def tokens(r):
            return {t.lower() for t in self._TOKEN.findall(f"{r['title']} {r['body']}")}

        cnt, examples = Counter(), defaultdict(list)
        for r in excl:
            for t in tokens(r):
                cnt[t] += 1
                if len(examples[t]) < 2:
                    examples[t].append(r["title"][:90])
        candidates = {t for t, c in cnt.items() if c >= min_count
                      and not (stop and stop.fullmatch(t)) and not (topic and topic.fullmatch(t))}
        if not candidates:
            return []
        others = self.db.query("""
            SELECT id, title, substr(COALESCE(body, ''), 1, 1500) AS body FROM items
            WHERE COALESCE(published_at, fetched_at) >= ?""", (since,))
        bg, n = Counter(), 0
        for r in others:
            if r["id"] in ex_ids:
                continue
            n += 1
            for t in tokens(r) & candidates:
                bg[t] += 1
        res = []
        for t in candidates:
            rate = bg[t] / n if n else 0
            if rate <= 0.002:
                res.append({"word": t, "count": cnt[t], "elsewhere": bg[t], "examples": examples[t]})
        res.sort(key=lambda x: (-x["count"], x["elsewhere"], x["word"]))
        return res[:8]

    def suggestions(self, export_id: Optional[int] = None) -> dict:
        """Подсказки для экрана выгрузки: источники для «только про космос» и стоп-слова."""
        sources = [s for s in self.source_stats() if s["recommended"] and not s["space_only"] and s["enabled"]]
        if export_id is not None:                 # приоритет — источникам, которые убирали в этой выгрузке
            hit = {r["source_id"] for r in self.db.query("""
                SELECT DISTINCT i.source_id FROM export_items ei JOIN items i ON i.id = ei.item_id
                WHERE ei.export_id = ? AND ei.state = 'excluded'""", (export_id,))}
            sources.sort(key=lambda s: (s["id"] not in hit, -s["share"]))
        return {"sources": sources[:6], "stop": self.suggest_stop()}

    # ─── правки ──────────────────────────────────────────────────────────────
    def add_stop(self, word: str) -> str:
        word = word.strip()
        if not word:
            raise ValueError("пустое слово")
        current = self.stop_text().rstrip("\n")
        if word.lower() in {w.lower() for w in words_list(current)}:
            return current
        text = current + "\n" + word + "\n"
        self.settings.update({"filter": {"stop": text}})
        return text
