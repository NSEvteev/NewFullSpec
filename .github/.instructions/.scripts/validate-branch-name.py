#!/usr/bin/env python3
"""
validate-branch-name.py — Валидация имени ветки.

Ветка изменения — change/<имя> (её заводит map.py start, architecture/PROCESS.md, раздел 9). Основные ветки, служебные
chore/ и backport/ и ветки Dependabot не проверяются; любая другая ветка — ошибка: работа идёт процессом /dev.

Использование:
    python validate-branch-name.py [branch-name] [--json]

Примеры:
    python validate-branch-name.py change/payment-retry
    python validate-branch-name.py
    python validate-branch-name.py change/payment-retry --json

Возвращает:
    0 — валидация пройдена
    1 — есть ошибки
    2 — не удалось определить имя ветки
"""

import argparse
import json
import os
import re
import subprocess
import sys


# =============================================================================
# Константы
# =============================================================================

CHANGE_PATTERN = re.compile(r"^change/[a-z0-9][a-z0-9._-]*$")

SKIP_BRANCHES = ("main", "master")
SKIP_PREFIXES = ("backport/", "chore/", "dependabot/")

ERROR_CODES = {
    "BR001": "Ветка вне процесса: ожидается change/<имя>",
    "BR002": "Имя ветки изменения: строчная латиница, цифры, точка, дефис, подчёркивание",
}


# =============================================================================
# Общие функции
# =============================================================================


def get_current_branch() -> str | None:
    """Получить имя текущей ветки через git или CI-переменные."""
    # CI: GitHub Actions (detached HEAD — git branch --show-current пуст)
    branch = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME")
    if branch:
        return branch

    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, encoding="utf-8", timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


# =============================================================================
# Валидация
# =============================================================================


def validate_format(branch_name: str) -> list[tuple[str, str]]:
    """Валидация имени ветки.

    Returns:
        list: [(код ошибки, сообщение)]
    """
    if not branch_name.startswith("change/"):
        return [("BR001", ERROR_CODES["BR001"] + f": '{branch_name}'")]
    if not CHANGE_PATTERN.match(branch_name):
        return [("BR002", ERROR_CODES["BR002"] + f": '{branch_name}'")]
    return []


# =============================================================================
# Main
# =============================================================================


def main():
    """Точка входа."""
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Валидация имени ветки")
    parser.add_argument("branch", nargs="?", help="Имя ветки (по умолчанию: текущая ветка)")
    parser.add_argument("--json", action="store_true", help="Вывод в формате JSON")
    args = parser.parse_args()

    # Определить имя ветки
    branch_name = args.branch or get_current_branch()
    if not branch_name:
        print("❌ Не удалось определить имя ветки", file=sys.stderr)
        sys.exit(2)

    # Пропуск системных веток
    if branch_name in SKIP_BRANCHES or any(branch_name.startswith(p) for p in SKIP_PREFIXES):
        if not args.json:
            print(f"⏭️  Системная ветка '{branch_name}' — пропуск валидации")
        sys.exit(0)

    errors = validate_format(branch_name)

    # Вывод результатов
    if args.json:
        result = {
            "branch": branch_name,
            "errors": [{"code": code, "message": msg} for code, msg in errors],
            "valid": len(errors) == 0
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print(f"❌ Ветка '{branch_name}' — {len(errors)} ошибок:")
        for code, msg in errors:
            print(f"   {code}: {msg}")
    else:
        print(f"✅ Ветка '{branch_name}' — валидация пройдена")

    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
