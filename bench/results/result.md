## Замер дедупликатора

Пар «одно событие»: 145. Ложная склейка весит 1,5 пропуска.

| Модель | Текст | Окно, дн | Предохр. | При 0.82: найдено / ложных | Лучший порог | Найдено | Ложных | Сюжет склеено | Неразмеч. выше порога |
|---|---|---|---|---|---|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title | — | нет | 25 / 3 | 0.72 | 87 | 20 | 39 | 193 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title | 4 | нет | 25 / 3 | 0.72 | 87 | 20 | 39 | 79 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title | 4 | да | 25 / 3 | 0.72 | 87 | 19 | 39 | 68 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+300 | — | нет | 11 / 1 | 0.71 | 113 | 37 | 49 | 250 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+300 | 4 | нет | 11 / 1 | 0.71 | 113 | 37 | 49 | 144 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+300 | 4 | да | 11 / 0 | 0.71 | 112 | 29 | 49 | 122 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+800 | — | нет | 9 / 1 | 0.72 | 113 | 37 | 50 | 275 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+800 | 4 | нет | 9 / 1 | 0.72 | 113 | 37 | 50 | 161 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+800 | 4 | да | 9 / 1 | 0.72 | 112 | 30 | 50 | 139 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title | — | нет | 139 / 103 | 0.90 | 55 | 16 | 22 | 133 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title | 4 | нет | 139 / 103 | 0.90 | 55 | 16 | 22 | 45 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title | 4 | да | 138 / 89 | 0.90 | 54 | 8 | 22 | 29 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title+300 | — | нет | 142 / 107 | 0.93 | 26 | 9 | 9 | 17 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title+300 | 4 | нет | 142 / 107 | 0.93 | 26 | 9 | 9 | 4 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title+300 | 4 | да | 141 / 92 | 0.93 | 25 | 6 | 9 | 3 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title+800 | — | нет | 144 / 108 | 0.96 | 2 | 0 | 0 | 1 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title+800 | 4 | нет | 144 / 108 | 0.96 | 2 | 0 | 0 | 0 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title+800 | 4 | да | 143 / 93 | 0.85 | 134 | 83 | 78 | 11590 |
| multilingual-e5-small  | title | — | нет | 139 / 101 | 0.89 | 70 | 23 | 35 | 242 |
| multilingual-e5-small  | title | 4 | нет | 139 / 101 | 0.89 | 70 | 23 | 35 | 91 |
| multilingual-e5-small  | title | 4 | да | 138 / 86 | 0.89 | 69 | 15 | 35 | 70 |
| multilingual-e5-small  | title+300 | — | нет | 143 / 106 | 0.93 | 18 | 9 | 10 | 16 |
| multilingual-e5-small  | title+300 | 4 | нет | 143 / 106 | 0.93 | 18 | 9 | 10 | 4 |
| multilingual-e5-small  | title+300 | 4 | да | 142 / 91 | 0.86 | 122 | 73 | 73 | 3595 |
| multilingual-e5-small  | title+800 | — | нет | 142 / 108 | 0.96 | 5 | 1 | 0 | 4 |
| multilingual-e5-small  | title+800 | 4 | нет | 142 / 108 | 0.96 | 5 | 1 | 0 | 0 |
| multilingual-e5-small  | title+800 | 4 | да | 141 / 93 | 0.88 | 112 | 67 | 72 | 1839 |
| multilingual-e5-base  | title | — | нет | 140 / 95 | 0.89 | 79 | 29 | 32 | 197 |
| multilingual-e5-base  | title | 4 | нет | 140 / 95 | 0.89 | 79 | 29 | 32 | 90 |
| multilingual-e5-base  | title | 4 | да | 139 / 82 | 0.89 | 78 | 21 | 32 | 68 |
| multilingual-e5-base  | title+300 | — | нет | 144 / 108 | 0.89 | 111 | 66 | 68 | 849 |
| multilingual-e5-base  | title+300 | 4 | нет | 144 / 108 | 0.89 | 111 | 66 | 68 | 456 |
| multilingual-e5-base  | title+300 | 4 | да | 143 / 93 | 0.89 | 110 | 55 | 67 | 403 |
| multilingual-e5-base  | title+800 | — | нет | 145 / 110 | 0.89 | 122 | 76 | 76 | 2516 |
| multilingual-e5-base  | title+800 | 4 | нет | 145 / 110 | 0.89 | 122 | 76 | 76 | 1331 |
| multilingual-e5-base  | title+800 | 4 | да | 144 / 95 | 0.89 | 121 | 62 | 75 | 1155 |
| paraphrase-multilingual-mpnet-base-v2  | title | — | нет | 36 / 5 | 0.75 | 87 | 34 | 41 | 168 |
| paraphrase-multilingual-mpnet-base-v2  | title | 4 | нет | 36 / 5 | 0.75 | 87 | 34 | 41 | 52 |
| paraphrase-multilingual-mpnet-base-v2  | title | 4 | да | 36 / 5 | 0.61 | 127 | 57 | 61 | 1755 |
| paraphrase-multilingual-mpnet-base-v2  | title+300 | — | нет | 44 / 14 | 0.73 | 127 | 47 | 48 | 404 |
| paraphrase-multilingual-mpnet-base-v2  | title+300 | 4 | нет | 44 / 14 | 0.73 | 127 | 47 | 48 | 216 |
| paraphrase-multilingual-mpnet-base-v2  | title+300 | 4 | да | 43 / 8 | 0.73 | 126 | 35 | 48 | 179 |
| paraphrase-multilingual-mpnet-base-v2  | title+800 | — | нет | 43 / 13 | 0.75 | 121 | 40 | 42 | 304 |
| paraphrase-multilingual-mpnet-base-v2  | title+800 | 4 | нет | 43 / 13 | 0.75 | 121 | 40 | 42 | 158 |
| paraphrase-multilingual-mpnet-base-v2  | title+800 | 4 | да | 42 / 8 | 0.75 | 120 | 33 | 42 | 129 |
| LaBSE тяжелее бюджета | title | — | нет | 10 / 1 | 0.63 | 93 | 30 | 43 | 409 |
| LaBSE тяжелее бюджета | title | 4 | нет | 10 / 1 | 0.63 | 93 | 30 | 43 | 188 |
| LaBSE тяжелее бюджета | title | 4 | да | 10 / 1 | 0.63 | 92 | 23 | 43 | 162 |
| LaBSE тяжелее бюджета | title+300 | — | нет | 14 / 10 | 0.72 | 78 | 38 | 41 | 192 |
| LaBSE тяжелее бюджета | title+300 | 4 | нет | 14 / 10 | 0.72 | 78 | 38 | 41 | 108 |
| LaBSE тяжелее бюджета | title+300 | 4 | да | 14 / 7 | 0.65 | 114 | 51 | 66 | 365 |
| LaBSE тяжелее бюджета | title+800 | — | нет | 26 / 19 | 0.65 | 131 | 76 | 76 | 2671 |
| LaBSE тяжелее бюджета | title+800 | 4 | нет | 26 / 19 | 0.65 | 131 | 76 | 76 | 1375 |
| LaBSE тяжелее бюджета | title+800 | 4 | да | 26 / 16 | 0.65 | 130 | 61 | 75 | 1223 |
| bge-m3 тяжелее бюджета, для сравнения | title+300 | — | нет | 20 / 12 | 0.68 | 133 | 63 | 61 | 454 |
| bge-m3 тяжелее бюджета, для сравнения | title+300 | 4 | нет | 20 / 12 | 0.68 | 133 | 63 | 61 | 294 |
| bge-m3 тяжелее бюджета, для сравнения | title+300 | 4 | да | 19 / 9 | 0.68 | 132 | 50 | 61 | 267 |

## Один сюжет (столбец «Связанные строки»)

Находка — пара «одно событие» (145) или «один сюжет» (83); ошибка — «разные» (111). Только окно 4 дня с предохранителем.

| Модель | Текст | Порог | Одно событие | Один сюжет | Всего найдено | Ошибок | Неразмеч. выше порога |
|---|---|---|---|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title | 0.55 | 126 | 63 | 189 из 228 | 61 из 111 | 2648 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+300 | 0.60 | 140 | 78 | 218 из 228 | 63 из 111 | 912 |
| paraphrase-multilingual-MiniLM-L12-v2 текущая | title+800 | 0.64 | 136 | 77 | 213 из 228 | 56 из 111 | 592 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title | 0.84 | 132 | 76 | 208 из 228 | 73 из 111 | 7274 |
|  ↳ при 0.88 | | | 89 | 45 | 134 | 35 | 247 |
|  ↳ при 0.90 | | | 54 | 22 | 76 | 8 | 29 |
|  ↳ при 0.92 | | | 24 | 7 | 31 | 3 | 1 |
|  ↳ при 0.94 | | | 9 | 2 | 11 | 2 | 0 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title+300 | 0.84 | 140 | 82 | 222 из 228 | 88 из 111 | 24182 |
|  ↳ при 0.88 | | | 107 | 67 | 174 | 62 | 836 |
|  ↳ при 0.90 | | | 71 | 46 | 117 | 49 | 124 |
|  ↳ при 0.92 | | | 40 | 20 | 60 | 20 | 12 |
|  ↳ при 0.94 | | | 11 | 4 | 15 | 2 | 0 |
| app:story_model e5-small ONNX int8 — ровно как в программе | title+800 | 0.81 | 144 | 82 | 226 из 228 | 93 из 111 | 96035 |
|  ↳ при 0.88 | | | 104 | 68 | 172 | 67 | 850 |
|  ↳ при 0.90 | | | 79 | 51 | 130 | 53 | 162 |
|  ↳ при 0.92 | | | 42 | 22 | 64 | 27 | 18 |
|  ↳ при 0.94 | | | 10 | 4 | 14 | 8 | 0 |
| multilingual-e5-small  | title | 0.83 | 134 | 78 | 212 из 228 | 79 из 111 | 11892 |
| multilingual-e5-small  | title+300 | 0.83 | 140 | 82 | 222 из 228 | 88 из 111 | 31769 |
| multilingual-e5-small  | title+800 | 0.84 | 141 | 82 | 223 из 228 | 88 из 111 | 36384 |
| multilingual-e5-base  | title | 0.81 | 141 | 80 | 221 из 228 | 87 из 111 | 29406 |
| multilingual-e5-base  | title+300 | 0.86 | 138 | 81 | 219 из 228 | 79 из 111 | 5649 |
| multilingual-e5-base  | title+800 | 0.87 | 136 | 80 | 216 из 228 | 76 из 111 | 7491 |
| paraphrase-multilingual-mpnet-base-v2  | title | 0.56 | 131 | 73 | 204 из 228 | 67 из 111 | 4291 |
| paraphrase-multilingual-mpnet-base-v2  | title+300 | 0.67 | 139 | 78 | 217 из 228 | 61 из 111 | 648 |
| paraphrase-multilingual-mpnet-base-v2  | title+800 | 0.68 | 137 | 75 | 212 из 228 | 56 из 111 | 621 |
| LaBSE тяжелее бюджета | title | 0.57 | 111 | 54 | 165 из 228 | 41 из 111 | 555 |
| LaBSE тяжелее бюджета | title+300 | 0.60 | 131 | 78 | 209 из 228 | 64 из 111 | 1060 |
| LaBSE тяжелее бюджета | title+800 | 0.61 | 135 | 79 | 214 из 228 | 69 из 111 | 3075 |
| bge-m3 тяжелее бюджета, для сравнения | title+300 | 0.61 | 141 | 81 | 222 из 228 | 64 из 111 | 799 |
