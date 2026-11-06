---
description: Инструменты Claude Code в проекте — скиллы настройки и процесса изменений, правила, настройки, скрипты проверок для хуков.
---

# .claude/ — Claude Code

| Что | Описание |
|-----|----------|
| [skills/](./skills/README.md) | Скиллы: `/new-project`, `/backlog`, `/dev` и пять шагов процесса изменений, `/docker-up`, `/handoff` |
| [ctxmon/](./ctxmon/INSTALL.md) | Монитор контекста — копия для установки на машину: строка контекста, передача перед сжатием, пробуждение сессии после него; ставится один раз на машину в `~/.claude/ctxmon/` |
| [rules/](./rules/) | Правила, которые подгружаются сами: `core` (изменения — через `/dev`), `code` (стандарт кода, проверка результата), `search`, `working` (общие уроки работы) |
| `scripts/agent_progress.py` | Монитор хода агента блока |
| `.instructions/skills/.scripts/validate-skill.py`, `.instructions/rules/.scripts/validate-rule.py` | Проверки формата скиллов и правил — их вызывают хуки pre-commit |
| `settings.json` | Общие настройки и хуки Claude Code |
| `settings.local.json` | Личные разрешения инструментов; вне git |

Процесс изменений — [architecture/PROCESS.md](/architecture/PROCESS.md); стандарт кода — [architecture/standards/code.md](/architecture/standards/code.md); что в наборе общее, а что проектное — [architecture/KIT.md](/architecture/KIT.md).
