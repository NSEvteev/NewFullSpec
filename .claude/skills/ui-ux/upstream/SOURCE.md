# Откуда эта папка

Зачем: что здесь чужое, откуда взято и как обновить. Кто пишет: сессия, которая забирает новую версию оригинала. Кто читает: та же сессия и скилл `/ui-ux` ([../SKILL.md](../SKILL.md)). Файлы папки — как в оригинале, текст не правлен.

## Источник

| Что | Значение |
|---|---|
| Репо | https://github.com/nextlevelbuilder/ui-ux-pro-max-skill |
| Коммит | `b7d5353e0130feb8c5574ef1251f8a1db1873ccb` (2026-11-05, `feat: add Apple Native Experience UI style (#557)`) |
| Версия | 2.15.0 (по `skill.json` оригинала) |
| Дата забора | 2026-11-07 |
| Лицензия | MIT, Copyright (c) 2024 Next Level Builder — файл [LICENSE](LICENSE); файла NOTICE в оригинале нет |
| Папка оригинала | `.claude/skills/ui-ux-pro-max/` |

## Что взято

| Здесь | В оригинале | Что это |
|---|---|---|
| `SKILL.upstream.md` | `SKILL.md` | скилл оригинала; переименован: проверка при коммите (`skills-validate`) проверяет нашим форматом любой `SKILL.md` в `.claude/skills/` |
| `data/` (39 файлов, из них 22 в `data/stacks/`) | `data/` | таблицы базы: стили, палитры, шрифты, правила UX, графики, значки, правила стеков, правила выбора (`ui-reasoning.csv`); json-каталоги шрифтов и значков и сведения о происхождении данных — их читает `validate_data.py` |
| `references/quick-reference.md`, `references/pro-rules.md` | `references/` | полный свод правил по 10 разделам; правила для приложений и проверка перед сдачей |
| `scripts/search.py` | `scripts/` | вход: поиск по базе, сборка дизайн-системы |
| `scripts/core.py`, `scripts/design_system.py`, `scripts/reasoning_contract.py` | `scripts/` | поиск BM25 по таблицам, сборка дизайн-системы, правила выбора без исполнения кода из данных |
| `scripts/validate_data.py` | `scripts/` | проверка целостности таблиц: после обновления папки должна сказать `OK` |
| `LICENSE` | `LICENSE` в корне репо | лицензия |

Скрипты — только стандартная библиотека Python 3, без сети и без запуска других программ. Таблицы ищутся от пути самого скрипта (`core.py`: `DATA_DIR = Path(__file__).parent.parent / "data"`), поэтому раскладка `scripts/` рядом с `data/` работает без правок. Переменная `CLAUDE_PLUGIN_ROOT` встречается только в командах `SKILL.upstream.md`; наш `SKILL.md` даёт путь от корня репо: `python .claude/skills/ui-ux/upstream/scripts/search.py …`. **Скрипты не правились.**

Что пишут скрипты: только `search.py … --design-system --persist` — папку `<--output-dir>/design-system/<имя из -p>/` с `MASTER.md` и пустой `pages/` (с `--page <имя>` — ещё `pages/<имя>.md`). Без `--output-dir` — от текущей папки. Существующий `MASTER.md` без `--force` не перезаписывается. Остальное только читает и печатает.

Концы строк: файлы взяты из рабочей копии клона на Windows (`core.autocrlf=true`), в них CRLF; содержимое совпадает с теми же файлами оригинала в LF. `validate_data.py` сравнивает хэши каталогов, приводя концы строк к LF, поэтому проверка проходит.

## Что не взято и почему

| В оригинале | Почему нет |
|---|---|
| `.claude/skills/ui-ux-pro-max/scripts/tests/` | тесты оригинала и их данные: для работы скилла не нужны |
| `src/ui-ux-pro-max/` | та же папка `data/` и `scripts/` для сборки установщика (отличие — только концы строк) и `templates/` под другие ИИ-среды |
| `cli/` | установщик `npx ui-ux-pro-max-cli` для разных ИИ-сред |
| `scripts/` в корне репо | обслуживание базы автором: обновление каталогов шрифтов и значков из сети, оценка качества поиска, выпуск версий |
| `README*.md` (8 языков), `docs/`, `screenshots/`, `preview/`, `gallery/`, `projects/` | описание, переводы, картинки, демо-сайт и примеры проектов |
| `stack/` | отдельный набор инструкций оригинала, не входит в скилл |
| `.claude/skills/` кроме `ui-ux-pro-max/` (`banner-design`, `brand`, `design`, `design-system`, `slides`, `ui-styling`) | другие скиллы того же репо |
| `.claude-plugin/`, `skill.json`, `.github/`, `.releaserc.json`, `CLAUDE.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.gitattributes`, `.gitignore` | обвязка плагина, выпуска и репо оригинала |

## Как обновить

1. Клонировать оригинал во временную папку сессии; записать коммит: `git -C <клон> log -1 --format='%H %ad %s' --date=short`.
2. Прочитать новые `scripts/*.py` (сеть, запуск программ, запись файлов, пути к `data/`) и `SKILL.md` оригинала.
3. Заменить `data/`, `references/`, `scripts/*.py` (без `tests/`), `LICENSE`; `SKILL.md` оригинала — как `SKILL.upstream.md`.
4. Проверить из корня репо: `python .claude/skills/ui-ux/upstream/scripts/validate_data.py` — `OK`; поиск дизайн-системы и `--domain ux` — команды из [../SKILL.md](../SKILL.md), шаги 3–4.
5. Обновить этот файл: коммит, дата, что изменилось в составе; новые имена разделов оригинала — в ссылках `../SKILL.md`.
