"""Набор для новых проектов: что ещё не настроено, настроить, найти чужие имена в общих файлах.

Зачем. Шаблон переезжает в новые проекты: у свежей копии надо заполнить имя, решающего и PROJECT.md, а в общих файлах
(скиллы, инструменты) не должно оставаться имён одного проекта и путей одного компьютера, иначе они уедут в следующий.
Что общее, а что проектное, — architecture/KIT.md.

Кто зовёт. Скилл /new-project, /dev и человек. Из корня репо:
  python <карта>/tools/kit.py status                 что ещё не заполнено: настройки, <заполнить: …>, @OWNER
  python <карта>/tools/kit.py init --title Склад --decider Анна --to Анне --status "решено Анной" --owner anna
                                    [--timezone Europe/Moscow] [--names склад,накладн]
                                                     записать настройки проекта и владельца
  python <карта>/tools/kit.py check                  имена из own_names и абсолютные пути в общих файлах
  python <карта>/tools/kit.py check --names a,b      ещё и эти слова
  python <карта>/tools/kit.py check --all            по всему репо, а не только по общим файлам
  python <карта>/tools/kit.py --selftest             самопроверка на временной копии

Что читает и пишет. status и check только читают. init пишет project/settings.yaml и .github/CODEOWNERS; если настройки
после записи не читаются как задумано, возвращает файл как был. Сам kit.py в check не входит: в нём лежат шаблоны поиска.
Сторонние файлы скиллов (.claude/skills/<скилл>/upstream/) в check не входят: они лежат как есть, их текст не правится.

Коды выхода: 0 — настроен (status), записано (init), находок нет (check); 1 — есть что заполнить или что убрать;
2 — ошибка вызова.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent
MAP = TOOLS.parent
DEFAULT_TITLE = "Новый проект"
BLANK = "<заполнить"
OWNER_MARK = "@OWNER"
# файлы, где проект заполняет места <заполнить: …>
FILLED = ("PROJECT.md", "README.md", "architecture/standards/code.md")
# общие файлы набора, от корня репо; остальное — проектное (KIT.md, «Что общее, а что проектное»)
KIT_PATHS = (
    ".claude/",
    "architecture/CLAUDE.md",
    "architecture/KIT.md",
    "architecture/PROCESS.md",
    "architecture/PROCESS-WHY.md",
    "architecture/STANDARD.md",
    "architecture/_shared/",
    "architecture/tools/",
    ".github/.instructions/",
    ".pre-commit-config.yaml",
    "scripts/test_limited.py",
)
NOT_SCANNED = {".claude/settings.local.json", "architecture/tools/kit.py"}
# сторонние файлы скиллов лежат как есть (.claude/skills/<скилл>/upstream/): их текст не правится, имён проекта в нём нет,
# а пути в примерах кода — чужие
VENDOR = re.compile(r"^\.claude/skills/[^/]+/upstream/")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".ruff_cache", ".pytest_cache", ".venv", "venv", ".playwright-cli"}
ABS_PATH = re.compile(r"[A-Za-z]:[\\/]+(?:Users|Dev|home)[\\/]|(?<![\w.~])/(?:home|Users)/[\w.-]+/|(?<![\w.])/[a-z]/Dev/", re.I)
OWNER_RE = re.compile(r"^[\w-]+(/[\w-]+)?$")


def settings_of(root: Path) -> dict:
    return yaml.safe_load((root / "project" / "settings.yaml").read_text(encoding="utf-8")) or {}


def status(root: Path) -> list[str]:
    """Что ещё не заполнено: строка на находку, пусто — проект настроен."""
    repo, todo = root.parent, []
    if settings_of(root).get("title") == DEFAULT_TITLE:
        todo.append(f"{root.name}/project/settings.yaml: имя и решающий ещё по умолчанию — kit.py init")
    for rel in FILLED:
        p = repo / rel
        if p.is_file():
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if BLANK in line:
                    todo.append(f"{rel}:{n}: {line.strip()[:110]}")
    owners = repo / ".github" / "CODEOWNERS"
    if owners.is_file() and OWNER_MARK in owners.read_text(encoding="utf-8"):
        todo.append(".github/CODEOWNERS: владелец ещё @OWNER — kit.py init --owner <логин>")
    return todo


def init(root: Path, a: argparse.Namespace) -> list[str]:
    """Записать настройки проекта. Возвращает ошибки; при ошибке файлы остаются как были."""
    if not OWNER_RE.match(a.owner.lstrip("@")):
        return [f"логин «{a.owner}»: нужны латиница, цифры, дефис"]
    path = root / "project" / "settings.yaml"
    before = path.read_bytes()
    text = before.decode("utf-8").replace("\r\n", "\n")  # в карте строки — только \n (.gitattributes)
    names = [x.strip() for x in (a.names or "").split(",") if x.strip()]
    q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731 — кавычки YAML: у имени могут быть двоеточие и пробел
    steps = [
        (r"^title: .*$", f"title: {q(a.title)}"),
        (r"^decider:\n  name: .*\n  to: .*$", f"decider:\n  name: {q(a.decider)}\n  to: {q(a.to)}"),
        (r"^(statuses:\n)  - .*$", rf"\g<1>  - {q(a.status)}"),
        (r"^own_names: .*$", f"own_names: {q(names)}"),
    ]
    if a.timezone:
        steps.append((r"^timezone: .*$", f"timezone: {q(a.timezone)}"))
    for pattern, new in steps:
        new_text, n = re.subn(pattern, lambda m, r=new: m.expand(r) if "\\g<" in r else r, text, count=1, flags=re.M)
        if n != 1:
            return [f"settings.yaml: не нашёл строку {pattern}"]
        text = new_text
    path.write_bytes(text.encode("utf-8"))
    got = settings_of(root)
    if (got.get("title"), (got.get("decider") or {}).get("name"), (got.get("statuses") or [""])[0]) != (a.title, a.decider, a.status):
        path.write_bytes(before)
        return ["settings.yaml: после записи значения не читаются — файл возвращён как был"]
    owners = root.parent / ".github" / "CODEOWNERS"
    if owners.is_file():
        data = owners.read_bytes().decode("utf-8").replace(OWNER_MARK, "@" + a.owner.lstrip("@"))
        owners.write_bytes(data.encode("utf-8"))
    return []


def in_kit(rel: str) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in KIT_PATHS)


def walk(repo: Path) -> Iterator[Path]:
    for folder, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            yield Path(folder) / name


def name_pattern(name: str) -> re.Pattern:
    """Числа и имена короче 4 знаков — словом целиком, остальное — подстрокой; регистр не важен."""
    word = name.isdigit() or len(name) < 4
    return re.compile(rf"(?<!\w){re.escape(name)}(?!\w)" if word else re.escape(name), re.I)


def check(root: Path, extra: list[str], everything: bool) -> list[str]:
    """Находки: имена проекта и абсолютные пути. Настройки проекта с самими именами в поиск не входят."""
    repo = root.parent
    names = sorted({str(x) for x in (settings_of(root).get("own_names") or [])} | set(extra))
    patterns = [(n, name_pattern(n)) for n in names]
    found = []
    for p in walk(repo):
        rel = p.relative_to(repo).as_posix()
        if rel in NOT_SCANNED or rel == f"{root.name}/project/settings.yaml" or VENDOR.match(rel):
            continue
        if not (everything or in_kit(rel)):
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(lines, 1):
            hits = [name for name, pat in patterns if pat.search(line)]
            if ABS_PATH.search(line):
                hits.append("абсолютный путь")
            for hit in hits:
                found.append(f"{rel}:{n}: «{hit}» — {line.strip()[:110]}")
    return found


def selftest() -> int:
    bad: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        root = repo / "architecture"
        (root / "project").mkdir(parents=True)
        (root / "tools").mkdir()
        (repo / ".github").mkdir()
        (repo / ".claude").mkdir()
        settings = (
            f"# Шаблон: title: x\ntitle: {DEFAULT_TITLE}\ndecider:\n  name: владелец\n  to: владельцу\ntimezone: UTC\n"
            "statuses:\n  - решено владельцем\n  - открыто\nown_names: []\n"
        )
        (root / "project" / "settings.yaml").write_text(settings, encoding="utf-8")
        (repo / "PROJECT.md").write_text("# П\n<заполнить: что>\n", encoding="utf-8")
        (repo / ".github" / "CODEOWNERS").write_text("* @OWNER\n", encoding="utf-8")
        if len(status(root)) != 3:
            bad.append(f"status на свежей копии: {status(root)}")

        args = argparse.Namespace(title="Склад: главный", decider="Анна", to="Анне", status="решено Анной", owner="anna", timezone="Europe/Moscow", names="склад, 8010")
        errors = init(root, args)
        got = settings_of(root)
        if errors or got["title"] != "Склад: главный" or got["decider"] != {"name": "Анна", "to": "Анне"} or got["timezone"] != "Europe/Moscow":
            bad.append(f"init: {errors} {got}")
        if got["statuses"] != ["решено Анной", "открыто"] or got["own_names"] != ["склад", "8010"]:
            bad.append(f"init, статусы и имена: {got}")
        if "@anna" not in (repo / ".github" / "CODEOWNERS").read_text(encoding="utf-8"):
            bad.append("init: владелец не записан")
        if "# Шаблон: title: x" not in (root / "project" / "settings.yaml").read_text(encoding="utf-8"):
            bad.append("init тронул комментарий")
        args.owner = "не логин!"
        if not init(root, args):
            bad.append("плохой логин не пойман")
        left = status(root)
        if len(left) != 1 or "PROJECT.md:2" not in left[0]:
            bad.append(f"status после init: {left}")
        (repo / "PROJECT.md").write_text("# П\nготово\n", encoding="utf-8")
        if status(root):
            bad.append("настроенный проект не признан настроенным")

        (repo / ".claude" / "a.md").write_text("чисто\n", encoding="utf-8")
        if check(root, [], False):
            bad.append(f"чистые файлы: {check(root, [], False)}")
        (repo / ".claude" / "a.md").write_text("про СКЛАДЫ\nпорт 8010\nпорт 180102\nE:\\Dev\\x\nC:/Users/x/y\nC:/Program Files/Git/orders\n/e/Dev/x\n~/.claude\n", encoding="utf-8")
        got_found = "\n".join(check(root, [], False))
        if got_found.count("«склад»") != 1 or got_found.count("«8010»") != 1 or got_found.count("абсолютный путь") != 3:
            bad.append(f"порча не поймана:\n{got_found}")
        vendor = repo / ".claude" / "skills" / "x" / "upstream"
        vendor.mkdir(parents=True)
        (vendor / "data.csv").write_text("C:/Users/x/y\nсклад\n", encoding="utf-8")
        if "upstream/data.csv" in "\n".join(check(root, [], False)):
            bad.append("сторонний файл скилла в upstream/ проверен, а не пропущен")
        (repo / "src").mkdir()
        (repo / "src" / "b.py").write_text("склад\n", encoding="utf-8")
        if "src/b.py" in got_found or "src/b.py" not in "\n".join(check(root, [], True)):
            bad.append("проектный файл: без --all не смотрится, с --all смотрится")
    for x in bad:
        print(f"ошибка самопроверки: {x}")
    if bad:
        return 1
    print("Самопроверка: всё сходится.")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="kit.py", description="Набор для новых проектов (шапка файла — подробно).")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--root", default=str(MAP), help="корень карты")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    p_init = sub.add_parser("init")
    for flag in ("--title", "--decider", "--to", "--status", "--owner"):
        p_init.add_argument(flag, required=True)
    p_init.add_argument("--timezone")
    p_init.add_argument("--names")
    p_check = sub.add_parser("check")
    p_check.add_argument("--names", default="")
    p_check.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    root = Path(a.root).resolve()
    if a.cmd == "status":
        todo = status(root)
        for line in todo:
            print(line)
        print(f"осталось заполнить: {len(todo)}" if todo else "проект настроен")
        return 1 if todo else 0
    if a.cmd == "init":
        errors = init(root, a)
        for line in errors:
            print(f"ошибка: {line}", file=sys.stderr)
        if errors:
            return 2
        print(f"записано: {root.name}/project/settings.yaml, .github/CODEOWNERS; дальше — python {root.name}/tools/kit.py status")
        return 0
    if a.cmd == "check":
        found = check(root, [x.strip() for x in a.names.split(",") if x.strip()], a.all)
        for line in found:
            print(line)
        print(f"находок: {len(found)}")
        return 1 if found else 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
