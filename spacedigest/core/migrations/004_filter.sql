-- 004: фильтр мусора
-- «Только про космос»: новость источника попадает в выгрузку, только если в ней есть
-- космические слова (для лент общего профиля: South China Morning Post, Breaking Defense…).
ALTER TABLE sources ADD COLUMN space_only INTEGER NOT NULL DEFAULT 0;

-- Новая роль в выгрузке: filtered — отсеяна фильтром (reason — какое правило сработало).
ALTER TABLE export_items ADD COLUMN reason TEXT;
