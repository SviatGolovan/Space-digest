"""Встроенные источники (RSS/Atom). Свои источники добавляются в «Настройки → Источники»."""

# ─── 50 ИСТОЧНИКОВ ────────────────────────────────────────────────────────────
# Первые 10 — из вставки пользователя
# Следующие 40 — из документа «40 лучших международных источников»
SOURCES = [

    # ── Блок 1: 10 источников из вставки пользователя ─────────────────────────
    {
        "id": "spacenews", "name": "SpaceNews",
        "url": "https://spacenews.com/feed/",
        "type": "rss", "category": "Ежедневные новости", "region": "США", "enabled": True,
    },
    {
        "id": "europeanspaceflight", "name": "European Spaceflight",
        "url": "https://europeanspaceflight.com/feed/",
        "type": "rss", "category": "Ежедневные новости", "region": "Европа", "enabled": True,
    },
    {
        "id": "satellitetoday", "name": "Satellite Today (Via Satellite)",
        "url": "https://www.satellitetoday.com/feed/",
        "type": "rss", "category": "Отраслевые издания", "region": "США", "enabled": True,
    },
    {
        "id": "csis_aerospace", "name": "CSIS Aerospace Security",
        "url": "https://aerospace.csis.org/feed/",
        "type": "rss", "category": "Аналитика", "region": "США", "enabled": True,
    },
    {
        "id": "arstechnica_space", "name": "Ars Technica – Space",
        "url": "https://feeds.arstechnica.com/arstechnica/science",
        "type": "rss", "category": "Широкопрофильные СМИ", "region": "США", "enabled": True,
    },
    {
        "id": "spacecom", "name": "Space.com",
        "url": "https://www.space.com/feeds/all",
        "type": "rss", "category": "Ежедневные новости", "region": "США", "enabled": True,
    },
    {
        "id": "spacedaily", "name": "Space Daily",
        "url": "http://www.spacedaily.com/spacedaily.xml",
        "type": "rss", "category": "Ежедневные новости", "region": "США", "enabled": True,
    },
    {
        "id": "nasaspaceflight", "name": "NASASpaceflight",
        "url": "https://www.nasaspaceflight.com/feed/",
        "type": "rss", "category": "Ежедневные новости", "region": "США", "enabled": True,
    },
    {
        "id": "spaceindustrynews", "name": "Space Industry News",
        "url": "https://spaceindustrynews.com/feed/",
        "type": "rss", "category": "Отраслевые издания", "region": "США", "enabled": True,
    },
    {
        "id": "universetoday", "name": "Universe Today",
        "url": "https://www.universetoday.com/feed/",
        "type": "rss", "category": "Научпоп", "region": "США", "enabled": True,
    },

    # ── Блок 2: Категория 1 — Основные ежедневные новостные порталы ───────────
    {
        "id": "spaceflightnow", "name": "Spaceflight Now",
        "url": "https://spaceflightnow.com/feed/",
        "type": "rss", "category": "Ежедневные новости", "region": "США", "enabled": True,
    },
    {
        "id": "spaceref", "name": "SpaceRef",
        "url": "https://spaceref.com/feed/",
        "type": "rss", "category": "Ежедневные новости", "region": "США", "enabled": True,
    },
    {
        "id": "nasawatch", "name": "NASAWatch",
        "url": "https://nasawatch.com/feed/",
        "type": "rss", "category": "Ежедневные новости", "region": "США", "enabled": True,
    },
    {
        "id": "spacepolicyonline", "name": "SpacePolicyOnline",
        "url": "https://spacepolicyonline.com/feed/",
        "type": "rss", "category": "Аналитика", "region": "США", "enabled": True,
    },
    {
        "id": "payloadspace", "name": "Payload Space",
        "url": "https://payloadspace.com/feed/",
        "type": "rss", "category": "Ежедневные новости", "region": "США", "enabled": True,
    },
    {
        "id": "americaspace", "name": "AmericaSpace",
        "url": "https://www.americaspace.com/feed/",
        "type": "rss", "category": "Ежедневные новости", "region": "США", "enabled": True,
    },
    {
        "id": "spacewatch", "name": "SpaceWatch.Global",
        "url": "https://spacewatch.global/feed/",
        "type": "rss", "category": "Ежедневные новости", "region": "Германия", "enabled": True,
    },
    {
        "id": "physorg_space", "name": "Phys.org – Space",
        "url": "https://phys.org/rss-feed/space-news/",
        "type": "rss", "category": "Научпоп", "region": "Великобритания", "enabled": True,
    },
    {
        "id": "earthsky", "name": "EarthSky",
        "url": "https://earthsky.org/feed/",
        "type": "rss", "category": "Научпоп", "region": "США", "enabled": True,
    },

    # ── Блок 3: Категория 2 — Специализированные отраслевые издания ───────────
    {
        "id": "aviationweek", "name": "Aviation Week & Space Technology",
        "url": "https://aviationweek.com/rss.xml",
        "type": "rss", "category": "Отраслевые издания", "region": "США", "enabled": True,
    },
    {
        "id": "breakingdefense", "name": "Breaking Defense",
        "url": "https://breakingdefense.com/feed/",
        "type": "rss", "category": "Военный космос", "region": "США", "enabled": True,
    },
    {
        "id": "defensenews_space", "name": "Defense News – Space",
        "url": "https://www.defensenews.com/arc/outboundfeeds/rss/category/space/",
        "type": "rss", "category": "Военный космос", "region": "США", "enabled": True,
    },
    {
        "id": "c4isrnet_space", "name": "C4ISRNET – Space",
        "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/category/battlefield-tech/space/",
        "type": "rss", "category": "Военный космос", "region": "США", "enabled": True,
    },
    {
        "id": "spaceintelreport", "name": "Space Intel Report",
        "url": "https://www.spaceintelreport.com/feed/",
        "type": "rss", "category": "Отраслевые издания", "region": "США/Франция", "enabled": True,
    },
    {
        "id": "satnews", "name": "SatNews Daily",
        "url": "https://satnews.com/feed/",
        "type": "rss", "category": "Отраслевые издания", "region": "США", "enabled": True,
    },
    {
        "id": "parabolicarc", "name": "Parabolic Arc",
        "url": "https://parabolicarc.com/feed/",
        "type": "rss", "category": "Коммерческий космос", "region": "США", "enabled": True,
    },

    # ── Блок 4: Категория 3 — Научно-популярные и астрономические издания ─────
    {
        "id": "astronomy", "name": "Astronomy Magazine",
        "url": "https://www.astronomy.com/feed/",
        "type": "rss", "category": "Научпоп", "region": "США", "enabled": True,
    },
    {
        "id": "skyandtelescope", "name": "Sky & Telescope",
        "url": "https://skyandtelescope.org/feed/",
        "type": "rss", "category": "Научпоп", "region": "США", "enabled": True,
    },
    {
        "id": "sciencenews_space", "name": "Science News – Space",
        "url": "https://www.sciencenews.org/topic/space/feed",
        "type": "rss", "category": "Научпоп", "region": "США", "enabled": True,
    },
    {
        "id": "planetary", "name": "The Planetary Society",
        "url": "https://www.planetary.org/feed",
        "type": "rss", "category": "Научпоп", "region": "США", "enabled": True,
    },
    {
        "id": "astronomynow", "name": "Astronomy Now",
        "url": "https://astronomynow.com/feed/",
        "type": "rss", "category": "Научпоп", "region": "Великобритания", "enabled": True,
    },

    # ── Блок 5: Категория 4 — Аналитика и мнения ──────────────────────────────
    {
        "id": "thespacereview", "name": "The Space Review",
        "url": "https://www.thespacereview.com/index.xml",
        "type": "rss", "category": "Аналитика", "region": "США", "enabled": True,
    },
    {
        "id": "spaceq", "name": "SpaceQ (Canada)",
        "url": "https://spaceq.ca/feed/",
        "type": "rss", "category": "Аналитика", "region": "Канада", "enabled": True,
    },
    {
        "id": "spacefoundation", "name": "Space Foundation News",
        "url": "https://www.spacefoundation.org/feed/",
        "type": "rss", "category": "Аналитика", "region": "США", "enabled": False,
    },

    # ── Блок 6: Категория 5 — Международные региональные источники ────────────
    {
        "id": "esa_newsroom", "name": "ESA Newsroom",
        "url": "https://www.esa.int/rssfeed/Newsroom",
        "type": "rss", "category": "Космические агентства", "region": "Европа", "enabled": True,
    },
    {
        "id": "xinhua_space", "name": "Xinhua – Space",
        "url": "http://www.xinhuanet.com/english/rss/scienceRSS.xml",
        "type": "rss", "category": "Международные", "region": "Китай", "enabled": True,
    },
    {
        "id": "cgtn_space", "name": "CGTN Science & Space",
        "url": "https://www.cgtn.com/rss/sci-tech.xml",
        "type": "rss", "category": "Международные", "region": "Китай", "enabled": True,
    },
    {
        # Раньше здесь стояла rss/91 — общая лента издания (политика, Гонконг, бизнес): до 50 новостей
        # в день не про космос. Лента научного раздела + «только про космос».
        "id": "scmp_space", "name": "South China Morning Post – Science",
        "url": "https://www.scmp.com/rss/328475/feed",
        "type": "rss", "category": "Международные", "region": "Гонконг", "enabled": True,
        "space_only": True,
    },
    {
        "id": "aerospaceglobalnews", "name": "Aerospace Global News",
        "url": "https://aerospaceglobalnews.com/feed/",
        "type": "rss", "category": "Ежедневные новости", "region": "Международное", "enabled": True,
    },
    {
        "id": "spaceinafrica", "name": "Space in Africa",
        "url": "https://spaceinafrica.com/feed/",
        "type": "rss", "category": "Международные", "region": "Африка", "enabled": True,
    },

    # ── Блок 7: Категория 6 — Широкопрофильные СМИ ───────────────────────────
    {
        "id": "nbcnews_space", "name": "NBC News – Space",
        "url": "https://feeds.nbcnews.com/nbcnews/public/science",
        "type": "rss", "category": "Широкопрофильные СМИ", "region": "США", "enabled": True,
    },
    {
        "id": "cbsnews_space", "name": "CBS News – Space",
        "url": "https://www.cbsnews.com/latest/rss/science",
        "type": "rss", "category": "Широкопрофильные СМИ", "region": "США", "enabled": True,
    },
    {
        "id": "guardian_space", "name": "The Guardian – Space",
        "url": "https://www.theguardian.com/science/space/rss",
        "type": "rss", "category": "Широкопрофильные СМИ", "region": "Великобритания", "enabled": True,
    },
    {
        "id": "reuters_aerospace", "name": "Reuters – Aerospace & Defense",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "type": "rss", "category": "Широкопрофильные СМИ", "region": "Международное", "enabled": True,
    },

    # ── Блок 8: Категория 7 — Нишевые и развивающиеся медиа ──────────────────
    {
        "id": "teslarati_spacex", "name": "Teslarati – SpaceX",
        "url": "https://www.teslarati.com/category/spacex/feed/",
        "type": "rss", "category": "Коммерческий космос", "region": "США", "enabled": True,
    },
    {
        "id": "marsdaily", "name": "Mars Daily",
        "url": "http://www.marsdaily.com/marsdaily.xml",
        "type": "rss", "category": "Нишевые", "region": "США", "enabled": True,
    },
    {
        "id": "spacetoday", "name": "Spacetoday.net",
        "url": "https://spacetoday.net/rss.xml",
        "type": "rss", "category": "Нишевые", "region": "США", "enabled": False,
    },
    {
        "id": "geospatialworld", "name": "Geospatial World – Satellite",
        "url": "https://www.geospatialworld.net/feed/",
        "type": "rss", "category": "Нишевые", "region": "Индия", "enabled": True,
    },
    {
        "id": "spaceinsider", "name": "SpaceInsider.tech",
        "url": "https://spaceinsider.tech/feed/",
        "type": "rss", "category": "Нишевые", "region": "Международное", "enabled": True,
    },
    {
        "id": "aircosmos", "name": "Air & Cosmos (France)",
        "url": "https://www.air-cosmos.com/feed/",
        "type": "rss", "category": "Международные", "region": "Франция", "enabled": False,
    },
]
