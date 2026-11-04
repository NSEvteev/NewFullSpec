"""Живая проверка карты: факты вынимаются заново и сравниваются, каждая ссылка на код — по запомненному тексту.

Зачем. Сборка проверяет карту без живого окружения; а сошлась ли карта с тем, что работает сейчас, видно только
здесь: методы — с живой схемой, колонки и строки — с живой базой, ссылки «Код:» — с текстом строк. Обязательна на
старте изменения и на закрытии: на старте — чтобы начинать с верной карты, на закрытии — чтобы сдать верную.

Кто зовёт. Основная сессия на старте и закрытии изменения; where.py --gate done через done.py. Из корня репо:
  python <карта>/tools/live.py                     всё: факты всех сервисов, проверки карты, строки кода
  python <карта>/tools/live.py --service orders    только этот сервис (факты и его ссылки на код)
  python <карта>/tools/live.py --no-facts          без живого окружения: проверки карты и строки кода
  … --root <карта>                                 другая карта
Что читает. Карту (модель и проверки), код по ссылкам «Код:», ASIS/*/.anchors.json; для фактов — зовёт
extract.py --check (живая схема, база, compose). Ничего не пишет.

Сообщения: «факты: <сервис> — …» (расхождение с живым), «строка изменилась: путь:строка — было «…», сейчас «…»;
проверь шаг, намеренно — map.py accept путь:строка; сдвиг — relocate.py», «не запомнена: …» (нужна полная сборка),
ошибки модели и проверок карты. Строка с секретом показывается отпечатком.

Коды выхода: 0 — ошибок нет; 1 — есть; 2 — ошибка вызова.

Чего не делает. Не правит md, факты и запомненные строки: чинят сборка, relocate.py, map.py accept и пишущий.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchors  # noqa: E402
import checks  # noqa: E402
from mapmodel import MapModel  # noqa: E402


def facts(root: Path, service: str | None) -> list[str]:
    tools = Path(__file__).resolve().parent
    args = [sys.executable, str(tools / "extract.py"), "--check", "--root", str(root)]
    args += [service] if service else ["--all"]
    res = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    out = []
    for line in res.stdout.splitlines():
        svc, _, msg = line.partition(": ")
        if msg and not msg.startswith(("совпадает", "фактов нет")):
            out.append(f"факты: {svc} — {msg}")
    if res.returncode not in (0, 1) and not out:
        out.append(f"факты: extract.py упал — {(res.stderr.strip().splitlines() or ['?'])[-1]}")
    return out


def short(t: str | None) -> str:
    if t is None:
        return "строки нет"
    return t if len(t) <= 80 else t[:79] + "…"


def run(root: Path, service: str | None, with_facts: bool) -> list[str]:
    m = MapModel(root)
    r = checks.run(m)
    prefix = f"ASIS/{service}/" if service else ""
    errs = [e for e in m.errors + r.errors if e.startswith(prefix)]
    if with_facts:
        errs += facts(root, service)
    for folder, key, was, now, where in anchors.changed(m):
        if service and folder != f"ASIS/{service}":
            continue
        errs.append(
            f"{where[0]} — строка изменилась: {key} — было «{short(was)}», сейчас «{short(now)}»; проверь, что "
            f"написано; намеренно — map.py accept {key}; сдвиг — relocate.py"
        )
    for folder, key, where in anchors.missing(m):
        if service and folder != f"ASIS/{service}":
            continue
        errs.append(f"{where[0]} — ссылка {key} не запомнена: нужна полная сборка build.py")
    return errs


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="live.py", description="Живая проверка карты (шапка файла — подробно).")
    ap.add_argument("--service")
    ap.add_argument("--no-facts", action="store_true")
    ap.add_argument("--root")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else Path(__file__).resolve().parent.parent
    if not (root / "project" / "settings.yaml").is_file():
        print(f"ошибка: {root} — не корень карты", file=sys.stderr)
        return 2
    errs = run(root, a.service, not a.no_facts)
    for e in errs:
        print("ошибка:", e)
    print(f"живая проверка{' ' + a.service if a.service else ''}: ошибок {len(errs)}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
