-- 001: единая база Space Digest 4.0
-- Все даты — ISO-8601 UTC с суффиксом Z: 2026-11-14T09:30:00Z

-- Источники всех типов (RSS-сайты, Telegram-каналы, файлы)
CREATE TABLE sources (
    id          INTEGER PRIMARY KEY,
    key         TEXT    NOT NULL UNIQUE,          -- 'spacenews', 'custom_ab12cd34', 'tg:roscosmos_press'
    kind        TEXT    NOT NULL CHECK (kind IN ('rss', 'telegram', 'file')),
    name        TEXT    NOT NULL,
    url         TEXT    NOT NULL DEFAULT '',      -- адрес ленты или имя канала
    category    TEXT    NOT NULL DEFAULT '',
    region      TEXT    NOT NULL DEFAULT '',
    builtin     INTEGER NOT NULL DEFAULT 0,       -- из встроенного списка (нельзя удалить, можно выключить)
    enabled     INTEGER NOT NULL DEFAULT 1,       -- участвует в сборе и отмечен по умолчанию
    priority    INTEGER NOT NULL DEFAULT 0,       -- для выбора основной публикации сюжета
    config      TEXT    NOT NULL DEFAULT '{}',    -- JSON с настройками коннектора
    created_at  TEXT    NOT NULL
);
CREATE INDEX ix_sources_kind ON sources (kind, enabled);

-- Техническое состояние источника: условные запросы и «здоровье»
CREATE TABLE source_state (
    source_id            INTEGER PRIMARY KEY REFERENCES sources (id) ON DELETE CASCADE,
    etag                 TEXT,
    last_modified        TEXT,
    resolved_url         TEXT,                     -- найденная лента, если в источнике указана страница
    cursor               TEXT,                     -- докуда уже собрано (Telegram: последний id поста)
    last_attempt_at      TEXT,
    last_ok_at           TEXT,
    last_new_at          TEXT,                     -- когда последний раз пришло что-то новое
    last_error           TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_new_items       INTEGER NOT NULL DEFAULT 0
);

-- Каждая публикация: статья сайта, пост канала, строка файла
CREATE TABLE items (
    id             INTEGER PRIMARY KEY,
    source_id      INTEGER NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    external_id    TEXT    NOT NULL,              -- guid/id из ленты, номер поста, url
    url            TEXT    NOT NULL DEFAULT '',
    url_canonical  TEXT    NOT NULL DEFAULT '',
    title          TEXT    NOT NULL DEFAULT '',
    summary        TEXT    NOT NULL DEFAULT '',   -- анонс (description), без обрезки
    body           TEXT    NOT NULL DEFAULT '',   -- полный текст (content:encoded / пост)
    author         TEXT    NOT NULL DEFAULT '',
    published_at   TEXT,
    fetched_at     TEXT    NOT NULL,
    updated_at     TEXT,
    content_hash   TEXT    NOT NULL,
    origin         TEXT    NOT NULL DEFAULT 'collect' CHECK (origin IN ('collect', 'import30', 'file')),
    stage          TEXT    NOT NULL DEFAULT 'new',  -- до какого шага конвейера дошла новость
    UNIQUE (source_id, external_id)
);
CREATE INDEX ix_items_published  ON items (published_at);
CREATE INDEX ix_items_source_pub ON items (source_id, published_at);
CREATE INDEX ix_items_url        ON items (url_canonical) WHERE url_canonical <> '';
CREATE INDEX ix_items_hash       ON items (content_hash);
CREATE INDEX ix_items_stage      ON items (stage);

-- Полнотекстовый поиск
CREATE VIRTUAL TABLE items_fts USING fts5 (
    title, summary, body,
    content = 'items', content_rowid = 'id',
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER items_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts (rowid, title, summary, body) VALUES (new.id, new.title, new.summary, new.body);
END;
CREATE TRIGGER items_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts (items_fts, rowid, title, summary, body) VALUES ('delete', old.id, old.title, old.summary, old.body);
END;
CREATE TRIGGER items_au AFTER UPDATE OF title, summary, body ON items BEGIN
    INSERT INTO items_fts (items_fts, rowid, title, summary, body) VALUES ('delete', old.id, old.title, old.summary, old.body);
    INSERT INTO items_fts (rowid, title, summary, body) VALUES (new.id, new.title, new.summary, new.body);
END;

-- Очередь фоновых задач
CREATE TABLE jobs (
    id           INTEGER PRIMARY KEY,
    type         TEXT    NOT NULL,
    payload      TEXT    NOT NULL DEFAULT '{}',
    dedupe_key   TEXT,                              -- пока такая задача в очереди/в работе, вторую не ставим
    status       TEXT    NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued', 'running', 'done', 'failed', 'cancelled')),
    priority     INTEGER NOT NULL DEFAULT 0,
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    run_after    TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    started_at   TEXT,
    finished_at  TEXT,
    progress     INTEGER NOT NULL DEFAULT 0,
    log          TEXT    NOT NULL DEFAULT '',
    result       TEXT,
    error        TEXT,
    worker       TEXT
);
CREATE UNIQUE INDEX uq_jobs_active_dedupe ON jobs (dedupe_key)
    WHERE dedupe_key IS NOT NULL AND status IN ('queued', 'running');
CREATE INDEX ix_jobs_pick ON jobs (status, run_after, priority);
CREATE INDEX ix_jobs_type ON jobs (type, status);

-- Расписание (интервальное; «в определённое время» добавится миграцией, когда понадобится)
CREATE TABLE schedules (
    name             TEXT    PRIMARY KEY,
    job_type         TEXT    NOT NULL,
    payload          TEXT    NOT NULL DEFAULT '{}',
    interval_minutes INTEGER NOT NULL CHECK (interval_minutes >= 1),
    enabled          INTEGER NOT NULL DEFAULT 1,
    last_run_at      TEXT,
    next_run_at      TEXT
);

-- Служебные отметки (импорт 3.0 выполнен, водяные знаки выгрузок и т. п.)
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
