#!/usr/bin/env python3
"""
check-github-required.py — Проверка наличия обязательных файлов GitHub.

Использование:
    python check-github-required.py

Проверяет:
    - .github/CODEOWNERS
    - .github/labels.yml
    - .github/PULL_REQUEST_TEMPLATE.md

Примеры:
    python check-github-required.py
    # ✅ Все обязательные файлы GitHub на месте

Возвращает:
    0 — все файлы на месте
    1 — отсутствуют обязательные файлы
"""

import sys
from pathlib import Path


# Коды ошибок
ERROR_CODES = {
    "GH001": "Отсутствует .github/CODEOWNERS",
    "GH002": "Отсутствует .github/labels.yml",
    "GH003": "Отсутствует .github/PULL_REQUEST_TEMPLATE.md",
}


def find_repo_root(start_path: Path) -> Path:
    """Найти корень репозитория (папка с .git)."""
    current = start_path.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return start_path.resolve()


def check_required_files(repo_root: Path) -> list[str]:
    """Проверить наличие обязательных файлов."""
    errors = []
    github_dir = repo_root / ".github"

    # GH001: CODEOWNERS
    if not (github_dir / "CODEOWNERS").exists():
        errors.append("[GH001] Отсутствует .github/CODEOWNERS")

    # GH002: labels.yml
    if not (github_dir / "labels.yml").exists():
        errors.append("[GH002] Отсутствует .github/labels.yml")

    # GH003: PULL_REQUEST_TEMPLATE.md
    if not (github_dir / "PULL_REQUEST_TEMPLATE.md").exists():
        errors.append("[GH003] Отсутствует .github/PULL_REQUEST_TEMPLATE.md")

    return errors


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    repo_root = find_repo_root(Path.cwd())

    print("🔍 Проверка обязательных файлов GitHub...")
    errors = check_required_files(repo_root)

    if errors:
        print("\n❌ Отсутствуют обязательные файлы:")
        for err in errors:
            print(f"  {err}")
        sys.exit(1)
    else:
        print("✅ Все обязательные файлы GitHub на месте")
        sys.exit(0)


if __name__ == "__main__":
    main()
