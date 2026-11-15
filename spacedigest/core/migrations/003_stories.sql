-- 003: сюжеты в выгрузке и кэш векторов для сверки повторов

-- Роль новости в выгрузке:
--   main     — своя строка CSV (основная версия сюжета);
--   merged   — другая версия того же события, её новые факты дописаны в строку main (duplicate_of);
--   known    — уже было в прошлой выгрузке (duplicate_of — та новость), в CSV не попала;
--   excluded — убрана пользователем вручную.
ALTER TABLE export_items ADD COLUMN state TEXT NOT NULL DEFAULT 'main';
ALTER TABLE export_items ADD COLUMN similarity REAL;

UPDATE export_items SET state = CASE
    WHEN row_no IS NOT NULL THEN 'main'
    WHEN duplicate_of IN (SELECT e2.item_id FROM export_items e2
                          WHERE e2.export_id = export_items.export_id AND e2.row_no IS NOT NULL)
        THEN 'merged'
    ELSE 'known'
END;

-- Векторы смысловой близости (нейросеть). Считаются один раз на новость,
-- поэтому сверка с прошлыми выгрузками не пересчитывает тысячи текстов каждый день.
CREATE TABLE item_vectors (
    item_id   INTEGER PRIMARY KEY REFERENCES items (id) ON DELETE CASCADE,
    model     TEXT    NOT NULL,
    text_hash TEXT    NOT NULL,
    vec       BLOB    NOT NULL,
    created_at TEXT   NOT NULL
);
