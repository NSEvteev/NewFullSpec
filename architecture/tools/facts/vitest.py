"""Часть фактов «vitest»: сколько тестов у интерфейса — подсчётом в файлах, без запуска.

Зачем. Тесты интерфейса идут под Node, а скрипт фактов Node не запускает. Чтобы на странице было хотя бы число
тестов, часть считает вызовы it( и test( в файлах тестов.

Что читает. Файлы *.test.* и *.spec.* (.js, .jsx, .ts, .tsx, в том числе .cjs/.mjs) в папке package, кроме
node_modules и шаблонов test.exclude из vite.config.ts в корне root.

Раздел .facts.json:
  collected      {"vitest": сколько вызовов it( и test(}
  counted_only   словами: как посчитано (сколько файлов, сколько исключено настройкой)
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from facts._base import Ctx, diff

CODE_EXTS = (".ts", ".tsx")
VITEST_FILE = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$")


def _excludes(root: Path) -> list[str]:
    vc = root / "vite.config.ts"
    if not vc.is_file():
        return []
    src = vc.read_text(encoding="utf-8")
    i = src.find("test:")
    m = re.search(r"exclude\s*:\s*\[([^\]]*)\]", src[i:]) if i >= 0 else None
    return re.findall(r"[\"']([^\"']+)[\"']", m[1]) if m else []


def extract(ctx: Ctx) -> dict:
    cases, files, skipped = 0, 0, 0
    excl = _excludes(ctx.root)
    for d, dirs, names in os.walk(ctx.package):
        dirs[:] = sorted(x for x in dirs if x != "node_modules")
        for name in sorted(names):
            if not VITEST_FILE.search(name):
                continue
            rel_p = (Path(d) / name).relative_to(ctx.package).as_posix()
            if any(fnmatch.fnmatch(rel_p, g) for g in excl):
                skipped += 1
                continue
            files += 1
            text = (Path(d) / name).read_text(encoding="utf-8", errors="replace")
            cases += len(re.findall(r"^\s*(?:it|test)(?:\.each\([^)]*\))?\(", text, re.M))
    return {"collected": {"vitest": cases},
            "counted_only": f"посчитаны it( и test( в {files} файлах *.test / *.spec"
                            + (f", {skipped} исключено настройкой test.exclude в vite.config.ts" if skipped else "")}


def compare(old: dict, new: dict) -> list[str]:
    return diff(old, new, "vitest", ignore=frozenset({"counted_only"}))
