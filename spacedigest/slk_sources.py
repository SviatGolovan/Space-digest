"""
Источники дайджеста по РН сверхлёгкого класса (перенесены из парсера СЛК 3.1).

Идут только в выгрузку СЛК (scope = "slk"); выгрузка СЛК при этом читает и все общие
источники Space Digest (scope = "all"). Шесть отраслевых лент из старого списка
(SpaceNews, NASASpaceflight, Spaceflight Now, European Spaceflight, Payload, SpaceWatch)
здесь не повторяются — они уже есть среди встроенных источников Space Digest.

config:
  html          — у сайта нет RSS: разбирается страница новостей (connectors/html_page.py)
  item_selector — CSS-селектор карточки новости, если автоматический разбор ошибается
  slk_trusted   — сайт компании из перечня ТЗ: в выгрузку СЛК идёт всё, без предфильтра
  general       — издание общего профиля (РБК, КП…): сначала проверка «про космос ли»
  fulltext      — "match": полный текст статьи открывается, только если новость
                  прошла предфильтр СЛК (иначе это сотни лишних запросов к сайту)

Китайские сайты (casic, calt, i-space, expace) часто не отвечают из-за пределов КНР —
это блокировка на их стороне; новости о компаниях придут через отраслевые издания.
"""

SLK_SOURCES = [
    {"id": "slk_rocketlab", "name": "Rocket Lab", "url": "https://rocketlabcorp.com/updates/", "category": "СЛК · Сайты компаний", "region": "США", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_galactic_energy", "name": "Galactic Energy", "url": "https://www.galactic-energy.cn/index.php/News/index.html", "category": "СЛК · Сайты компаний", "region": "Китай", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_northrop", "name": "Northrop Grumman", "url": "https://news.northropgrumman.com/news/releases?pagetemplate=rss", "category": "СЛК · Сайты компаний", "region": "США", "enabled": True, "config": {"fulltext": "match"}},
    {"id": "slk_isro", "name": "ISRO", "url": "https://www.isro.gov.in/rss.xml", "category": "СЛК · Сайты компаний", "region": "Индия", "enabled": True, "config": {"slk_trusted": True}},
    {"id": "slk_nsil", "name": "NewSpace India Limited (NSIL)", "url": "https://www.nsilindia.co.in/media-gallery", "category": "СЛК · Сайты компаний", "region": "Индия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_ispace_cn", "name": "iSpace (Interstellar Glory)", "url": "http://www.i-space.com.cn/news.html", "category": "СЛК · Сайты компаний", "region": "Китай", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_calt", "name": "China Academy of Launch Vehicle Technology", "url": "http://www.calt.com/col/col2201/index.html", "category": "СЛК · Сайты компаний", "region": "Китай", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_isar", "name": "Isar Aerospace", "url": "https://www.isaraerospace.com/newsroom", "category": "СЛК · Сайты компаний", "region": "Германия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_firefly", "name": "Firefly Aerospace", "url": "https://fireflyspace.com/news/", "category": "СЛК · Сайты компаний", "region": "США", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_casic", "name": "CASIC (China Aerospace Sci. & Industry)", "url": "http://www.casic.com.cn/n189298/n189314/index.html", "category": "СЛК · Сайты компаний", "region": "Китай", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_expace", "name": "ExPace", "url": "http://www.expace.com.cn/news/", "category": "СЛК · Сайты компаний", "region": "Китай", "enabled": False, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_jaxa", "name": "JAXA", "url": "https://global.jaxa.jp/rss/press.rdf", "category": "СЛК · Сайты компаний", "region": "Япония", "enabled": True, "config": {"slk_trusted": True}},
    {"id": "slk_kbkha", "name": "АО КБХА", "url": "https://kbkha.ru/news/", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_vnh_energo", "name": "ООО «ВНХ-Энерго»", "url": "https://vnh-energo.ru/", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_voenmeh", "name": "БГТУ «ВОЕНМЕХ»", "url": "https://voenmeh.ru/news", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "fulltext": "match"}},
    {"id": "slk_3drd", "name": "3Д Исследования и Разработки", "url": "https://3drd.ru/", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_tsniimash", "name": "АО «ЦНИИмаш»", "url": "https://tsniimash.ru/press/news/", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "fulltext": "match"}},
    {"id": "slk_khrunichev", "name": "ГКНПЦ им. М. В. Хруничева", "url": "http://www.khrunichev.ru/main.php?id=1", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_progress_rkc", "name": "РКЦ «Прогресс»", "url": "https://www.samspace.ru/news/", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_srspace", "name": "SR Space / АО «СР Спейс»", "url": "https://srspace.ru/news/", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_laros", "name": "ЛАРОС / ООО «КБ ЛАРОС»", "url": "https://laros.ru/news", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_lin_industrial", "name": "ООО «ЛИН ИНДАСТРИАЛ»", "url": "https://spacelin.ru/", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_space_energy", "name": "ООО «КОСМИЧЕСКАЯ ЭНЕРГИЯ» / Space Energy", "url": "https://spaceenergy.su/", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_noy_space", "name": "ЧКК «НОЙ»", "url": "https://noyspace.com/", "category": "СЛК · Сайты компаний", "region": "Россия", "enabled": True, "config": {"html": True, "slk_trusted": True}},
    {"id": "slk_roscosmos", "name": "Роскосмос", "url": "https://www.roscosmos.ru/rss/", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"fulltext": "match"}},
    {"id": "slk_skyrocket", "name": "Gunter's Space Page", "url": "https://space.skyrocket.de/directories/chronology.htm", "category": "СЛК · Новостные сайты", "region": "Германия", "enabled": False, "config": {"html": True, "fulltext": "match"}},
    {"id": "slk_habr", "name": "Хабр — Космонавтика", "url": "https://habr.com/ru/rss/hub/cosmonautics/all/?fl=ru", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"fulltext": "match"}},
    {"id": "slk_rbc", "name": "РБК", "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"general": True, "fulltext": "match"}},
    {"id": "slk_kp", "name": "Комсомольская правда", "url": "https://www.kp.ru/rss/allsections.xml", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"general": True, "fulltext": "match"}},
    {"id": "slk_kommersant", "name": "Коммерсантъ", "url": "https://www.kommersant.ru/RSS/news.xml", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"general": True, "fulltext": "match"}},
    {"id": "slk_ria", "name": "РИА Новости — Космос", "url": "https://ria.ru/export/rss2/space/index.xml", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"fulltext": "match"}},
    {"id": "slk_forbes", "name": "Forbes", "url": "https://www.forbes.com/innovation/feed2/", "category": "СЛК · Новостные сайты", "region": "США", "enabled": True, "config": {"general": True, "fulltext": "match"}},
    {"id": "slk_prokosmos", "name": "Proкосмос", "url": "https://prokosmos.ru/feed", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"fulltext": "match"}},
    {"id": "slk_interfax", "name": "Интерфакс", "url": "https://www.interfax.ru/rss.asp", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"general": True, "fulltext": "match"}},
    {"id": "slk_in_space", "name": "In Space", "url": "https://in-space.ru/feed/", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"fulltext": "match"}},
    {"id": "slk_naked_science", "name": "NakedScience", "url": "https://naked-science.ru/feed", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"fulltext": "match"}},
    {"id": "slk_rocketlaunch", "name": "RocketLaunch.org", "url": "https://rocketlaunch.org/launch-schedule", "category": "СЛК · Новостные сайты", "region": "США", "enabled": True, "config": {"html": True, "fulltext": "match"}},
    {"id": "slk_spacelaunchschedule", "name": "Space Launch Schedule", "url": "https://www.spacelaunchschedule.com/", "category": "СЛК · Новостные сайты", "region": "США", "enabled": True, "config": {"html": True, "fulltext": "match"}},
    {"id": "slk_ixbt", "name": "iXBT", "url": "https://www.ixbt.com/export/news.rss", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"general": True, "fulltext": "match"}},
    {"id": "slk_3dnews", "name": "3DNews", "url": "https://3dnews.ru/news/rss/", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"general": True, "fulltext": "match"}},
    {"id": "slk_mk", "name": "Московский Комсомолец", "url": "https://www.mk.ru/rss/index.xml", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"general": True, "fulltext": "match"}},
    {"id": "slk_mosregdata", "name": "Данные Московской области", "url": "https://mosregdata.ru", "category": "СЛК · Новостные сайты", "region": "Россия", "enabled": True, "config": {"html": True, "general": True, "fulltext": "match"}},
    {"id": "slk_tass_space", "name": "ТАСС — Космос", "url": "https://tass.ru/rss/v2.xml", "category": "СЛК · Доп. источники", "region": "Россия", "enabled": False, "config": {"fulltext": "match"}},
]

# Telegram-каналы компаний: у сайта Space Energy нет дат у новостей, а в канале они есть
SLK_TELEGRAM = [
    {"channel": "se_data", "name": "Space Energy (Telegram)", "trusted": True},
]
