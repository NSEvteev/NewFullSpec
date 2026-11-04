"""Открыть страницу карты в браузере человека.

Зачем. Страницы карты собирает build.py; человек смотрит их в своём браузере по умолчанию, с диска (file://).
Страница самодостаточна: оформление подключено относительными путями (_shared/page.css, page.js), из сети —
только шрифты; без сети шрифт заменяется системным. Сервер не нужен.

Кто зовёт и когда — Claude, чтобы показать страницу решающему; сам человек — из терминала.
    python tools/open.py                          доска — ASIS/01_service-map.html
    python tools/open.py <сервис>                 страница сервиса
    python tools/open.py <процесс>                страница процесса (ключ процесса — имя его md); на ней же срезы
                                                  всех участников; своя работа сервиса — на странице сервиса
    python tools/open.py <путь к .html>           любая страница
    python tools/open.py --list                   все страницы по порядку показа, ничего не открывает:
                                                  доска, сервисы, процессы
    --root <карта>                                другая карта, например проверочная: tools/samples/good/architecture
Корень карты по умолчанию — папка над tools/.

Что читает: только какие html лежат в ASIS/ и реестр project/services.yaml (порядок сервисов в --list).
Что пишет: ничего; печатает путь открытой страницы.

Коды выхода: 0 — открыто (или список напечатан); 1 — страницы нет (нужна сборка build.py) или имя подходит к
нескольким страницам — они перечислены, ничего не открыто; 2 — ошибка ввода.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

import yaml


def pages_in_order(root: Path) -> list[Path]:
    """Страницы по порядку показа: доска, сервисы по реестру, процессы."""
    asis = root / "ASIS"
    reg = yaml.safe_load((root / "project" / "services.yaml").read_text(encoding="utf-8")) or {}
    out = [asis / "01_service-map.html"]
    for svc in reg:
        out.append(asis / svc / "index.html")
    out += sorted((asis / "_processes").glob("*.html"))
    return [p for p in out if p.is_file()]


def find(root: Path, args: list[str]) -> list[Path]:
    asis = root / "ASIS"
    if not args:
        return [asis / "01_service-map.html"]
    name = args[0]
    if name.endswith(".html"):
        return [Path(name)]
    found = [p for p in (asis / name / "index.html", asis / "_processes" / f"{name}.html") if p.is_file()]
    return found or [asis / name / "index.html"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Открыть страницу карты в браузере")
    ap.add_argument("what", nargs="?", help="сервис, процесс или путь к .html")
    ap.add_argument("--root", help="корень карты (папка с project/settings.yaml)")
    ap.add_argument("--list", action="store_true", help="все страницы по порядку показа")
    a = ap.parse_args()
    root = Path(a.root) if a.root else Path(__file__).resolve().parent.parent
    if not (root / "project" / "settings.yaml").is_file():
        print(f"{root} — не корень карты: нет project/settings.yaml", file=sys.stderr)
        return 2
    if a.list:
        for i, p in enumerate(pages_in_order(root), 1):
            print(f"{i:>3}  {p.resolve().relative_to(root.resolve()).as_posix()}")
        return 0
    found = find(root, [a.what] if a.what else [])
    if len(found) > 1:
        print("имя подходит к нескольким страницам — назови точнее:")
        for p in found:
            print("  ", p.resolve())
        return 1
    page = found[0].resolve()
    if not page.is_file():
        print(f"страницы нет: {page} — собрать: python tools/build.py")
        return 1
    webbrowser.open(page.as_uri())
    print(f"открыто: {page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
