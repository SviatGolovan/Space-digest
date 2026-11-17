## Замер дедупликатора

Пар «одно событие»: 43. Ложная склейка весит 1,5 пропуска.

| Модель | Текст | Окно, дн | Предохр. | При 0.82: найдено / ложных | Лучший порог | Найдено | Ложных | Сюжет склеено | Неразмеч. выше порога |
|---|---|---|---|---|---|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title | — | нет | 3 / 2 | 0.86 | 2 | 0 | 0 | 12 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title | 4 | нет | 3 / 2 | 0.86 | 2 | 0 | 0 | 10 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title | 4 | да | 3 / 2 | 0.86 | 2 | 0 | 0 | 10 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+300 | — | нет | 7 / 1 | 0.82 | 7 | 1 | 1 | 14 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+300 | 4 | нет | 7 / 1 | 0.82 | 7 | 1 | 1 | 7 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+300 | 4 | да | 7 / 0 | 0.82 | 7 | 0 | 1 | 6 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+800 | — | нет | 5 / 1 | 0.83 | 4 | 0 | 2 | 11 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+800 | 4 | нет | 5 / 1 | 0.83 | 4 | 0 | 2 | 4 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+800 | 4 | да | 5 / 1 | 0.81 | 7 | 2 | 2 | 25 |
| multilingual-e5-small  | title | — | нет | 43 / 80 | 0.93 | 12 | 3 | 1 | 22 |
| multilingual-e5-small  | title | 4 | нет | 43 / 80 | 0.93 | 12 | 3 | 1 | 13 |
| multilingual-e5-small  | title | 4 | да | 42 / 65 | 0.93 | 12 | 1 | 1 | 12 |
| multilingual-e5-small  | title+300 | — | нет | 43 / 85 | 0.94 | 9 | 3 | 0 | 7 |
| multilingual-e5-small  | title+300 | 4 | нет | 43 / 85 | 0.94 | 9 | 3 | 0 | 2 |
| multilingual-e5-small  | title+300 | 4 | да | 42 / 70 | 0.94 | 8 | 1 | 0 | 2 |
| multilingual-e5-small  | title+800 | — | нет | 43 / 86 | 0.95 | 10 | 7 | 0 | 9 |
| multilingual-e5-small  | title+800 | 4 | нет | 43 / 86 | 0.95 | 10 | 7 | 0 | 1 |
| multilingual-e5-small  | title+800 | 4 | да | 42 / 71 | 0.95 | 9 | 7 | 0 | 1 |
| multilingual-e5-base  | title | — | нет | 43 / 75 | 0.93 | 11 | 2 | 0 | 25 |
| multilingual-e5-base  | title | 4 | нет | 43 / 75 | 0.93 | 11 | 2 | 0 | 14 |
| multilingual-e5-base  | title | 4 | да | 42 / 62 | 0.92 | 13 | 1 | 1 | 31 |
| multilingual-e5-base  | title+300 | — | нет | 43 / 85 | 0.95 | 10 | 4 | 0 | 4 |
| multilingual-e5-base  | title+300 | 4 | нет | 43 / 85 | 0.95 | 10 | 4 | 0 | 0 |
| multilingual-e5-base  | title+300 | 4 | да | 42 / 70 | 0.95 | 9 | 3 | 0 | 0 |
| multilingual-e5-base  | title+800 | — | нет | 43 / 86 | 0.95 | 19 | 15 | 3 | 15 |
| multilingual-e5-base  | title+800 | 4 | нет | 43 / 86 | 0.95 | 19 | 15 | 3 | 7 |
| multilingual-e5-base  | title+800 | 4 | да | 42 / 71 | 0.95 | 18 | 13 | 3 | 7 |
| paraphrase-multilingual-mpnet-base-v2  | title | — | нет | 6 / 2 | 0.83 | 5 | 1 | 0 | 57 |
| paraphrase-multilingual-mpnet-base-v2  | title | 4 | нет | 6 / 2 | 0.83 | 5 | 1 | 0 | 37 |
| paraphrase-multilingual-mpnet-base-v2  | title | 4 | да | 6 / 2 | 0.78 | 8 | 3 | 1 | 113 |
| paraphrase-multilingual-mpnet-base-v2  | title+300 | — | нет | 17 / 12 | 0.89 | 4 | 1 | 0 | 6 |
| paraphrase-multilingual-mpnet-base-v2  | title+300 | 4 | нет | 17 / 12 | 0.89 | 4 | 1 | 0 | 2 |
| paraphrase-multilingual-mpnet-base-v2  | title+300 | 4 | да | 16 / 6 | 0.83 | 15 | 3 | 2 | 25 |
| paraphrase-multilingual-mpnet-base-v2  | title+800 | — | нет | 15 / 12 | 0.86 | 9 | 3 | 1 | 26 |
| paraphrase-multilingual-mpnet-base-v2  | title+800 | 4 | нет | 15 / 12 | 0.86 | 9 | 3 | 1 | 14 |
| paraphrase-multilingual-mpnet-base-v2  | title+800 | 4 | да | 14 / 7 | 0.80 | 20 | 8 | 2 | 68 |
| LaBSE тяжелее бюджета | title | — | нет | 7 / 1 | 0.75 | 13 | 3 | 4 | 64 |
| LaBSE тяжелее бюджета | title | 4 | нет | 7 / 1 | 0.75 | 13 | 3 | 4 | 43 |
| LaBSE тяжелее бюджета | title | 4 | да | 7 / 1 | 0.75 | 13 | 1 | 4 | 40 |
| LaBSE тяжелее бюджета | title+300 | — | нет | 10 / 10 | 0.93 | 1 | 0 | 0 | 0 |
| LaBSE тяжелее бюджета | title+300 | 4 | нет | 10 / 10 | 0.93 | 1 | 0 | 0 | 0 |
| LaBSE тяжелее бюджета | title+300 | 4 | да | 10 / 7 | 0.85 | 6 | 3 | 1 | 3 |
| LaBSE тяжелее бюджета | title+800 | — | нет | 12 / 19 | 0.89 | 4 | 1 | 4 | 4 |
| LaBSE тяжелее бюджета | title+800 | 4 | нет | 12 / 19 | 0.89 | 4 | 1 | 4 | 0 |
| LaBSE тяжелее бюджета | title+800 | 4 | да | 12 / 16 | 0.89 | 4 | 1 | 4 | 0 |
| bge-m3 тяжелее бюджета, для сравнения | title+300 | — | нет | 16 / 12 | 0.89 | 3 | 1 | 0 | 2 |
| bge-m3 тяжелее бюджета, для сравнения | title+300 | 4 | нет | 16 / 12 | 0.89 | 3 | 1 | 0 | 0 |
| bge-m3 тяжелее бюджета, для сравнения | title+300 | 4 | да | 15 / 9 | 0.82 | 15 | 9 | 1 | 10 |
