# Набор для новых проектов

Эта папка и обвязка вокруг неё — переносимый набор: карта архитектуры, процесс изменений `/dev`, бэклог, проверки. Новый проект начинается с копии шаблона, а дальше живёт сам. Этот файл — для того, кто начинает проект или переносит улучшения набора из проекта в шаблон.

## Как начать новый проект

1. Создать репо из шаблона: **Use this template** на GitHub или `gh repo create <имя> --template <владелец>/<шаблон> --private --clone`; копия через `git clone` несёт историю шаблона — удалить `.git` и выполнить `git init -b main`. В репо должен быть `origin`: ворота `/dev` сверяют `main` с `origin/main`.
2. `make setup` — зависимости инструментов и хуки pre-commit; нет `make` — команды его цели `setup` из `Makefile`.
3. Машина новая — один раз поставить монитор контекста по `.claude/ctxmon/INSTALL.md`: без него нет передачи перед сжатием (`/handoff`) и пробуждения сессии после сжатия.
4. `/new-project` в Claude Code — он спросит и заполнит всё из раздела «Проектное» ниже.
5. Первая задача — `/backlog`, её изменение — `/dev <задача словами>`.

Сервисов в новом проекте нет, карта пуста, и это нормальное состояние: `build.py`, `live.py` и `where.py` на ней работают. Первый сервис появляется первым изменением: его запись реестра лежит в `TOBE/board.yaml` (поле `registry`) и на закрытии переходит в `project/services.yaml`.

## Что общее, а что проектное

**Общее** — в новом проекте не правится, улучшения возвращаются в шаблон; `kit.py check` следит, чтобы в этих файлах не было имён проекта:

| Что | Где |
|---|---|
| скиллы, правила, скрипты и проверки Claude Code | `.claude/` (кроме `settings.local.json`) |
| процесс и как писать карту | `architecture/PROCESS.md`, `PROCESS-WHY.md`, `STANDARD.md`, `CLAUDE.md`, этот файл |
| инструменты, проверочные карты, оформление страниц | `architecture/tools/`, `architecture/_shared/` |
| проверки репо | `.github/.instructions/`, `.pre-commit-config.yaml` (кроме хуков линтера), `scripts/test_limited.py` |

**Проектное** — у каждого проекта своё:

| Что | Где | Кто заполняет |
|---|---|---|
| сервисы, команды, окружение, как используется, соседние репо, CI | `PROJECT.md` | `/new-project`, дальше — по мере изменений |
| имя, кто решает, часовой пояс, единицы, провайдеры, compose, интерфейс, свои имена | `architecture/project/settings.yaml` | `/new-project` (`kit.py init`) и руками по шапкам ключей |
| реестр сервисов, раскладка доски | `architecture/project/services.yaml`, `board.yaml` | закрытие изменения |
| стандарт кода | `architecture/standards/code.md` | `/new-project`, разделы под свой стек |
| описание репо, запуск, CI | `README.md`, `CLAUDE.md`, `Makefile`, `.github/workflows/`, `.github/CODEOWNERS`, `.github/dependabot.yml`, `.gitignore`, `.env.example`, `.dockerignore`, хуки линтера в `.pre-commit-config.yaml` | `/new-project` |
| карта, журнал, бэклог, путеводитель | `architecture/ASIS/`, `TOBE/`, `JOURNAL.md`, `_backlog/`, `CHANGELOG.md` | сам процесс |
| код | `src/`, `shared/`, `platform/`, `config/` | изменения |

`LICENSE` — лицензия самого шаблона (MIT): её текст остаётся вместе с набором; лицензию своего кода проект выбирает сам.

## Другая технология

Сам процесс от технологии не зависит. Скрипт фактов (`tools/facts/`) умеет: compose, FastAPI, pydantic-settings, Vite, Postgres, Alembic, импорты и экспорты Python, pytest, vitest. Для другого стека есть два пути:

- `facts: []` у сервиса в реестре — всё о нём описано в md, проверки, которым нужны факты, для него молчат. С этого начинать. Тесты лежат рядом с кодом (как в Go) — в `tests` реестра указать папку кода;
- своя часть в `tools/facts/` по образцу соседних — когда описание руками начинает расходиться с кодом.

Ещё зависят от стека: `make test` и `make lint`, задания `.github/workflows/ci.yml`, хуки ruff в `.pre-commit-config.yaml`, `scripts/test_limited.py` (pytest), `tools/devDead.py` (Python); `/new-project` называет их в своём шаге.

## Как переносить улучшения

Набор в проекте и шаблон связаны только копированием, само ничего не обновляется.

- **Из проекта в шаблон:** правка общих файлов проходит сессию разбора (`PROCESS.md`, раздел 12). Перед переносом — `python architecture/tools/kit.py check`: имя проекта из `own_names` в общем файле значит, что туда попало проектное. Перенести в шаблон только общие файлы.
- **Из шаблона в проект:** сравнить и забрать общие файлы (`git diff --no-index <шаблон>/.claude .claude` и так же по таблице выше); проектные файлы не трогать. После — `python architecture/tools/build.py`: страницы собираются новым генератором.

## Проверка

```bash
python architecture/tools/kit.py status                 # настройки, незаполненные места, владелец; код 0 — они заполнены
python architecture/tools/kit.py check                  # имена проекта и абсолютные пути в общих файлах
python architecture/tools/kit.py check --all --names <слова>   # то же по всему репо и со своими словами
python -m pytest architecture/tools/tests -q            # инструменты на проверочной карте
```
