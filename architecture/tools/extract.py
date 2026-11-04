"""Скрипт фактов: вынимает из кода, compose, живой схемы методов, живой базы и тестов то, что о сервисе можно узнать
без человека, — в ASIS/<сервис>/.facts.json.

Зачем. Пишущий карту не пишет того, что знает код: обработчик метода и его строку, поля запроса и ответа, колонки и
типы, значения настроек, порт, число тестов. Это факты: их вынимает скрипт, генератор ставит их на страницы, а
проверки по ним находят метод, таблицу или настройку без описания. Живая проверка вынимает факты заново и
сравнивает со старыми: так видно, что код ушёл вперёд от описания.

Как устроен. Сам скрипт про технологии не знает. У сервиса в реестре project/services.yaml поле facts — список
частей скрипта (по технологии: compose, fastapi-openapi, postgres…). Каждая часть — файл tools/facts/<часть>.py
со своим договором (tools/facts/__init__.py) и своим разделом в .facts.json. Части идут в порядке их зависимостей
(NEEDS): compose — первой, база — после настроек, где её адрес.

Кто зовёт и когда. Основная сессия или скрипт карты: при переносе карты, на новом сервисе, на закрытии изменения
(факты — заново); на старте изменения и закрытии — живая проверка (--check), она ничего не пишет.

Команды (из корня репо или откуда угодно):
  python <карта>/tools/extract.py orders            факты сервиса orders → <карта>/ASIS/orders/.facts.json
  python <карта>/tools/extract.py --all             факты всех сервисов реестра (тесты — только сбор, без прогона)
  python <карта>/tools/extract.py orders --tests    и прогнать тесты — по одному сервису, с потолком памяти
  python <карта>/tools/extract.py --all --check     живая проверка: вынуть заново, сравнить, ничего не писать
  --root <папка>  корень карты (папка с project/settings.yaml); по умолчанию — папка над tools/

Что читает: project/services.yaml, project/settings.yaml, код сервисов, compose, живые /openapi.json и базы
(только чтение), прежний .facts.json (итог прошлого прогона тестов). Что пишет: ASIS/<сервис>/.facts.json — без
--check. Строение файла: наверху service, commit (короткий коммит репо, на котором вынимали), extracted_at, parts,
code (files и lines — файлы и непустые строки кода сервиса без тестов и миграций, exts — по каким расширениям;
только если хоть одна часть знает язык), дальше — раздел на каждую часть под её именем.

Коды выхода: 0 — готово, расхождений нет; 1 — в --check есть расхождения или часть упала; 2 — неверный вызов:
сервиса нет в реестре, неизвестная часть, нет поля facts.

Чего не делает и что нельзя. Не пишет md и html. Факты руками не правятся. Значения секретов в файл не попадают.
Живые системы — только чтение. Тесты --all не прогоняются: прогон — по одному сервису.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from facts._base import Ctx, code_files, code_lines  # noqa: E402

PARTS_DIR = TOOLS / "facts"


def load_part(name: str):
    """Модуль части по имени из реестра; имя с дефисом — файл с дефисом."""
    path = PARTS_DIR / f"{name}.py"
    if name.startswith("_") or not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"facts.{name.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ordered(parts: list[str], mods: dict) -> list[str]:
    """Порядок частей: каждая — после тех, что ей нужны (NEEDS) и есть у сервиса; иначе — как в реестре."""
    out: list[str] = []

    def visit(p: str, path: tuple = ()) -> None:
        if p in out or p in path:
            return
        for n in getattr(mods[p], "NEEDS", ()):
            if n in parts:
                visit(n, path + (p,))
        out.append(p)

    for p in parts:
        visit(p)
    return out


def git_commit(repo: Path) -> str:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or "?"


def extract(svc: str, info: dict, mods: dict, settings: dict, registry: dict, repo: Path, previous: dict,
            run_tests: bool) -> tuple[dict, list[str]]:
    """Факты одного сервиса и список ошибок частей."""
    parts = ordered(info["facts"], mods)
    ctx = Ctx(svc, info, settings, registry, repo, previous=previous, run_tests=run_tests)
    facts: dict = {"service": svc, "commit": git_commit(repo), "extracted_at": dt.datetime.now().isoformat(timespec="seconds"),
                   "parts": parts}
    exts = tuple(sorted({e for p in parts for e in getattr(mods[p], "CODE_EXTS", ())}))
    if exts and ctx.package.is_dir():
        files = code_files(ctx.package, exts)
        facts["code"] = {"files": len(files), "lines": code_lines(files), "exts": list(exts)}
    errors = []
    for p in parts:
        try:
            section = mods[p].extract(ctx)
        except Exception as e:  # noqa: BLE001 — часть упала: сервис без её раздела, но остальные части идут
            section = {"error": f"{type(e).__name__}: {e}"}
        if section.get("error"):
            errors.append(f"{svc}: часть {p} — {section['error']}")
        ctx.facts[p] = section
        facts[p] = section
    return facts, errors


def summary(f: dict) -> str:
    bits = []
    if "code" in f:
        bits.append(f"строк кода {f['code']['lines']}")
    if "fastapi-openapi" in f:
        o = f["fastapi-openapi"]
        bits.append(f"методов {o.get('count', 0)}" + ("" if o.get("live") else f" ({o.get('reason', '')})"))
    for p in ("pydantic-settings", "vite-env"):
        if p in f:
            bits.append(f"настроек {len(f[p].get('settings', []))}")
    if "postgres" in f:
        db = f["postgres"]
        bits.append(f"таблиц {len(db.get('tables', []))}" + ("" if db.get("live") else " (база не прочитана)"))
    if "python-exports" in f:
        bits.append(f"имён наружу {len(f['python-exports'].get('exports', []))}")
    for p in ("pytest", "vitest"):
        if p in f:
            bits.append(f"тестов {sum(f[p].get('collected', {}).values())}"
                        + (f", прогон {f[p]['run']['date']}" if (f[p].get("run") or {}).get("date") else ""))
    return ", ".join(bits)


def main() -> int:
    ap = argparse.ArgumentParser(description="Вынуть факты сервисов карты в ASIS/<сервис>/.facts.json")
    ap.add_argument("services", nargs="*", help="ключи из project/services.yaml")
    ap.add_argument("--all", action="store_true", help="все сервисы реестра")
    ap.add_argument("--tests", action="store_true", help="прогнать тесты (только для одного сервиса)")
    ap.add_argument("--check", action="store_true", help="живая проверка: сравнить с записанным, не писать")
    ap.add_argument("--root", default=str(TOOLS.parent), help="корень карты (папка с project/settings.yaml)")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    repo = root.parent
    registry = yaml.safe_load((root / "project/services.yaml").read_text(encoding="utf-8")) or {}
    settings = yaml.safe_load((root / "project/settings.yaml").read_text(encoding="utf-8")) or {}
    keys = list(registry) if a.all else a.services
    if a.all and not keys:  # новый проект: реестр пуст, сверять нечего — это не ошибка
        return 0
    if not keys:
        ap.error("укажите сервис или --all")
    if a.tests and len(keys) != 1:
        ap.error("--tests — только для одного сервиса: прогон всех разом занимает слишком много памяти")
    mods: dict = {}
    for k in keys:
        if k not in registry:
            print(f"нет в реестре: {k}", file=sys.stderr)
            return 2
        if "facts" not in registry[k]:
            print(f"у {k} в реестре нет поля facts", file=sys.stderr)
            return 2
        for p in registry[k]["facts"]:
            if p not in mods:
                mods[p] = load_part(p)
            if mods[p] is None:
                print(f"{k}: неизвестная часть фактов «{p}» — нет файла tools/facts/{p}.py", file=sys.stderr)
                return 2
    failed = False
    for k in keys:
        info = registry[k]
        out = root / "ASIS" / k / ".facts.json"
        if not info["facts"]:
            print(f"{k}: фактов нет (facts: []) — описан одними md")
            continue
        previous = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
        facts, errors = extract(k, info, mods, settings, registry, repo, previous, a.tests)
        for e in errors:
            print(f"ошибка: {e}")
        failed |= bool(errors)
        if a.check:
            if not previous:
                print(f"{k}: прежних фактов нет — сравнивать не с чем")
                failed = True
                continue
            diffs = []
            for p in facts["parts"]:
                if p not in previous:
                    diffs.append(f"{p}: раздела не было")
                else:
                    diffs += mods[p].compare(previous[p], facts[p])
            print(f"{k}: " + ("совпадает" if not diffs else f"расхождений {len(diffs)}"))
            for d in diffs:
                print(f"  {d}")
            failed |= bool(diffs)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(facts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"{k}: {summary(facts)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
