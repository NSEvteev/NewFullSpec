"""Бриф агенту блока: задачи, тесты и «Готово, когда» подставляет скрипт, основная сессия пишет только границу.

Зачем. Бриф — полный промт: агент не видел разговора. Раньше основная сессия читала вывод find.py и переписывала его в
бриф руками: один и тот же текст проходил через контекст дважды, а брифы шли десятки минут.

Кто зовёт. Скилл /dev-block, основная сессия. Из корня репо:
  python <карта>/tools/devBrief.py <блок> --out <файл>    бриф из шаблона; файл уже есть — отказ, заново — --force
  python <карта>/tools/devBrief.py --check <файл>         что ещё не заполнено; годится ли граница
  python <карта>/tools/devBrief.py --selftest             самопроверка на проверочной карте и порченых копиях
  … --root <карта>   другая карта

Что читает. Шаблон .claude/skills/dev-block/templates/brief-block.md, обложку и find.py <ключ> --tobe. Пишет только
файл --out: брифу место во временной папке сессии, не в репо.

Что подставляет. {{номер}}, {{якорь}}, {{название блока}}, {{изменение}}, {{ветка}}, {{правки}} — команды find.py по
правкам задач; {{блок и задачи}} — вывод find.py по блоку, его задачам и тестам дословно.

Коды выхода: 0 — готово; 1 — бриф не готов или блока нет: причина в выводе; 2 — ошибка вызова.

Чего не делает. Не заполняет границу и проверки: их знает только основная сессия после разведки. Не запускает агента.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
TEMPLATE = TOOLS.parents[1] / ".claude" / "skills" / "dev-block" / "templates" / "brief-block.md"
SAMPLE = TOOLS / "samples" / "good" / "architecture"
UNFILLED = re.compile(r"<(?![^<>\n]*@)[^<>\n]{1,200}>")  # адрес в угловых скобках — не незаполненное
TOKEN = re.compile(r"\{\{[^{}]+\}\}")
TAIL = "## Формат ответа"


def find(root: Path, key: str) -> str:
    res = subprocess.run(
        [sys.executable, str(TOOLS / "find.py"), key, "--tobe", "--root", str(root)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if res.returncode != 0:
        raise LookupError(f"find.py {key}: {(res.stdout + res.stderr).strip()[:200]}")
    return res.stdout.strip()


def build(root: Path, block: str, template: str) -> str:
    """Текст брифа: шаблон с подстановками; угловые скобки остаются основной сессии."""
    block_text = find(root, block)
    title = re.search(r"блок «(.+?)»", block_text.splitlines()[0])
    tasks = re.findall(r"\[\[(k-[a-z0-9-]+)\]\]", next((x for x in block_text.splitlines() if "Задачи:" in x), ""))
    parts = [block_text]
    tests: list[str] = []
    changes: list[str] = []
    for key in tasks:
        text = find(root, key)
        parts.append(text)
        for line in text.splitlines():
            if "Тесты:" in line:
                tests += re.findall(r"\[\[(t-[a-z0-9-]+)\]\]", line)
            if "Правки:" in line:
                changes += re.findall(r"\[\[(c-[a-z0-9-]+)\]\]", line)
    parts += [find(root, key) for key in dict.fromkeys(tests)]
    cover = (root / "TOBE" / "README.md").read_text(encoding="utf-8")
    change = re.search(r"^# (.+)$", cover, re.M)
    branch = re.search(r"^Ветка:\s*(.+)$", cover, re.M)
    values = {
        "номер": "Б" + block.lstrip("b"),
        "якорь": block,
        "название блока": title.group(1) if title else block,
        "изменение": change.group(1).strip() if change else "?",
        "ветка": branch.group(1).strip(" `") if branch else "?",
        "правки": "; ".join(f"python architecture/tools/find.py {c} --tobe" for c in dict.fromkeys(changes)) or "правок нет",
        "блок и задачи": "\n\n".join(parts),
    }
    text = template
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    left = TOKEN.findall(text)
    if left:
        raise LookupError(f"в шаблоне неизвестные места: {left}")
    return re.sub(r"\A<!--.*?-->\s*", "", text, flags=re.S)


def check_text(text: str) -> list[str]:
    """Что мешает отдать бриф агенту. Вид ответа и команды find.py — не незаполненное."""
    head = text.split(TAIL, 1)[0]
    head = re.sub(r"(## Задачи блока\n).*?(\nЧитать:)", r"\1\2", head, flags=re.S)  # вывод find.py — не незаполненное
    out = [f"не заполнено: {m}" for m in dict.fromkeys(UNFILLED.findall(head))]
    border = re.search(r"## Граница\n(.*?)(?=\n## )", text, re.S)
    if not border:
        out.append("нет раздела «Граница»")
    elif re.search(r"и т\. ?[пд]\.|и другое|и прочее", border.group(1)):
        out.append("в «Границе» неопределённость вроде «и т. п.»: список должен быть закрытым")
    if "## Проверки" not in text:
        out.append("нет раздела «Проверки»: список проверок закрытый")
    if not re.search(r"~\d+ минут", text):
        out.append("не указано ожидаемое время: «~N минут»")
    if TAIL not in text:
        out.append("нет раздела «Формат ответа»")
    return out


def selftest() -> int:
    bad: list[str] = []
    template = TEMPLATE.read_text(encoding="utf-8")
    text = build(SAMPLE, "b1", template)
    for want in ("Б1", "orders: повтор оплаты", "Оплата с повтором", "change/payment-retry", "k-ord-retry", "t-ord-retry",
                 "Готово, когда:", "find.py c-ord-charge --tobe"):
        if want not in text:
            bad.append(f"в брифе нет «{want}»")
    if "{{" in text or text.startswith("<!--"):
        bad.append("в брифе остались места шаблона или его комментарий")
    if not check_text(text):
        bad.append("незаполненный бриф прошёл проверку")
    filled = re.sub(r"<[^<>\n]{1,200}>", "значение", text.split(TAIL, 1)[0]).replace("~значение минут", "~20 минут") + TAIL + text.split(TAIL, 1)[1]
    if check_text(filled):
        bad.append(f"заполненный бриф не прошёл: {check_text(filled)}")
    spoils = {
        "и т. п. в границе": (filled.replace("## Граница\n", "## Граница\nи т. п.\n"), "неопределённость"),
        "без времени": (filled.replace("~20 минут", "сколько выйдет"), "ожидаемое время"),
        "без границы": (filled.replace("## Граница\n", "## Другое\n"), "«Граница»"),
        "без проверок": (filled.replace("## Проверки", "## Другое"), "«Проверки»"),
        "остаток в строке Читать": (filled.replace("Читать: architecture/CLAUDE.md", "Читать: <копии> architecture/CLAUDE.md"), "не заполнено"),
    }
    for name, (spoiled, want) in spoils.items():
        if not any(want in x for x in check_text(spoiled)):
            bad.append(f"порча «{name}» не поймана")
    if check_text(filled.replace("## Коммиты\n", "## Коммиты\nCo-Authored-By: Имя <a@b.c>\n")):
        bad.append("адрес в угловых скобках принят за незаполненное")
    try:
        build(SAMPLE, "b99", template)
        bad.append("несуществующий блок не пойман")
    except LookupError:
        pass
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "b.md"
        if main(["b1", "--out", str(out), "--root", str(SAMPLE)]) != 0 or not out.is_file():
            bad.append("--out не записал бриф")
        if main(["b1", "--out", str(out), "--root", str(SAMPLE)]) != 1:
            bad.append("чужой файл с тем же именем перезаписан без --force")
    for x in bad:
        print(f"ошибка самопроверки: {x}")
    if bad:
        return 1
    print(f"Самопроверка: всё сходится (порч {len(spoils)}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="devBrief.py", description="Бриф агенту блока (шапка файла — подробно).")
    ap.add_argument("block", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--check")
    ap.add_argument("--root")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.check:
        found = check_text(Path(a.check).read_text(encoding="utf-8"))
        print("\n".join(found) if found else "бриф готов: можно запускать агента")
        return 1 if found else 0
    if not a.block or not a.out:
        print("ошибка: нужно <блок> --out <файл>, --check <файл> или --selftest", file=sys.stderr)
        return 2
    out = Path(a.out)
    if out.exists() and not a.force:
        print(f"{out}: файл уже есть — это может быть бриф прошлого изменения; заново — --force")
        return 1
    root = Path(a.root) if a.root else TOOLS.parent
    try:
        text = build(root, a.block, TEMPLATE.read_text(encoding="utf-8"))
    except LookupError as e:
        print(e)
        return 1
    out.write_text(text, encoding="utf-8", newline="\n")
    found = check_text(text)
    print(f"{out}: бриф из шаблона, заполнить мест: {len(found)}; затем devBrief.py --check {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
