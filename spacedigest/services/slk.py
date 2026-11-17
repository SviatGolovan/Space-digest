"""
Дайджест по РН сверхлёгкого класса (СЛК): мягкий предфильтр перед ChatGPT.

Отбор по теме делает ChatGPT по промпту — содержательно, с учётом омонимов. Задача
программы скромнее: не отдать ему тысячи строк про всё подряд. Поэтому режется только
явно лишнее, и всё отрезанное видно во вкладке «Отфильтровано» с причиной:

1. Стоп-слова фильтра мусора (реклама, розыгрыши) — для всех источников.
2. Сайт компании из перечня ТЗ (slk_trusted) — проходит всё.
3. В тексте есть название РН или компании из перечня, или термин «сверхлёгкий класс» —
   проходит (даже если рядом военная тематика: «Ангара», «Союз-5»).
4. Явно военная тематика (ракетный удар, ПВО, «Искандер») без названий из перечня — отсев.
5. Издание общего профиля (РБК, КП…): нужно и однозначно космическое слово
   (космос, орбита, спутник, космодром…), и ракетное.
   Космическое издание или канал: достаточно ракетного слова (пуск, двигатель, космодром…).

Словари правятся в Настройки → СЛК (синтаксис как у фильтра мусора: «ракет*» — все
формы слова, «РН» — только целое слово, «огнев* испытан*» — фраза).
"""
from __future__ import annotations

from typing import Optional

from ..core.db import Database
from .filters import ContentFilter, compile_words

# Издания общего профиля: «запуск сервиса», «звезда эстрады», «ракетка» — не космос.
# Поэтому для них нужно ещё и однозначно космическое слово из этого короткого списка.
GENERAL_CORE = """косм*
космодром*
роскосм*
орбит*
носител*
ракетоносител*
спутни*
МКС
суборбитал*
ЖРД
РДТТ
байконур*
плесецк*
space*
orbit*
satellit*
spacecraft*
spaceport*
launch vehicle*
"""

DEFAULT_NAMES = """# РН из перечня ТЗ
Electron
Ceres-1
Ceres 1
Церера-1
Pegasus*
Пегас-XL
SSLV
Hyperbola*
Гипербола*
SQX-1
Minotaur*
Минотавр*
Long March 11*
Long March 6*
LM-11
CZ-11
LM-6
CZ-6
Чанчжэн-11
Чанчжэн-6
Kuaizhou*
KZ-11
Куайчжоу*
Jielong*
Smart Dragon*
Смарт Дракон*
Epsilon*
Эпсилон*
Старт-1*
Рокот*
Ангара-1.2
Ангара 1.2
Ангара-А5М
Ангара А5М
Союз-2.1б
Союз-2.1в
Союз-5
Иртыш
Союз-7
Амур-СПГ
Амур СПГ
ЛАРОС-РН
Spectrum
Hybris
Firefly Alpha
Firefly Alfa
# Компании из перечня ТЗ
Rocket Lab
RocketLab
Рокет Лаб
Galactic Energy
Northrop Grumman
Orbital ATK
Orbital Sciences
NewSpace India
NSIL
i-Space
Interstellar Glory
CALT
CALVT
China Academy of Launch Vehicle Technology
Isar Aerospace
Firefly Aerospace
CASIC
ExPace
КБХА
химавтоматик*
ВНХ-Энерго
Военмех*
3ДИР
3Д Исследования
ЦНИИмаш*
Хруничев*
ГКНПЦ
РКЦ Прогресс
РКЦ «Прогресс»
Самспейс
SR Space
СР Спейс
ЛАРОС
Космокурс*
Космические Транспортные Системы
Лин Индастриал*
Lin Industrial
НСТР КС
Космическая энергия
Space Energy
ЧКК НОЙ
# Другие игроки рынка малых носителей
ABL Space
Orbex
Skyrora
PLD Space
Miura*
Latitude
Gilmour*
Relativity
Astra Space
Virgin Orbit
LauncherOne
Vega*
Agnibaan
Agnikul*
Skyroot
Vikram-1
Zhuque*
Чжуцюэ*
Ceres-2
Gravity-1
Tianlong*
Lijian*
Kinetica*
Success Rockets
# Класс носителя
СЛК
сверхлегк*
сверхлёгк*
микроносител*
наноносител*
small launch*
small-lift*
smallsat launch*
small launcher*
micro-launcher*
microlauncher*
micro launcher*
nanolauncher*
dedicated smallsat*
"""

DEFAULT_ROCKET = """# Русские
ракет*
носител*
РН
пуск*
запуск*
космодром*
стартов*
ЖРД
РДТТ
двигател*
ступен*
огнев* испытан*
стендов* испытан*
летн* испытан*
лётн* испытан*
суборбитал*
выведен*
орбит*
полезн* нагрузк*
кубсат*
МКА
# English
launch*
rocket*
launcher*
liftoff
lift-off
booster*
engine*
static fire
hot fire
hotfire
first stage
second stage
upper stage
suborbital
orbital
spaceport*
launch pad
payload*
rideshare
smallsat*
cubesat*
maiden flight
"""

DEFAULT_MILITARY = """# Боевые ракеты и ПВО (отсев, если нет названий из перечня)
ракетн* удар*
ракетн* атак*
ракетн* обстрел*
обстрел*
крылат* ракет*
баллистическ* ракет*
зенитн*
противотанк*
ПВО
перехват*
сбит*
Искандер*
Калибр*
Кинжал*
Орешник*
Ярс*
Булава*
Сармат*
Тополь*
ATACMS
HIMARS
Patriot
Storm Shadow
Tomahawk
боеголовк*
ВСУ
missile strike*
air defense
air defence
intercept*
"""


class SlkFilter:
    """Тот же интерфейс, что у ContentFilter (enabled/checker/split), — выгрузка не знает разницы."""

    def __init__(self, db: Database, settings, junk: Optional[ContentFilter] = None):
        self.db = db
        self.settings = settings
        self.junk = junk or ContentFilter(db, settings)

    def cfg(self) -> dict:
        return self.settings.get("slk") or {}

    def enabled(self) -> bool:
        return bool(self.cfg().get("prefilter", True)) or self.junk.enabled()

    def words(self, key: str) -> str:
        default = {"names": DEFAULT_NAMES, "rocket": DEFAULT_ROCKET, "military": DEFAULT_MILITARY}[key]
        return (self.cfg().get(key) or "").strip() or default

    def _sources(self) -> dict[int, dict]:
        import json
        out = {}
        for r in self.db.query("SELECT id, kind, config FROM sources"):
            try:
                cfg = json.loads(r["config"] or "{}")
            except ValueError:
                cfg = {}
            out[r["id"]] = cfg
        return out

    def checker(self):
        junk = self.junk.checker() if self.junk.enabled() else (lambda row: None)
        if not self.cfg().get("prefilter", True):
            return junk
        names, rocket = compile_words(self.words("names")), compile_words(self.words("rocket"))
        military, space = compile_words(self.words("military")), compile_words(GENERAL_CORE)
        sources = self._sources()

        def check(row: dict) -> Optional[str]:
            if (reason := junk(row)):
                return reason
            cfg = sources.get(row.get("source_id"), {})
            if cfg.get("slk_trusted"):
                return None
            text = ContentFilter._text(row)
            if names and names.search(text):
                return None
            if military and (m := military.search(text)):
                return f"военная тематика «{m.group(0).strip()}» (предфильтр СЛК)"
            if cfg.get("general") and space and not space.search(text):
                return "не про космос (издание общего профиля, предфильтр СЛК)"
            if rocket and not rocket.search(text):
                return "не про ракеты и пуски (предфильтр СЛК)"
            return None
        return check

    def passes(self, row: dict) -> bool:
        """Для дотягивания полного текста: стоит ли открывать статью общего сайта.
        Правила пересобираются раз в 5 минут (новые источники и правки словарей)."""
        import time
        if not hasattr(self, "_gate") or time.monotonic() - self._gate_at > 300:
            self._gate, self._gate_at = self.checker(), time.monotonic()
        return self._gate(row) is None

    def split(self, rows: list[dict]) -> tuple[list[dict], dict[int, str]]:
        if not rows:
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
