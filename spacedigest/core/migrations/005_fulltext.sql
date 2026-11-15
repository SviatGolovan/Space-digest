-- 005: полный текст статей для лент, которые отдают только анонс
--   fulltext_status: NULL — не пробовали; ok — текст взят со страницы статьи;
--   same — на странице не больше, чем в ленте; failed — страница не открылась / текст не извлечён.
ALTER TABLE items ADD COLUMN fulltext_status TEXT;
ALTER TABLE items ADD COLUMN fulltext_at TEXT;
CREATE INDEX idx_items_fulltext ON items (source_id, fulltext_status);
