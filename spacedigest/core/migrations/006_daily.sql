-- 006: расписания «каждый день в ЧЧ:ММ по Москве» (утренняя выгрузка)
ALTER TABLE schedules ADD COLUMN at_time TEXT;
