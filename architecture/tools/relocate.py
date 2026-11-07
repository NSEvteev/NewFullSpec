"""Перенос съехавших ссылок на код: код сдвинул строки — номера в «Код:» md переносятся на новые места.

Зачем. Ссылка `путь:строка` указывает на строку, которая после правки кода стоит ниже или выше. Найти её новое
место можно по запомненному тексту (ASIS/*/.anchors.json): если строка с тем же текстом в файле одна или стоит на
сдвиге соседней уже перенесённой ссылки — это та же строка. Тексты читаются все до переноса; номер, на который
претендуют две ссылки, ни одной не ставится. Остальное переносится руками, с подсказкой, где искать. Тот же расчёт
(solve) переносит ссылки правок «как будет» — map.py code --relocate.

Кто зовёт. Только основная сессия — на закрытии изменения до агентов и после правок кода, сдвинувших строки
(агенты его не запускают: он пересобирает общие страницы). Из корня репо:
  python <карта>/tools/relocate.py            перенести, что переносится; остальное — списком «вручную»
  python <карта>/tools/relocate.py --dry-run  только показать, что перенёс бы
  … --root <карта>                            другая карта
Что читает и пишет. Читает модель карты, код и запомненные строки. Пишет в md только номера строк в «Код:» —
единственное исключение из «md пишет только пишущий» — и ключи в .anchors.json (текст тот же). Страницы после
переноса собирает полная сборка build.py — команда напоминает об этом.

Коды выхода: 0 — всё перенесено или переносить нечего; 1 — осталось «вручную»; 2 — ошибка вызова.

Чего не делает. Строку, у которой поменялся текст (а не место), не трогает: это правка смысла — map.py accept
после того, как пишущий проверил описание.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchors  # noqa: E402
from mapmodel import MapModel  # noqa: E402


def solve(lines: anchors.Lines, todo: dict[str, str], stay: set[str]) -> tuple[dict[str, int], dict[str, str]]:
    """Новые номера ссылок, чей текст на месте не совпал с запомненным. todo — {путь:строка: запомненный текст}, stay —
    ссылки, что остаются на своих номерах. Тексты — только запомненные до переноса: ни одна ссылка не ищется по тексту,
    записанному этим же переносом (однажды соседние :650 и :654 при сдвиге +4 обе стали :654). Кандидат — строка файла
    с тем же текстом (пробелы по краям не в счёт): один — он; несколько — тот единственный, что на сдвиге уже
    перенесённой ссылки того же файла; иначе — «вручную» с кандидатами. Номер, на который переходят две ссылки или
    который остаётся за неперенесённой, — «вручную» у переносимых: у двух ссылок один номер — одна из них наугад.
    Ответ: ({путь:строка: новая строка}, {путь:строка: подсказка «вручную»})."""
    moves: dict[str, int] = {}
    cands: dict[str, list[int]] = {}
    shifts: dict[str, set[int]] = {}  # путь → сдвиги ссылок с одним кандидатом
    for key, text in todo.items():
        path, _, n = key.rpartition(":")
        cands[key] = anchors.find_moved(lines, path, text, int(n))
        if len(cands[key]) == 1:
            moves[key] = cands[key][0]
            shifts.setdefault(path, set()).add(moves[key] - int(n))
    for key, got in cands.items():
        path, _, n = key.rpartition(":")
        fit = [c for c in got if c - int(n) in shifts.get(path, set())]
        if key not in moves and len(got) > 1 and len(fit) == 1:
            moves[key] = fit[0]
    hints: dict[str, str] = {}
    clash = True
    while clash:  # снятый перенос оставляет ссылку на месте — её номер может быть целью другого переноса
        staying = stay | (set(todo) - set(moves))
        claims: dict[str, list[str]] = {}
        for key, to in moves.items():
            claims.setdefault(f"{key.rpartition(':')[0]}:{to}", []).append(key)
        clash = False
        for target, keys in claims.items():
            holders = sorted(set(keys) | ({target} & staying))
            if len(holders) < 2:
                continue
            clash = True
            for key in keys:
                del moves[key]
                others = ", ".join(h for h in holders if h != key)
                hints[key] = f"кандидат :{target.rpartition(':')[2]}, но этот номер и у {others}: какая где, не понять"
    for key, got in cands.items():
        if key not in moves and key not in hints:
            hints[key] = (f"кандидаты {', '.join(f':{c}' for c in got[:5])} — какой, по сдвигу не понять" if got
                          else "текста в файле нет — строку переписали, кандидатов нет")
    return moves, hints


def plan(m: MapModel) -> tuple[dict[str, int], list[str]]:
    """{"путь:старая": новая строка} и список «вручную» с подсказками."""
    changed = anchors.changed(m)
    todo = {key: was for _, key, was, _, _ in changed}
    stay = {k for keys in anchors.refs(m).values() for k in keys} - set(todo)
    moves, hints = solve(anchors.Lines(m.repo), todo, stay)
    manual = [f"{', '.join(where)} — {key}: «{was[:60]}» — {hints[key]}" for _, key, was, _, where in changed
              if key in hints]
    return moves, manual


def apply(m: MapModel, moves: dict[str, int]) -> int:
    """Переписать номера в «Код:» md и ключи в .anchors.json."""
    by_md: dict[str, list[tuple[int, str, str]]] = {}
    for folder, keys in anchors.refs(m).items():
        for key, where in keys.items():
            if key in moves:
                path = key.rpartition(":")[0]
                for w in where:
                    md, _, ln = w.rpartition(":")
                    by_md.setdefault(md, []).append((int(ln), key, f"{path}:{moves[key]}"))
    # Все замены строки — одним проходом по исходным номерам: иначе `:232`→`:234`, а потом та же
    # ссылка ещё раз `:234`→`:236` (цепочкой), если в строке есть и ссылка на :234.
    for md, items in by_md.items():
        p = m.root / md
        text = p.read_text(encoding="utf-8").split("\n")
        by_line: dict[int, dict[str, str]] = {}
        for ln, old, new in items:
            by_line.setdefault(ln, {})[old] = new
        for ln, swap in by_line.items():
            pattern = re.compile("`(" + "|".join(re.escape(o) for o in sorted(swap, key=len, reverse=True)) + ")`")
            text[ln - 1] = pattern.sub(lambda mt: f"`{swap[mt.group(1)]}`", text[ln - 1])
        p.write_text("\n".join(text), encoding="utf-8", newline="\n")
    for folder in anchors.refs(m):
        data = anchors.load(m.root, folder)
        if not any(old in data for old in moves):
            continue
        # Новые ключи — по исходным: перенос A→B не должен затереть запись B до её собственного переноса.
        moved = {(f"{k.rpartition(':')[0]}:{moves[k]}" if k in moves else k): v for k, v in data.items()}
        (m.root / folder / ".anchors.json").write_text(anchors.dump(moved), encoding="utf-8", newline="\n")
    return sum(len(v) for v in by_md.values())


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="relocate.py", description="Перенос съехавших ссылок (шапка файла — подробно).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else Path(__file__).resolve().parent.parent
    if not (root / "project" / "settings.yaml").is_file():
        print(f"ошибка: {root} — не корень карты", file=sys.stderr)
        return 2
    m = MapModel(root)
    moves, manual = plan(m)
    for k, v in sorted(moves.items()):
        print(f"{'перенёс бы' if a.dry_run else 'перенесено'}: {k} → :{v}")
    if moves and not a.dry_run:
        n = apply(m, moves)
        print(f"правлено ссылок в md: {n}; дальше — полная сборка build.py")
    for x in manual:
        print("вручную:", x)
    print(f"перенос ссылок: {len(moves)}, вручную: {len(manual)}")
    return 1 if manual else 0


if __name__ == "__main__":
    sys.exit(main())
