-- 008: дайджест по РН сверхлёгкого класса (СЛК) в общей базе + надёжные даты

-- Откуда взята дата публикации:
--   NULL      — из ленты RSS/Atom или Telegram (надёжно)
--   card      — из карточки на странице новостей сайта
--   page      — со страницы самой статьи (метаданные)
--   none      — дата неизвестна; published_at = время, когда новость впервые замечена
--   baseline  — дата неизвестна, и новость пришла при самом первом сборе источника:
--               это архив сайта, а не свежая новость — в выгрузки не идёт
ALTER TABLE items ADD COLUMN date_status TEXT;
CREATE INDEX ix_items_date_status ON items (date_status) WHERE date_status IS NOT NULL;

-- В какие выгрузки идёт источник: all — в обе, space — только в общую, slk — только в СЛК
ALTER TABLE sources ADD COLUMN scope TEXT NOT NULL DEFAULT 'all';

-- Выгрузки: общая (space) и СЛК (slk) ведут раздельную историю
ALTER TABLE exports ADD COLUMN profile TEXT NOT NULL DEFAULT 'space';
CREATE INDEX ix_exports_profile ON exports (profile, id);

-- Пометка строки выгрузки, например «было в дайджесте СЛК от 30.10.2026»
ALTER TABLE export_items ADD COLUMN note TEXT;
