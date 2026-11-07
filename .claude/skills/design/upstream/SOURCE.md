# Откуда взято

Зачем этот файл: откуда пришли файлы папки `upstream/`, что взято, что нет и почему. Кто пишет: тот, кто обновляет `upstream/` из оригинала, — заменяет файлы целиком и переписывает этот файл. Тексты оригинала не правятся; наш скилл, который по ним работает, — `../SKILL.md`.

| Поле | Значение |
|---|---|
| Оригинал | Impeccable, https://github.com/pbakaus/impeccable |
| Коммит | `687bc381bc9091bf252c0a05303640561014a425` от 2026-11-06 |
| Забрано | 2026-11-07 |
| Версия скилла | 4.8.0 (шапка `SKILL.upstream.md`); версия программы-движка, под которую написаны тексты, — 0.1.18 |
| Лицензия | Apache 2.0 — `LICENSE`; сторонние части — `NOTICE.md`: `reference/ios.md` и `reference/android.md` переписаны из `ehmo/platform-design-skills` (MIT) |

## Что взято

Всё — без правок текста, побайтно.

| Здесь | В оригинале | Что это |
|---|---|---|
| `SKILL.upstream.md` | `plugin/skills/impeccable/SKILL.md` | скилл оригинала: принципы, режимы поверхностей, список команд |
| `reference/` (41 файл) | `plugin/skills/impeccable/reference/` | справочники команд: `shape`, `craft`, `craft-floor`, `new-work`, `layout`, `critique`, `audit`, `polish`, `typeset`, `colorize`, `clarify`, `harden`, `adapt`, `distill`, `bolder`, `quieter`, `delight`, `animate` и другие; режимы `mode-operate`, `mode-read`, `mode-persuade`, `operate`; нативные платформы `ios`, `android`, `*.native.md` — взяты целиком, они нужны другим репо |
| `reference/degraded/` (4 файла) | `plugin/skills/impeccable/reference/degraded/` | те же роли, что в `agents/`, для работы без субагентов — в одной сессии |
| `agents/` (4 файла) | `plugin/agents/` | субагенты оригинала: оценщик готовой сборки, составитель DESIGN.md, изготовитель картинок, применитель правок режима `live`. Лежат как справочники: Claude Code грузит агентов только из `.claude/agents/`, отсюда — нет |
| `LICENSE`, `NOTICE.md` | корень репо | лицензия и сторонние части |

Переименовано: `SKILL.md` → `SKILL.upstream.md` — проверка при коммите (`skills-validate`) проверяет нашим форматом любой вложенный `SKILL.md`. Ссылки `reference/…` внутри `SKILL.upstream.md` по-прежнему ведут куда надо: раскладка папок та же.

## Что не взято и почему

| В оригинале | Почему |
|---|---|
| `plugin/skills/impeccable/scripts/impeccable`, `impeccable.cmd` | запускатель движка: скачивает с GitHub собранную программу под свою систему и запускает её. Наш скилл работает по текстам справочников, чужую собранную программу не кладём и не запускаем |
| `scripts/engine-checksums.txt`, `scripts/VERSION` | суммы и версия программы движка — нужны только запускателю |
| `scripts/command-metadata.json` | описания команд для сборки плагина под разные среды; скилл их не читает |
| `scripts/live-browser.js`, `live-browser-dom.js`, `live-browser-ignores.js`, `live-browser-session.js`, `modern-screenshot.umd.js` | страничные скрипты режима `live` (выбор вариантов прямо в браузере); работают только вместе с движком |
| `scripts/data/font-index.json`, `font-index-failures.json` | указатель шрифтов Google Fonts для команды движка `font-match` |
| `plugin/hooks/hooks.json` | автопроверка: после правки файлов зовёт детектор движка |
| `plugin/.claude-plugin/`, `plugin/.grok-plugin/` | описания плагина для установки |
| `skill/` | исходник скилла до сборки, с подстановками под разные среды; взята собранная для Claude папка `plugin/skills/impeccable/` |
| `cli/`, `crates/`, `Cargo.*`, `rust-toolchain.toml`, `ENGINE_VERSION` | исходники движка |
| `.agent/`, `.agents/`, `.codex/`, `.cursor/`, `.gemini/`, `.kiro/` и другие папки сред, `cursor-plugin/`, `vscode/`, `extension/`, `browser-bundle/` | копии скилла под другие среды и расширения редакторов и браузера |
| `demos/`, `docs/`, `ui/` | сайт и демонстрации |
| `tests/` | тесты оригинала |
| `README.md`, `README.npm.md`, `AGENTS.md`, `CLAUDE.md`, `DESIGN.md`, `PRODUCT.md` | описание и правила самого репо оригинала, не скилла |
| `.github/`, `package.json`, `bun.lock`, `biome.json`, `.bun-version`, `skills-lock.json` | сборка и выпуск |

## Что в текстах ссылается на невзятое

Справочники зовут `"${CLAUDE_SKILL_DIR}/scripts/impeccable" <команда>` и `<skill-base-dir>/scripts/impeccable` — `context`, `detect`, `critique-storage`, `concept-seed`, `serve-question`, `surface-brief`, `comp-spec`, `build-phase`, `comp-diff`, `font-match`, `generate-image`, `embed-prompt`, `live*`, `hooks`, `doctor`, `signals`. Этих файлов здесь нет нарочно. Чем каждая команда заменяется у нас — таблица в начале `../SKILL.md`. Целиком на движке держатся `live.md`, `live-setup.md`, `generate.md`, `hooks.md`, `doctor.md`, `region-map.md`, `component-review.md`, путь comp-led в `new-work.md` и `visualize.md`: лежат для полноты, наш скилл их не зовёт.
