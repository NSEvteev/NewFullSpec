---
description: GitHub конфигурация — workflows, шаблон PR, метки, CODEOWNERS, скрипты проверок для хуков pre-commit.
---

# /.github/ — GitHub конфигурация

| Что | Описание |
|-----|----------|
| [workflows/](./workflows/README.md) | GitHub Actions: `ci.yml` (pre-commit, тесты, линт, проверка зависимостей) |
| `.instructions/.scripts/`, `.instructions/commits/.scripts/` | Скрипты проверок, которые вызывают хуки pre-commit: шаблон PR, CODEOWNERS, workflows, безопасность, имя ветки, обязательные файлы, сообщение коммита; `sync-labels.py` — метки из `labels.yml` (`make init`) |
| [CODEOWNERS](./CODEOWNERS) | Владельцы кода |
| [dependabot.yml](./dependabot.yml) | Обновления зависимостей |
| [labels.yml](./labels.yml) | Метки (их ставит и Dependabot) |
| [PULL_REQUEST_TEMPLATE.md](./PULL_REQUEST_TEMPLATE.md) | Шаблон PR (тело PR процесса `/dev` пишется из файла — `/dev-deliver`) |
| [SECURITY.md](./SECURITY.md) | Политика безопасности |

Как вести изменение (ветка, коммиты, PR, merge) — `architecture/PROCESS.md` и скиллы `/dev`.
