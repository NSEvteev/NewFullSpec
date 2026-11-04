"""Часть фактов «vite-env»: переменные окружения, которые читает интерфейс на Vite.

Зачем. У интерфейса настройки — переменные окружения: адреса сервисов для прокси Vite (vite.config.ts) и
import.meta.env в коде страниц. В settings.md у каждой — раздел со смыслом; откуда значение — отсюда.

Что читает. Файлы .ts и .tsx в папке package реестра (без тестов) и vite.config.ts в корне root: import.meta.env.X,
process.env.X, env?.["X"]; встроенные признаки сборки Vite (DEV, PROD, MODE, BASE_URL, SSR) — не настройки.
Раздел compose — откуда значение. NEEDS: compose.

Раздел .facts.json — список settings (у всех записей kind environ или runtime/compose-only) и поля рядом; что в
записи — tools/facts/_settings.py.
"""

from __future__ import annotations

import re

from facts._base import COMMENT_LINE, Ctx, code_files, diff
from facts._settings import settings_section

NEEDS = ("compose",)
CODE_EXTS = (".ts", ".tsx")
TS_ENV_READ = re.compile(r"(?:import\.meta\.env|process\.env)\.(\w+)|env\?\.\[\s*[\"'](\w+)[\"']\s*\]")
VITE_BUILTIN = {"DEV", "PROD", "MODE", "BASE_URL", "SSR"}


def extract(ctx: Ctx) -> dict:
    files = code_files(ctx.package, CODE_EXTS)
    config = ctx.root / "vite.config.ts"
    reads: dict[str, str] = {}
    for p in [*files, *([config] if config.is_file() and config not in files else [])]:
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if COMMENT_LINE.match(line):
                continue
            for m in TS_ENV_READ.finditer(line):
                name = m[1] or m[2]
                if name not in VITE_BUILTIN:
                    reads.setdefault(name, ctx.ref(p, i))
    return settings_section(ctx, [], reads, [], {})


def compare(old: dict, new: dict) -> list[str]:
    return diff(old, new, "vite-env", ignore=frozenset({"used_refs"}), ids={"settings": "name"})
