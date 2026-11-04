"""Мёртвый код: то, что проверки карты не видят, потому что строки по ссылкам на месте.

Зачем. Выключенный, но оставленный код проходит и тесты, и сверку ссылок, а описание при этом незаметно врёт. Скрипт
ищет код, до которого не доходит выполнение, и следы удалённых имён.

Кто зовёт. Шаг блока (/dev-block) — по файлам блока; закрытие (/dev-close) — по папкам задетых сервисов. Из корня репо:
  python <карта>/tools/devDead.py <папка> [<папка> ...]      все .py в папках: код после безусловного выхода
  python <карта>/tools/devDead.py --since <коммит>           только .py, которые менялись после коммита
  python <карта>/tools/devDead.py --gone <имя> [<имя> ...] --in <папка> [<папка> ...]
                                                             где ещё упоминаются удалённые имена
  python <карта>/tools/devDead.py --selftest                 самопроверка на образце и порченых копиях

Что считает мёртвым. Оператор после return, raise, continue или break в том же блоке — только Python. Другие языки и
слова, за которыми прячется оставленный код, — раздел «Мёртвый код» файла PROJECT.md.

Что читает. Файлы .py; git — для --since и --gone. Ничего не пишет.

Коды выхода: 0 — чисто; 1 — нашлось; 2 — ошибка вызова.

Чего не делает. Не решает, что удалять: это вопрос тому, кто решает. Не ищет функции, которые никто не зовёт: вывод
find.py и поиск по коду. Файл с ошибкой синтаксиса называет находкой и идёт дальше.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import tempfile
from pathlib import Path

SKIP_DIRS = {"__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".git"}
EXITS = (ast.Return, ast.Raise, ast.Continue, ast.Break)
BLOCK_FIELDS = ("body", "orelse", "finalbody")


def dead_in_text(text: str, name: str) -> list[str]:
    """Находки одного файла: «<файл>:<строка> — после return»."""
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [f"{name}:{e.lineno} — не разобрать: {e.msg}"]
    hits = []
    for node in ast.walk(tree):
        for field in BLOCK_FIELDS:
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for stmt, following in zip(block, block[1:]):
                if isinstance(stmt, EXITS):
                    hits.append(f"{name}:{following.lineno} — после {type(stmt).__name__.lower()}")
                    break
    return sorted(hits)


def py_files(roots: list[str]) -> list[Path]:
    out = []
    for root in roots:
        p = Path(root)
        found = [p] if p.is_file() else sorted(p.rglob("*.py"))
        out += [f for f in found if not set(f.parts) & SKIP_DIRS]
    return out


def changed_since(base: str, cwd: Path | None = None) -> list[Path]:
    """.py, которые менялись после коммита и ещё есть на диске."""
    res = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AM", f"{base}...HEAD", "--", "*.py"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd,
    )
    if res.returncode != 0:
        raise ValueError(f"git diff от {base}: {res.stderr.strip()[:120]}")
    root = cwd or Path()
    return [root / x for x in res.stdout.split("\n") if x.strip() and (root / x).is_file()]


def scan(files: list[Path]) -> list[str]:
    hits = []
    for f in files:
        hits += dead_in_text(f.read_text(encoding="utf-8", errors="replace"), f.as_posix())
    return hits


def gone_names(names: list[str], roots: list[str], cwd: Path | None = None) -> list[str]:
    """Где ещё упоминаются удалённые имена: только файлы под git, дословно."""
    hits = []
    for name in names:
        res = subprocess.run(
            ["git", "grep", "-nF", "--", name, *roots],
            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd,
        )
        if res.returncode not in (0, 1):
            raise ValueError(f"git grep «{name}»: {res.stderr.strip()[:120]}")
        hits += [f"{name}: {x[:140]}" for x in res.stdout.splitlines()]
    return hits


CLEAN = """def f(x):
    if x:
        return 1
    return 2


for i in range(3):
    if i:
        continue
    print(i)
"""
SPOILS = {
    "после return": "def f():\n    return 1\n    print(2)\n",
    "после raise": "def f():\n    raise ValueError\n    print(2)\n",
    "после continue": "for i in []:\n    continue\n    print(i)\n",
    "после break": "while True:\n    break\n    print(1)\n",
    "не разобрать": "def f(:\n",
}


def selftest() -> int:
    bad = []
    if dead_in_text(CLEAN, "чистый.py"):
        bad.append(f"чистый образец: {dead_in_text(CLEAN, 'чистый.py')}")
    for want, text in SPOILS.items():
        if not any(want in x for x in dead_in_text(text, "порча.py")):
            bad.append(f"порча «{want}» не поймана")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)

        def git(*args: str) -> None:
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, capture_output=True, check=True)

        git("init", "-q")
        (repo / "a.py").write_text(CLEAN, encoding="utf-8")
        git("add", "a.py")
        git("commit", "-qm", "первый")
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
        (repo / "b.py").write_text(SPOILS["после return"], encoding="utf-8")
        git("add", "b.py")
        git("commit", "-qm", "второй")
        found = [p.name for p in changed_since(base, repo)]
        if found != ["b.py"]:
            bad.append(f"--since: нашёл {found}, нужно b.py")
        if not gone_names(["print(2)"], ["."], repo):
            bad.append("--gone: не нашёл имя, которое есть")
        if gone_names(["нет_такого_имени"], ["."], repo):
            bad.append("--gone: нашёл имя, которого нет")
    for x in bad:
        print(f"ошибка самопроверки: {x}")
    if bad:
        return 1
    print(f"Самопроверка: всё сходится (порч {len(SPOILS)}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="devDead.py", description="Мёртвый код (шапка файла — подробно).")
    ap.add_argument("roots", nargs="*")
    ap.add_argument("--since")
    ap.add_argument("--gone", nargs="+")
    ap.add_argument("--in", dest="within", nargs="+")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    try:
        if a.gone:
            if not a.within:
                print("ошибка: у --gone нужен --in <папка>", file=sys.stderr)
                return 2
            hits = gone_names(a.gone, a.within)
            print("\n".join(hits) if hits else f"имён {len(a.gone)}: упоминаний нет")
            return 1 if hits else 0
        if not a.since and not a.roots:
            print("ошибка: папки, --since или --gone", file=sys.stderr)
            return 2
        files = changed_since(a.since) if a.since else py_files(a.roots)
    except ValueError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2
    hits = scan(files)
    print("\n".join(hits) if hits else "недостижимого кода нет")
    print(f"файлов {len(files)}, недостижимых мест {len(hits)}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
