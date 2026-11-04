"""Перенос съехавших ссылок на код: код сдвинул строки — номера в «Код:» md переносятся на новые места.

Зачем. Ссылка `путь:строка` указывает на строку, которая после правки кода стоит ниже или выше. Найти её новое
место можно по запомненному тексту (ASIS/*/.anchors.json): если строка с тем же текстом в файле одна или стоит на
сдвиге соседней уже перенесённой ссылки — это та же строка. Остальное переносится руками, с подсказкой, где искать.

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


def plan(m: MapModel) -> tuple[dict[str, int], list[str]]:
    """{"путь:старая": новая строка} и список «вручную» с подсказками."""
    lines = anchors.Lines(m.repo)
    moves: dict[str, int] = {}
    manual: list[str] = []
    todo = [c for c in anchors.changed(m)]
    shifts: dict[str, list[int]] = {}  # путь → сдвиги уже перенесённых ссылок
    for _ in range(2):  # второй проход — по сдвигам соседей
        rest = []
        for folder, key, was, now, where in todo:
            path, _, n = key.rpartition(":")
            cands = anchors.find_moved(lines, path, was, int(n))
            pick = None
            if len(cands) == 1:
                pick = cands[0]
            elif cands:
                for d in shifts.get(path, []):
                    if int(n) + d in cands:
                        pick = int(n) + d
                        break
            if pick:
                moves[key] = pick
                shifts.setdefault(path, []).append(pick - int(n))
            else:
                rest.append((folder, key, was, now, where, cands))
        todo = [x[:5] for x in rest]
    for folder, key, was, now, where, cands in rest:
        hint = f"похожие строки: {', '.join(f':{c}' for c in cands[:5])}" if cands else "текста в файле нет — строку переписали"
        manual.append(f"{', '.join(where)} — {key}: «{was[:60]}» — {hint}")
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
