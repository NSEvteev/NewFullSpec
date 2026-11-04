"""Часть фактов «python-imports»: какие общие пакеты проекта импортирует код сервиса на Python.

Зачем. Раздел «Кто подключает» в README общего пакета пишется словами (как попадает пакет и что делать после
правки), а кто его на деле импортирует — отсюда: проверка сверяет одно с другим, доска рисует линию подключения.

Что читает. Код в папке package (без тестов и миграций): import и from … import. Общий пакет проекта — запись
реестра вида package; его имя для импорта — путь его папки package от корня репо через точки, начиная после
последней папки с дефисом (папка shared/auth — shared.auth, папка lib/calendar-core/calendar_core —
calendar_core). Импорт самого себя не считается.

Раздел .facts.json:
  packages[]   key — ключ пакета в реестре; refs — до пяти строк импорта
"""

from __future__ import annotations

import ast

from facts._base import CODE_EXTS_PY, Ctx, code_files, diff, parse

CODE_EXTS = CODE_EXTS_PY


def _import_names(ctx: Ctx) -> dict[str, str]:
    """Имя для импорта → ключ пакета. Имя — путь папки пакета от корня репо через точки, начиная после последней
    папки, которая не годится в имя модуля Python (с дефисом): shared/auth → shared.auth,
    lib/calendar-core/calendar_core → calendar_core."""
    names = {}
    for key, info in ctx.registry.items():
        if info.get("kind") != "package" or key == ctx.service:
            continue
        parts = ctx.rel((ctx.repo / info["package"]).resolve()).split("/")
        tail: list[str] = []
        for part in reversed(parts):
            if not part.isidentifier():
                break
            tail.insert(0, part)
        if tail:
            names[".".join(tail)] = key
    return names


def extract(ctx: Ctx) -> dict:
    names = _import_names(ctx)
    found: dict[str, list[str]] = {}
    for p in code_files(ctx.package, CODE_EXTS_PY):
        tree = parse(p)
        if not tree:
            continue
        for n in ast.walk(tree):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                mods = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
            for m in mods:
                for prefix, key in names.items():
                    if m == prefix or m.startswith(prefix + "."):
                        found.setdefault(key, []).append(ctx.ref(p, n.lineno))
    return {"packages": [{"key": k, "refs": sorted(set(v))[:5]} for k, v in sorted(found.items())]}


def compare(old: dict, new: dict) -> list[str]:
    return diff(old, new, "python-imports", ignore=frozenset({"refs"}), ids={"packages": "key"})
