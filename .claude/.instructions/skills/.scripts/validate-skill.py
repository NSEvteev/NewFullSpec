#!/usr/bin/env python3
"""Проверка второй версии скиллов: .claude/skills/*/SKILL.md (правила формата — .claude/skills/README.md).

Зачем. Скилл — только шаги: «почему», истории и правила лежат в документах процесса. Текстом это не удержать: при
каждом уроке скилл снова растёт. Поэтому длину и запрет историй держит этот скрипт.

Кто зовёт. Проверка при коммите (.pre-commit-config.yaml, запись skills-validate) и сессия, которая пишет скилл.
Из корня репо:
  python .claude/.instructions/skills/.scripts/validate-skill.py <имя или путь> [...]
  python .claude/.instructions/skills/.scripts/validate-skill.py --all        все SKILL.md
  python .claude/.instructions/skills/.scripts/validate-skill.py --selftest   самопроверка на образце и порченых копиях

Что проверяет:
  S001–S003  шапка: name есть, в kebab-case, совпадает с именем папки
  S004–S005  description есть, от 100 до 600 знаков: он в контексте каждой сессии
  S006       allowed-tools есть
  S010       заголовок H1 один
  S011       во всём файле не больше 15 000 знаков
  S012–S013  шаги — верхний список «N. **…**», не меньше трёх, номера подряд с единицы
  S014       первый шаг начинается со слова «Прочитать»
  S015       последняя непустая строка начинается с «**По ходу всех шагов:**»
  S020       нет слова «однажды»: истории — в PROCESS-WHY.md
  S021       нет дат: дата — признак истории
  S022       нет кавычек длиннее 60 знаков: так выглядит цитата
  S023       нет разделов-обвязки: Чек-лист, Нельзя, Примеры, Выходы, Шаблон
  S030       пути architecture/… и .claude/… в тексте существуют

Что читает. Файлы скиллов; пути — от корня репо (папка с .git). Ничего не пишет.

Коды выхода: 0 — ошибок нет; 1 — есть; 2 — ошибка вызова.

Чего не делает. Не проверяет смысл: понятность проверяет новичок.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"
FILE_NAME = "SKILL.md"
MAX_CHARS = 15_000
DESC_MIN, DESC_MAX = 100, 600
QUOTE_MAX = 60
STEP_RE = re.compile(r"^(\d+)\. \*\*(.+?)\*\*", re.M)
DATE_RE = re.compile(r"\b\d{2}\.\d{2}\.20\d{2}\b|\b20\d{2}-\d{2}-\d{2}\b")
QUOTE_RE = re.compile(r"«[^«»\n]{%d,}»" % (QUOTE_MAX + 1))
BANNED_HEADS = ("Чек-лист", "Нельзя", "Примеры", "Выходы", "Шаблон")
PATH_RE = re.compile(
    r"(?<![\w./-])((?:architecture|\.claude)/[\w./-]+\.(?:py|md|yaml))\b"
)
KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
LAST_LINE = "**По ходу всех шагов:**"


def split_front(text: str) -> tuple[dict, str]:
    """Шапка YAML и тело; шапки нет — пустой словарь и весь текст."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    try:
        return yaml.safe_load(text[3:end]) or {}, text[end + 4 :]
    except yaml.YAMLError:
        return {}, text[end + 4 :]


def check(text: str, folder: str, repo: Path) -> list[tuple[str, str]]:
    """Ошибки одного файла: (код, что не так и где)."""
    errs: list[tuple[str, str]] = []
    front, body = split_front(text)
    name = str(front.get("name") or "")
    if not name:
        errs.append(("S001", "в шапке нет name"))
    elif not KEBAB_RE.match(name):
        errs.append(("S002", f"name «{name}» — нужен kebab-case"))
    elif name != folder:
        errs.append(("S003", f"name «{name}» — нужно как папка «{folder}»"))
    desc = str(front.get("description") or "")
    if not desc:
        errs.append(("S004", "в шапке нет description"))
    elif not DESC_MIN <= len(desc) <= DESC_MAX:
        errs.append(
            (
                "S005",
                f"description {len(desc)} знаков — нужно от {DESC_MIN} до {DESC_MAX}",
            )
        )
    if not front.get("allowed-tools"):
        errs.append(("S006", "в шапке нет allowed-tools"))
    h1 = len(re.findall(r"^# [^#]", body, re.M))
    if h1 != 1:
        errs.append(("S010", f"заголовков H1: {h1} — нужен один"))
    if len(text) > MAX_CHARS:
        errs.append(("S011", f"в файле {len(text)} знаков — потолок {MAX_CHARS}"))
    steps = STEP_RE.findall(body)
    nums = [int(n) for n, _ in steps]
    if len(nums) < 3:
        errs.append(
            (
                "S012",
                f"шагов «N. **…**» в верхнем списке: {len(nums)} — нужно не меньше трёх",
            )
        )
    elif nums != list(range(1, len(nums) + 1)):
        errs.append(("S013", f"номера шагов {nums} — нужны подряд с единицы"))
    if steps and not steps[0][1].startswith("Прочитать"):
        errs.append(
            ("S014", f"первый шаг «{steps[0][1]}» — нужно начать со слова «Прочитать»")
        )
    lines = [x for x in body.splitlines() if x.strip()]
    if not lines or not lines[-1].startswith(LAST_LINE):
        errs.append(("S015", f"последняя строка — нужна «{LAST_LINE} …»"))
    for no, line in enumerate(text.splitlines(), 1):
        if re.search(r"однажды", line, re.I):
            errs.append(
                ("S020", f"строка {no}: «однажды» — история, её место в PROCESS-WHY.md")
            )
        m = DATE_RE.search(line)
        if m:
            errs.append(
                (
                    "S021",
                    f"строка {no}: дата {m.group(0)} — история, её место в PROCESS-WHY.md",
                )
            )
        m = QUOTE_RE.search(line)
        if m:
            errs.append(
                (
                    "S022",
                    f"строка {no}: кавычки длиннее {QUOTE_MAX} знаков — похоже на цитату: {m.group(0)[:40]}…»",
                )
            )
        m = re.match(r"^#{2,3} (.+)", line)
        if m and m.group(1).startswith(BANNED_HEADS):
            errs.append(
                ("S023", f"строка {no}: раздел «{m.group(1)}» — скилл только из шагов")
            )
        for p in PATH_RE.findall(line):
            if (
                not p.startswith("architecture/TOBE/") and not (repo / p).exists()
            ):  # TOBE/ есть только у идущего изменения
                errs.append(("S030", f"строка {no}: файла {p} нет"))
    return errs


SAMPLE = """---
name: dev-sample
description: "Придуманный шаг для самопроверки: описание длиной больше ста знаков, чтобы шапка проходила все проверки этого скрипта без единой ошибки."
allowed-tools: Read, Bash
---

# /dev-sample — образец

Придуманный шаг.

1. **Прочитать:** `where.py --read dev-sample`.
2. **Запустить:** команду шага.
3. **Показать:** вывод решающему.

**По ходу всех шагов:** поправка хода — запись в журнал.
"""

SPOILS = {
    "S001": ("name: dev-sample\n", ""),
    "S002": ("name: dev-sample", "name: Dev_Sample"),
    "S003": ("name: dev-sample", "name: dev-other"),
    "S004": (
        'description: "Придуманный шаг для самопроверки: описание длиной больше ста знаков, чтобы шапка проходила все проверки этого скрипта без единой ошибки."\n',
        "",
    ),
    "S005": (
        "Придуманный шаг для самопроверки: описание длиной больше ста знаков, чтобы шапка проходила все проверки этого скрипта без единой ошибки.",
        "Короткое.",
    ),
    "S006": ("allowed-tools: Read, Bash\n", ""),
    "S010": (
        "# /dev-sample — образец\n",
        "# /dev-sample — образец\n\n# Второй заголовок\n",
    ),
    "S011": ("Придуманный шаг.\n", "ш" * (MAX_CHARS + 1) + "\n"),
    "S012": (
        "2. **Запустить:** команду шага.\n3. **Показать:** вывод решающему.\n",
        "",
    ),
    "S013": ("3. **Показать:**", "5. **Показать:**"),
    "S014": ("1. **Прочитать:**", "1. **Запустить сразу:**"),
    "S015": ("**По ходу всех шагов:** поправка хода — запись в журнал.\n", ""),
    "S020": ("Придуманный шаг.", "Однажды так уже было."),
    "S021": ("Придуманный шаг.", "Решено 19.10.2026."),
    "S022": ("Придуманный шаг.", "«" + "очень длинная цитата решающего " * 3 + "»"),
    "S023": ("Придуманный шаг.\n", "Придуманный шаг.\n\n## Чек-лист\n"),
    "S030": ("Придуманный шаг.", "Смотри `architecture/tools/нет-такого.py`."),
}


def selftest(verbose: bool) -> int:
    """Чистый образец проходит; каждая порча ловится своим кодом."""
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        clean = check(SAMPLE, "dev-sample", repo)
        if clean:
            bad.append(f"чистый образец: {clean}")
        for code, (old, new) in SPOILS.items():
            if old not in SAMPLE:
                bad.append(f"{code}: порча не нашла места в образце")
                continue
            codes = [c for c, _ in check(SAMPLE.replace(old, new), "dev-sample", repo)]
            if code not in codes:
                bad.append(f"{code}: порча не поймана, коды — {codes}")
            elif verbose:
                print(f"{code}: поймана")
    for x in bad:
        print(f"ошибка самопроверки: {x}")
    if bad:
        return 1
    print(f"Самопроверка: всё сходится (порч {len(SPOILS)}).")
    return 0


def resolve(arg: str, repo: Path) -> Path:
    """Имя скилла или путь к файлу — в путь к файлу."""
    if "/" in arg or "\\" in arg or arg.endswith(".md"):
        p = Path(arg)
        return p if p.is_absolute() else repo / p
    return SKILLS_DIR / arg / FILE_NAME


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(
        description="Проверка SKILL.md (шапка файла — подробно)."
    )
    ap.add_argument("skill", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest(a.verbose)
    repo = SKILLS_DIR.parents[1]
    files = (
        sorted(SKILLS_DIR.glob(f"*/{FILE_NAME}"))
        if a.all
        else [resolve(x, repo) for x in a.skill]
    )
    if not files:
        print(
            "что проверять: имя скилла, путь или --all"
            if not a.all
            else f"файлов {FILE_NAME} нет"
        )
        return 0 if a.all else 2
    failed = False
    for p in files:
        if not p.is_file():
            print(f"❌ {p}: файла нет")
            failed = True
            continue
        text = p.read_text(encoding="utf-8")
        errs = check(text, p.parent.name, repo)
        if errs:
            failed = True
            print(f"❌ {p.parent.name}: ошибок {len(errs)}")
            for code, msg in errs:
                print(f"   {code}: {msg}")
        else:
            print(f"✅ {p.parent.name} — {len(text)} знаков")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
