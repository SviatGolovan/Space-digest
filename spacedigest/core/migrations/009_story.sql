-- 009: «один сюжет» — связанные строки выгрузки (модель e5-small, см. story_model.py)

-- Векторы заголовков для модели сюжетов (отдельно от item_vectors склейки: другая модель)
CREATE TABLE story_vectors (
    item_id    INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    text_hash  TEXT NOT NULL,
    vec        BLOB NOT NULL,
    created_at TEXT NOT NULL
);

-- id других основных новостей выгрузки того же сюжета (JSON-массив)
ALTER TABLE export_items ADD COLUMN related TEXT;
