"""Путеводитель CHANGELOG.md: шаги и блоки собирает из файлов изменения, руками — только «Сейчас» и события.

Зачем. Решающий читает путеводитель, а не поля карты. Когда он вёлся руками, шаги расходились с настоящим состоянием,
и каждый шаг процесса тратил на него отдельные правки. Шаг и блоки и так знает where.py.

Кто зовёт. Скиллы /dev*, основная сессия. Из корня репо:
  python <карта>/tools/devChangelog.py --now "<что делается и кем>" --next "<что дальше>" [--wait "<вопрос решающему>"]
  python <карта>/tools/devChangelog.py --log "<событие: дата подставится сама>"
  python <карта>/tools/devChangelog.py                          только пересобрать шапку и шаги
  python <карта>/tools/devChangelog.py --selftest               самопроверка на проверочной карте
  … --root <карта>   другая карта; … --file <файл>   другой файл; … --no-git   без git (проверочные карты)

Что пишет. CHANGELOG.md в корне репо; прежние «Сейчас», «Дальше», «Ждёт решающего» и «Ход работы» сохраняет, если их не
передали. Изменения нет — одна строка «Изменения нет». Пока агент коммитит в репо, не звать: правку съест
«спрятал — вернул» pre-commit.

Что читает. where.py (шаг, блоки), обложку, blocks.md и tasks.md: названия блоков и задач; дату — из git.

Коды выхода: 0 — записано; 1 — запись не вышла; 2 — ошибка вызова.

Чего не делает. Шаг не выбирает: это where.py. Дату начала и строки шагов не выдумывает: нет сведений — без них.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from where import STEPS, Where  # noqa: E402

TOOLS = Path(__file__).resolve().parent
SAMPLE = TOOLS / "samples" / "good"
STEP_TITLE = {"старт": "Старт", "описание": "Описание", "блок": "Блоки", "доставка": "Доставка", "закрытие": "Закрытие"}
HEAD = (
    "# CHANGELOG — путеводитель по идущему изменению\n\n"
    "*Где мы в изменении и что дальше — для решающего и для новой сессии Claude. Шаги собирает `devChangelog.py`, "
    "правило — [architecture/PROCESS.md](architecture/PROCESS.md), раздел 0.2. Задачи — "
    "[_backlog/CLAUDE.md](_backlog/CLAUDE.md).*\n"
)


def unmangle(text: str | None) -> str | None:
    """Git Bash превращает аргумент «/dev-close» в «C:/Program Files/Git/dev-close»: вернуть как было."""
    return re.sub(r"[A-Za-z]:/[^/]*(?:/[^/]*)*?/Git(?=/)", "", text) if text else text


def field(text: str, name: str) -> str:
    m = re.search(rf"^\*\*{name}:\*\* (.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def history(text: str) -> list[str]:
    m = re.search(r"^## Ход работы\n+(.*)\Z", text, re.M | re.S)
    return [x for x in m.group(1).splitlines() if x.strip()] if m else []


def task_titles(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted((root / "TOBE").glob("*/tasks.md")):
        for m in re.finditer(r"^### (.+?) \{#(k-[a-z0-9-]+)\}", p.read_text(encoding="utf-8"), re.M):
            out[m.group(2)] = m.group(1).strip()
    return out


def steps_lines(w: Where, step: str, info: dict, root: Path) -> list[str]:
    i = STEPS.index(step)
    lines = []
    for k, s in enumerate(STEPS):
        mark = "✅" if k < i else "▶" if k == i else "⬜"
        lines.append(f"- {mark} {k + 1}. {STEP_TITLE[s]}")
        if s == "блок":
            titles = task_titles(root)
            for b in info.get("blocks") or w.blocks():
                done = bool(b.get("Сделано"))
                now = b["anchor"] == info.get("current")
                lines.append(f"  - {'✅' if done else '▶' if now else '⬜'} Б{b['anchor'][1:]}. {b['title']}")
                for key in re.findall(r"\[\[(k-[a-z0-9-]+)\]\]", str(b.get("Задачи") or "")):
                    lines.append(f"    - {'✅' if done else '⬜'} {titles.get(key, key)}")
    return lines


def render(root: Path, old: str, now: str | None, nxt: str | None, wait: str | None, log: str | None, use_git: bool) -> str:
    w = Where(root, use_git)
    step, info = w.step()
    if step == "нет":
        return HEAD + "\nИзменения нет.\n"
    events = history(old)
    if log:
        events.insert(0, f"- {date.today().isoformat()} {log}")
    now_text = now if now is not None else field(old, "Сейчас")
    next_text = nxt if nxt is not None else field(old, "Дальше")
    wait_text = wait if wait is not None else (field(old, "Ждёт решающего") or "ничего")
    head = f"**{w.chg.title}** · ветка `{w.branch() or '?'}`"
    parts = [HEAD, head + "\n", f"**Сейчас:** {now_text}\n**Дальше:** {next_text}\n**Ждёт решающего:** {wait_text}\n", "## Шаги\n"]
    parts.append("\n".join(steps_lines(w, step, info, root)) + "\n")
    parts.append("## Ход работы\n")
    parts.append("\n".join(events) + ("\n" if events else ""))
    return "\n".join(parts)


def selftest() -> int:
    bad: list[str] = []
    if unmangle("C:/Program Files/Git/dev-block b2") != "/dev-block b2" or unmangle("показ и «да»") != "показ и «да»":
        bad.append("текст из Git Bash не восстановлен")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        good = Path(tmp) / "good"
        shutil.copytree(SAMPLE, good)
        root = good / "architecture"
        text = render(root, "", "описание, основная сессия", "показ", None, "старт: решения записаны", False)
        for want in ("**Оплата с повтором**", "`change/payment-retry`", "**Сейчас:** описание, основная сессия", "**Ждёт решающего:** ничего", "- ✅ 1. Старт", "- ▶ 2. Описание", "- ⬜ 3. Блоки", "- ⬜ 5. Закрытие", "старт: решения записаны"):
            if want not in text:
                bad.append(f"нет «{want}»")
        if "orders: повтор оплаты" not in text or "Повтор списания с ключом повтора" not in text:
            bad.append("нет блока или задачи названиями")
        again = render(root, text, None, None, None, "ещё событие", False)
        if "**Сейчас:** описание, основная сессия" not in again or "ещё событие" not in again or "старт: решения записаны" not in again:
            bad.append("прежние поля и ход работы не сохранились")
        if again.index("ещё событие") > again.index("старт: решения записаны"):
            bad.append("новое событие не сверху")
        for p in sorted((root / "TOBE").rglob("*")):
            if p.is_file() and p.name != ".gitkeep":
                p.unlink()
        if "Изменения нет" not in render(root, text, None, None, None, None, False):
            bad.append("нет изменения — нет строки «Изменения нет»")
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
    ap = argparse.ArgumentParser(prog="devChangelog.py", description="Путеводитель (шапка файла — подробно).")
    ap.add_argument("--now")
    ap.add_argument("--next", dest="nxt")
    ap.add_argument("--wait")
    ap.add_argument("--log")
    ap.add_argument("--root")
    ap.add_argument("--file")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    root = Path(a.root) if a.root else TOOLS.parent
    target = Path(a.file) if a.file else root.parent / "CHANGELOG.md"
    old = target.read_text(encoding="utf-8") if target.is_file() else ""
    try:
        target.write_text(render(root, old, unmangle(a.now), unmangle(a.nxt), unmangle(a.wait), unmangle(a.log), not a.no_git), encoding="utf-8", newline="\n")
    except OSError as e:
        print(f"запись не вышла: {e}")
        return 1
    print(f"{target.name} собран")
    return 0


if __name__ == "__main__":
    sys.exit(main())
