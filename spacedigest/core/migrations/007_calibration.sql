-- 007: ответы пользователя «одно событие / разные» для подбора порога дедупликации
CREATE TABLE dedup_labels (
    a          INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    b          INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    backend    TEXT    NOT NULL,              -- sentence-transformers | tfidf: у движков разная шкала
    similarity REAL    NOT NULL,
    same       INTEGER NOT NULL CHECK (same IN (0, 1)),
    created_at TEXT    NOT NULL,
    PRIMARY KEY (a, b, backend)
);
