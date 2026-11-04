"""Сверка полноты «как будет»: пункт требований, решение, правка, задача, блок — таблицей, дыры отдельно.

Зачем. Проверки карты видят форму описания, а не его полноту: правку без задачи они поймают, а требование, которое не
легло никуда, — нет. Скрипт собирает заготовку сверки, чтобы сессия читала глазами только то, что машина решить не может.

Кто зовёт. Скилл /dev-describe, сверка перед показом. Из корня репо:
  python <карта>/tools/devCoverage.py               таблица и дыры по идущему изменению
  python <карта>/tools/devCoverage.py --selftest    самопроверка на проверочной карте и порченых копиях
  … --root <карта>   другая карта

Что считает дырой:
  решение (пункт требований с якорем d-…), на которое не ссылается ни одна правка;
  правка «новое» или «меняется» без ссылки на решение и без «по рекомендации»;
  правка, которой нет ни в одной задаче; задача, которой нет ни в одном блоке.
Что отдаёт глазам: пункты требований без якоря — машина не знает, легли ли они в описание; правки «по рекомендации».

Что читает. Обложку, набор требований по её полю «Требования:», копии и новые файлы TOBE/, tasks.md, blocks.md. Ничего не пишет.

Коды выхода: 0 — дыр нет; 1 — есть; 2 — ошибка вызова.

Чего не делает. Не понимает смысл: пункт, который лёг в описание иначе, чем сказано (другое число, другой край), видит
только тот, кто читает.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapmodel import requirement_files  # noqa: E402

TOOLS = Path(__file__).resolve().parent
SAMPLE = TOOLS / "samples" / "good"
BLOCK_RE = re.compile(r"^::: (новое|меняется|уходит) (c-[a-z0-9-]+)")
NEW_FILE_RE = re.compile(r"^Правка: (c-[a-z0-9-]+)")
LINK = r"\[\[([a-z]-[a-z0-9-]+|b\d+)\]\]"
ANCHOR_RE = re.compile(r"\{#(d-[a-z0-9-]+)\}")
MARK_RE = re.compile(r"^\s*-\s*(?:\((?:решено|по рекомендации|не согласовано|предложено|открыто)\)|✅)")


def changes(tobe: Path) -> dict[str, dict]:
    """Правки: номер → вид, файл, решения, по рекомендации ли."""
    out: dict[str, dict] = {}
    for p in sorted(tobe.rglob("*.md")):
        if p.name in ("tasks.md", "blocks.md") or p == tobe / "README.md":
            continue
        lines = p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
        rel = p.relative_to(tobe).as_posix()
        i = 0
        while i < len(lines):
            m, new = BLOCK_RE.match(lines[i]), NEW_FILE_RE.match(lines[i])
            if m:
                j = next((k for k in range(i + 1, len(lines)) if lines[k].strip() == ":::"), len(lines))
                why = next((x for x in reversed(lines[i:j]) if x.startswith("Почему:")), "")
                out[m.group(2)] = {"kind": m.group(1), "file": rel, "why": why}
                i = j
            elif new:
                why = next((x for x in lines[i:i + 3] if x.startswith("Почему:")), "")
                out[new.group(1)] = {"kind": "новое", "file": rel, "why": why}
            i += 1
    return out


def report(root: Path) -> tuple[list[str], list[str], list[str]]:
    """Таблица, дыры, что смотреть глазами."""
    tobe = root / "TOBE"
    cover = tobe / "README.md"
    if not cover.is_file():
        raise ValueError("изменения нет: обложки TOBE/README.md нет")
    spec = next((x.split(":", 1)[1] for x in cover.read_text(encoding="utf-8").splitlines() if x.startswith("Требования:")), "")
    decisions: dict[str, str] = {}
    eyes: list[str] = []
    for p in requirement_files(root, spec):
        for no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            m = ANCHOR_RE.search(line)
            if m:
                decisions[m.group(1)] = line.strip()[:70]
            elif MARK_RE.match(line):
                eyes.append(f"{p.relative_to(root.parent).as_posix()}:{no} — пункт без якоря: {line.strip()[:80]}")
    edits = changes(tobe)
    task_of: dict[str, list[str]] = {}
    for p in sorted(tobe.glob("*/tasks.md")):
        task = None
        for line in p.read_text(encoding="utf-8").splitlines():
            h = re.search(r"\{#(k-[a-z0-9-]+)\}", line) if line.startswith("#") else None
            if line.startswith("#"):
                task = h.group(1) if h else None
            elif task and line.startswith("Правки:"):
                for c in re.findall(LINK, line):
                    task_of.setdefault(c, []).append(task)
    block_of: dict[str, list[str]] = {}
    blocks_p = tobe / "blocks.md"
    if blocks_p.is_file():
        block = None
        for line in blocks_p.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                h = re.search(r"\{#(b\d+)\}", line)
                block = h.group(1) if h else None
            elif block and line.startswith("Задачи:"):
                for k in re.findall(LINK, line):
                    block_of.setdefault(k, []).append(block)
    table: list[str] = []
    holes: list[str] = []
    cited: dict[str, list[str]] = {}
    for num, e in edits.items():
        for d in re.findall(LINK, e["why"]):
            if d.startswith("d-"):
                cited.setdefault(d, []).append(num)
    for d, text in decisions.items():
        nums = cited.get(d, [])
        if not nums:
            holes.append(f"решение {d} — ни одна правка на него не ссылается: {text}")
        for num in nums:
            ks = task_of.get(num, [])
            bs = [b for k in ks for b in block_of.get(k, [])]
            table.append(f"{d} → {num} → {', '.join(ks) or '—'} → {', '.join(dict.fromkeys(bs)) or '—'}")
    for num, e in edits.items():
        ks = task_of.get(num, [])
        if e["kind"] != "уходит" and not re.search(r"\[\[d-", e["why"]):
            if "по рекомендации" in e["why"]:
                eyes.append(f"{num} ({e['file']}) — по рекомендации: не меняет ли видимого человеку")
            else:
                holes.append(f"{num} ({e['file']}) — правка без решения и без «по рекомендации»")
        if not ks and not e["file"].startswith("_processes/"):  # правка процесса в задачи сервиса не входит
            holes.append(f"{num} ({e['file']}) — правки нет ни в одной задаче")
    for k in sorted({k for ks in task_of.values() for k in ks}):
        if k not in block_of:
            holes.append(f"задачи {k} нет ни в одном блоке")
    return table, holes, eyes


def selftest() -> int:
    bad: list[str] = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        good = Path(tmp) / "good"
        shutil.copytree(SAMPLE, good)
        root = good / "architecture"
        table, holes, _ = report(root)
        if holes or not table:
            bad.append(f"чистая карта: дыр {len(holes)}, строк {len(table)}: {holes[:3]}")

        def spoil(rel: str, old: str, new: str, want: str) -> None:
            p = good / rel
            before = p.read_text(encoding="utf-8")
            if old not in before:
                bad.append(f"порча «{want}»: нет места в {rel}")
                return
            p.write_text(before.replace(old, new), encoding="utf-8", newline="\n")
            _, found, _ = report(root)
            if not any(want in x for x in found):
                bad.append(f"порча «{want}» не поймана: {found[:3]}")
            p.write_text(before, encoding="utf-8", newline="\n")

        spoil("architecture/TOBE/orders/tasks.md", "Правки: [[c-ord-post-202]]", "Правки:", "c-ord-post-202")
        spoil("architecture/TOBE/blocks.md", "[[k-ord-202]] · ", "", "задачи k-ord-202")
        text = (good / "_backlog/promt-payment-retry.md").read_text(encoding="utf-8")
        (good / "_backlog/promt-payment-retry.md").write_text(text + "\n- **Новое** {#d-nobody} (владелец, 2026-10-20: «да»): без правок.\n", encoding="utf-8", newline="\n")
        if not any("d-nobody" in x for x in report(root)[1]):
            bad.append("решение без правки не поймано")
        (good / "_backlog/promt-payment-retry.md").write_text(text, encoding="utf-8", newline="\n")
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
    ap = argparse.ArgumentParser(prog="devCoverage.py", description="Сверка полноты (шапка файла — подробно).")
    ap.add_argument("--root")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    root = Path(a.root) if a.root else TOOLS.parent
    try:
        table, holes, eyes = report(root)
    except ValueError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2
    print("решение → правка → задача → блок:")
    print("\n".join(table) if table else "строк нет")
    print(f"\nдыры: {len(holes)}")
    print("\n".join(holes))
    print(f"\nсмотреть глазами: {len(eyes)}")
    print("\n".join(eyes))
    return 1 if holes else 0


if __name__ == "__main__":
    sys.exit(main())
