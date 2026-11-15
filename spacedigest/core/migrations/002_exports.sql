-- 002: выгрузки для ChatGPT (и любых других получателей)

CREATE TABLE exports (
    id                 INTEGER PRIMARY KEY,
    created_at         TEXT    NOT NULL,
    mode               TEXT    NOT NULL CHECK (mode IN ('since_last', 'dates')),
    period_from        TEXT,                         -- локальная дата публикации самой ранней новости
    period_to          TEXT,                         -- … и самой поздней (для промпта)
    fetched_until      TEXT    NOT NULL,             -- водяной знак: всё собранное до этого момента учтено
    kinds              TEXT    NOT NULL DEFAULT 'rss,telegram',
    items_selected     INTEGER NOT NULL DEFAULT 0,
    items_exported     INTEGER NOT NULL DEFAULT 0,
    duplicates_removed INTEGER NOT NULL DEFAULT 0,
    folder             TEXT    NOT NULL,
    csv_file           TEXT,
    prompt_file        TEXT,
    result_file        TEXT,                         -- готовый DOCX от ChatGPT
    status             TEXT    NOT NULL DEFAULT 'prepared' CHECK (status IN ('prepared', 'done'))
);
CREATE INDEX ix_exports_created ON exports (created_at);

-- Какие новости вошли в выгрузку (и какие были отсеяны как повторы)
CREATE TABLE export_items (
    export_id    INTEGER NOT NULL REFERENCES exports (id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    row_no       INTEGER,                            -- номер строки в CSV (NULL — повтор, не выгружен)
    duplicate_of INTEGER,                            -- item_id основной версии
    PRIMARY KEY (export_id, item_id)
);
CREATE INDEX ix_export_items_item ON export_items (item_id);
