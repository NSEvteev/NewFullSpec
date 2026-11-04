"""Работа с файлами карты: копия «как будет», перенос нового в копию, «Код:» в правки, «уходит» блоком, перенос «как будет» в
«как есть», черновик закрытия, принять строку кода, удалить и переименовать md, очистить «как будет».

Зачем. Эти действия трогают сразу несколько мест (копию и «как есть», md и его страницу, md и ссылки на него,
«как будет» и доску проекта). Руками одно из мест забывается; команда делает их вместе и показывает, что задето.

Кто зовёт. Пишущий и шаги процесса (описание, закрытие). Из корня репо:
  python <карта>/tools/map.py tobe <md>        копия файла «как есть» в TOBE/ под тот же путь — начало правки;
                                               md — путь от корня карты: ASIS/orders/methods.md
  python <карта>/tools/map.py sync <md>        в копию «как будет» — новое из «как есть» вне блоков; блоки, чьё место
                                               в «как есть» поменялось, — списком «пересмотреть»
  python <карта>/tools/map.py code <копия>#<раздел> <путь:строка>…   «Код:» в раздел правки «новое» или
                                               «меняется» (или нового файла): строку «Код:» раздела заменить или
                                               дописать; раздел — якорь или заголовок; текст строк кода — в
                                               TOBE/.anchors.json. Зовёт блок, который написал этот код
  python <карта>/tools/map.py code --from <файл>   то же списком: строка — «<копия>#<раздел> → путь:строка · путь:строка»
                                               (без «→» раздел обрезается на первом пробеле — заголовок метода не найдётся);
                                               один проход: годные строки записаны, отказы — «нельзя: …» в конце
                                               (код 1), раздел с «Код:» вне правок — «пропущено: …»
  python <карта>/tools/map.py start <имя ветки> "<название>" <тема задачи бэклога> [--small] [--no-git]
                                               старт: ветка change/<имя>, обложка из шаблона, требования — задача бэклога
                                               (нет задачи — новая; в списке — «в работе»); --small — поле «Размер: маленькое»
  python <карта>/tools/map.py blank blocks | board | tasks <сервис>   заготовка документа описания из шаблонов
                                               .claude/skills/dev-describe/templates/; готовый файл не перезаписывает
  python <карта>/tools/map.py block-done <блок> --commits "<хэши>" --summary "<тесты с числами; вживую что и числа>"
                                               [--from <список Код:>] [--relocate] [--tests <файл «t-… = имя»>]
                                               блок готов: «Код:» правок, имена тестов, «Сделано:» у задач и блока,
                                               разделы без «Код:», проверка «как будет» (build.py --check)
  python <карта>/tools/map.py code --gaps [<блок>]   разделы правок без «Код:» там, где его требует «как есть»
                                               (ограничители — тоже); только правки задач блока
  python <карта>/tools/map.py code --relocate   ссылки «Код:» правок «как будет» — по запомненному тексту строки: блок
                                               переписал код прежнего — номер переходит на строку с тем же текстом;
                                               не нашлась — «вручную». Звать после переноса каждого блока
  python <карта>/tools/map.py gone <номер> <решения> <md>[#<раздел>[|<раздел>…]]   «уходит» блоком: нет копии —
                                               сделать её; разделы (якорь или заголовок, с подразделами) — подряд,
                                               одним блоком; без разделов — весь файл; решения — d-… через
                                               запятую, статус — самый слабый из них; пример:
                                               gone c-ord-get d-poll 'ASIS/orders/methods.md#GET /api/v1/orders'
  python <карта>/tools/map.py gone --from <файл>   то же списком: строка — «<номер> <решения> <md>[#раздел…]»;
                                               пустые строки и строки с # в начале пропускаются
  python <карта>/tools/map.py apply [--yes]    закрытие: копии «как будет» без пометок — поверх «как есть»; файлы
                                               процессов и срезы, ушедшие целиком, — удалить; папку сервиса с узлом
                                               gone в TOBE/board.yaml — целиком (запись реестра — руками); запомненные строки
                                               «Код:» правок — в .anchors.json «как есть». Только когда все блоки с
                                               «Сделано:» и вне правок копия совпадает с «как есть» (иначе — sync).
                                               Без --yes — список; дальше relocate.py, build.py, done.py
  python <карта>/tools/map.py draft <сервис>   черновик: копии «как будет» сервиса без пометок — в
                                               TOBE/.draft/<сервис>/ (проверки его не читают); файлы процессов —
                                               draft _processes
  python <карта>/tools/map.py accept <путь:строка>   принять намеренно изменённую строку кода: запомнить новый текст
  python <карта>/tools/map.py rm <md> [--yes]  удалить md и его страницу; показать ссылки, которые сломаются;
                                               путь TOBE/… — удалить копию «как будет», «как есть» не трогать
  python <карта>/tools/map.py mv <процесс> <новый ключ> [--yes]   переименовать процесс: файл, срезы всех участников,
                                               ссылки md на него; без --yes — только показать
  python <карта>/tools/map.py mv-service <сервис> <новое имя> [--also <старое>=<новое>]… [--yes]   переименовать
                                               сервис во всей карте: папки ASIS/ и TOBE/, все написания имени
                                               (strategy-service, strategy_service, STRATEGY_SERVICE, StrategyService…) в
                                               md, yaml, json карты — реестр, доска, факты, пути «Код:»; --also — пары, что
                                               из имени не выводятся (база); на закрытии — после apply; без --yes — список
  python <карта>/tools/map.py close [--rename <старое> <новое> [--also <старое>=<новое>]…]   закрытие одним
                                               проходом: apply, переименование сервиса, факты задетых сервисов без
                                               тестов, relocate, сверка переноса ссылок по диффу кода (номер по
                                               диффу ставит сам; переписанную строку — «вручную по диффу» со всеми
                                               md; один раз — отметка TOBE/.diffchecked, повтор только напоминает
                                               непоправленное), done.py — в ответ только то, что править руками;
                                               после правок — снова close
  python <карта>/tools/map.py close --finish   сверка зелёная → очистка «как будет» и одна полная сборка
  python <карта>/tools/map.py clean-tobe [--yes]   очистить «как будет»: без --yes — список удаляемого и что
                                               перейдёт на доску; с --yes — только при зелёном done.py: места новых
                                               узлов доски — в project/board.yaml, ушедшие узлы — убрать оттуда;
                                               файлы TOBE/ — удалить, папку TOBE/ оставить (.gitkeep);
                                               --no-live, --no-git — передать done.py (проверочные карты)
  … --root <карта>   другая карта
Что читает и пишет — по подкоманде: копии в TOBE/, md карты, project/board.yaml, ASIS/*/.anchors.json,
TOBE/.anchors.json (того же вида, что у «как есть»: строки «Код:» правок, запомненные блоком).

Коды выхода: 0 — сделано (или показано, что будет сделано); 1 — нельзя (есть что пересмотреть, done.py не
зелёный, файл уже есть); 2 — ошибка вызова.

Чего не делает. Страницы не собирает — после rm, mv, sync, apply нужна сборка build.py. Не коммитит. apply не
сверяет текст с кодом: смысл сверяли блок и ревью; что разошлось с кодом, покажут relocate.py, live.py и done.py.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchors  # noqa: E402
import backlog  # noqa: E402
import tobe_checks  # noqa: E402
from mapmodel import (  # noqa: E402
    BLOCK_OPEN_RE,
    HEAD_RE,
    NEW_FILE_RE,
    ChangeModel,
    MapModel,
    _is_slice,
    cover_decisions,
    block_span,
    code_gaps,
    parse_blocks,
    read_md,
    sections_in,
    world_lines,
)


APPLIED = ".applied"  # отметка в TOBE/: перенос «как будет» в «как есть» сделан
# Отметка в TOBE/: сверка по диффу сделана — {"base": коммит до изменения, "manual": [[md, раздел, ссылка, подсказка]]}
DIFFCHECKED = ".diffchecked"


class Fail(Exception):
    """Нельзя сделать: код выхода 1."""


def raw_rel(root: Path, arg: str) -> str:
    p = Path(arg)
    return p.resolve().relative_to(root.resolve()).as_posix() if p.is_absolute() else arg.replace("\\", "/")


def rel_md(root: Path, arg: str) -> str:
    rel = raw_rel(root, arg)
    if rel.startswith("TOBE/"):
        rel = "ASIS/" + rel[5:]
    return rel


def is_tobe(root: Path, arg: str) -> bool:
    return raw_rel(root, arg).startswith("TOBE/")


# ─── как будет ───────────────────────────────────────────────────────────────────────────────────


def tobe(root: Path, md: str) -> list[str]:
    src = root / md
    if not src.is_file():
        raise Fail(f"{md}: файла «как есть» нет — новый файл пишется в TOBE/ сразу, со строки «Правка: c-… · <статус>»")
    dst = root / "TOBE" / md.split("/", 1)[1]
    if dst.exists():
        raise Fail(f"{dst.relative_to(root).as_posix()}: копия уже есть")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return [f"копия: {dst.relative_to(root).as_posix()} — правки пиши блоками ::: на месте"]


def block_ranges(lines: list[str]) -> list[tuple[int, int, str]]:
    """Блоки правок копии: (строка «::: …», строка закрывающего «:::», номер правки)."""
    out, start = [], None
    for i, line in enumerate(lines):
        if start is None and BLOCK_OPEN_RE.match(line):
            start = i
        elif start is not None and line.strip() == ":::":
            out.append((start, i, lines[start].split()[2]))
            start = None
    return out


def section_span(lines: list[str], spec: str, rel: str) -> tuple[int, int]:
    """Раздел копии по якорю или заголовку — с подразделами: (строка заголовка, конец без пустых строк хвоста)."""
    hits = [(i, len(m.group(1))) for i, m in ((i, HEAD_RE.match(x)) for i, x in enumerate(lines))
            if m and spec in (m.group(3), m.group(2).strip())]
    if len(hits) != 1:
        raise Fail(f"{rel}: раздел «{spec}» {'не найден' if not hits else 'найден не один'} — якорь или заголовок точно")
    i, level = hits[0]
    j = i + 1
    while j < len(lines) and not lines[j].startswith(":::"):
        m = HEAD_RE.match(lines[j])
        if m and len(m.group(1)) <= level:
            break
        j += 1
    while j > i + 1 and not lines[j - 1].strip():
        j -= 1
    return i, j


def gone(root: Path, items: list[tuple[str, str, str]]) -> list[str]:
    """«Уходит» блоком: items — (номер правки, решения через запятую, <md>[#раздел[|раздел…]]). Нет копии — делает её;
    разделы одного вызова — подряд, одним блоком; без разделов — весь файл. Статус — самый слабый из решений."""
    order = (yaml.safe_load((root / "project" / "settings.yaml").read_text(encoding="utf-8")) or {}).get("statuses") or []
    decisions = {k: d["Статус"] for k, d in cover_decisions(root, order).items()}
    used: set[str] = set()
    for p in (root / "TOBE").rglob("*.md"):
        text = p.read_text(encoding="utf-8").split("\n")
        used |= {n for _, _, n in block_ranges(text)}
        if text and NEW_FILE_RE.match(text[0]):
            used.add(NEW_FILE_RE.match(text[0]).group(1))
    out = []
    for number, why, target in items:
        if not re.fullmatch(r"c-[a-z0-9-]+", number) or number in used:
            raise Fail(f"{number}: номер правки — c-<сервис или процесс>-<смысл>, не занятый в TOBE/")
        refs = [d.strip() for d in why.split(",") if d.strip()]
        missing = [d for d in refs if d not in decisions]
        if not refs or missing:
            raise Fail(f"{number}: нет в требованиях решений {', '.join(missing) or '(пусто)'} — «Почему:» ссылается на решения")
        status = max((decisions[d] for d in refs), key=lambda s: order.index(s) if s in order else len(order))
        md, _, rest = target.partition("#")
        rel = rel_md(root, md)
        copy = root / "TOBE" / rel.split("/", 1)[1]
        if not copy.is_file():
            out += tobe(root, rel)
        lines = copy.read_text(encoding="utf-8").split("\n")
        blocks = block_ranges(lines)
        specs = [s.strip() for s in rest.split("|") if s.strip()]
        if specs:
            spans = sorted(section_span(lines, s, rel) for s in specs)
            for (_, a), (b, _) in zip(spans, spans[1:]):
                if any(x.strip() for x in lines[a:b]):
                    raise Fail(f"{rel}: разделы {', '.join(specs)} — не подряд: по вызову на кусок")
            start, end = spans[0][0], spans[-1][1]
        else:
            if blocks or (lines and NEW_FILE_RE.match(lines[0])):
                raise Fail(f"{rel}: в копии уже есть правки — весь файл уходит только из чистой копии")
            start, end = 0, max((i + 1 for i, x in enumerate(lines) if x.strip()), default=0)
        clash = [n for a, b, n in blocks if a < end and start <= b]
        if clash:
            raise Fail(f"{rel}: строки {start + 1}–{end} задевают правку {', '.join(clash)}")
        lines[start:end] = [f"::: уходит {number} · {status}", *lines[start:end],
                            "Почему: " + " · ".join(f"[[{d}]]" for d in refs), ":::"]
        copy.write_text("\n".join(lines), encoding="utf-8")
        used.add(number)
        what = " · ".join(specs) if specs else "весь файл"
        out.append(f"уходит: {copy.relative_to(root).as_posix()}:{start + 1} — {number} · {status} — {what}")
    return out


def gone_items(text: str) -> list[tuple[str, str, str]]:
    """Строки списка для gone --from: «<номер> <решения> <md>[#раздел[|раздел…]]»; пустые и с # в начале — мимо."""
    out = []
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            parts = line.strip().split(maxsplit=2)
            if len(parts) != 3:
                raise Fail(f"строка списка «{line.strip()}» — нужно «<номер> <решения> <md>[#раздел…]»")
            out.append((parts[0], parts[1], parts[2]))
    return out


def split_copy(lines: list[str]) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Копия → строки вне блоков и блоки с местом: (сколько строк вне блоков стоит до блока, строки блока)."""
    outside: list[str] = []
    blocks: list[tuple[int, list[str]]] = []
    cur: list[str] | None = None
    for line in lines:
        if cur is None and BLOCK_OPEN_RE.match(line):
            cur = [line]
            continue
        if cur is not None:
            cur.append(line)
            if line.strip() == ":::":
                blocks.append((len(outside), cur))
                cur = None
            continue
        outside.append(line)
    return outside, blocks


def sync(root: Path, md: str) -> list[str]:
    copy = root / "TOBE" / md.split("/", 1)[1]
    if not copy.is_file():
        raise Fail(f"{md}: копии в TOBE/ нет")
    asis = (root / md).read_text(encoding="utf-8").split("\n")
    outside, blocks = split_copy(copy.read_text(encoding="utf-8").split("\n"))
    if outside == asis:
        return ["вне блоков копия совпадает с «как есть» — переносить нечего"]
    ops = difflib.SequenceMatcher(None, outside, asis, autojunk=False).get_opcodes()

    def moved(pos: int) -> tuple[int, bool]:
        for tag, i1, i2, j1, j2 in ops:
            if i1 <= pos < i2 or (pos == i2 == len(outside) and tag != "equal"):
                return (j1 + (pos - i1), False) if tag == "equal" else (j1, True)
            if pos == i1 == i2:
                return j1, tag != "equal"
        return len(asis), False

    placed: dict[int, list[list[str]]] = {}
    review = []
    for pos, block in blocks:
        new_pos, touched = moved(pos)
        near = any(tag != "equal" and i1 - 3 <= pos <= i2 + 3 for tag, i1, i2, _, _ in ops)
        if touched or near:
            review.append(BLOCK_OPEN_RE.match(block[0]).group(2))
        placed.setdefault(new_pos, []).append(block)
    out: list[str] = []
    for i in range(len(asis) + 1):
        for block in placed.get(i, []):
            out += block
        if i < len(asis):
            out.append(asis[i])
    copy.write_text("\n".join(out), encoding="utf-8", newline="\n")
    msg = [f"{copy.relative_to(root).as_posix()}: новое из «как есть» перенесено вне блоков"]
    if review:
        msg.append("пересмотреть — место в «как есть» поменялось рядом с правкой: " + ", ".join(review))
    return msg


def draft(root: Path, svc: str) -> list[str]:
    chg = ChangeModel(root)
    if not chg.open:
        raise Fail("изменения нет: обложки TOBE/README.md нет")
    out_dir = root / "TOBE" / ".draft" / svc
    n = 0
    for asis_rel, tobe_rel in chg.copies.items():
        if asis_rel.split("/")[1] != svc:
            continue
        lines = (root / tobe_rel).read_text(encoding="utf-8").split("\n")
        wl, _ = world_lines(lines)
        dst = out_dir / asis_rel.split("/", 2)[2]
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("\n".join(wl), encoding="utf-8", newline="\n")
        n += 1
    if not n:
        raise Fail(f"у {svc} нет файлов в «как будет»")
    return [f"черновик: {n} файлов в {out_dir.relative_to(root).as_posix()}/ — сверь с кодом и перепиши «как есть»"]


CODE_REF_RE = re.compile(r"^[^\s`]+:\d+$")
EMPTY_LINE = {  # пустой файл справочника — одна строка (STANDARD.md, раздел 3)
    "methods.md": "методов нет", "exports.md": "функций для подключения нет", "pages.md": "страниц нет",
    "commands.md": "команд нет", "storage.md": "хранилищ нет", "settings.md": "настроек нет",
    "problems.md": "проблем нет", "tests.md": "тестов нет",
}


def file_spans(rel: str, struct: list[str]) -> list[tuple[int, int]]:
    """Где в копии правки «новое» и «меняется» (номера с 0, конец не входит); новый файл — весь."""
    if struct and NEW_FILE_RE.match(struct[0]):
        return [(0, len(struct))]
    blocks, _ = parse_blocks(rel, struct)
    return [block_span(b, struct) for b in blocks if b.kind != "уходит" and b.end]


class Outside(Fail):
    """Раздел есть, но «Код:» стоит вне правок — это не отказ: такие ссылки переносит закрытие."""


def code(root: Path, items: list[tuple[str, list[str]]]) -> list[str]:
    """«Код:» в разделы правок «как будет»: item — (<копия>#<якорь или заголовок>, [путь:строка, …]). Строка
    «Код:» раздела заменяется или дописывается последней; текст строк кода запоминается в TOBE/.anchors.json —
    по нему relocate.py после map.py apply и map.py code --relocate найдут ссылки, которые сдвинули следующие
    блоки. Один проход: годные строки списка записываются, отказы — строками «нельзя: …» в конце; раздел, где
    «Код:» вне правок, — «пропущено: …» (не отказ)."""
    lines = anchors.Lines(root.parent)
    remembered = anchors.load(root, "TOBE")
    out, skipped, refused = [], [], []
    for target, refs in items:
        try:
            out.append(_code_one(root, lines, remembered, target, refs))
        except Outside as e:
            skipped.append(f"пропущено: {target}: {e}")
        except Fail as e:
            refused.append(f"нельзя: {target}: {e}")
    (root / "TOBE" / ".anchors.json").write_text(anchors.dump(remembered), encoding="utf-8", newline="\n")
    return out + skipped + refused


def _code_one(root: Path, lines: anchors.Lines, remembered: dict[str, str], target: str, refs: list[str]) -> str:
    """Одна строка списка map.py code: «Код:» в раздел правки; ошибка — Fail (Outside — «Код:» вне правок)."""
    md, _, sec = target.partition("#")
    md = md.replace("\\", "/")
    rel = "TOBE/" + (md.split("/", 1)[1] if md.startswith(("ASIS/", "TOBE/")) else md)
    p = root / rel
    if not p.is_file():
        raise Fail("копии «как будет» нет")
    if not sec or not refs:
        raise Fail("нужно <копия>#<якорь или заголовок> и хотя бы одна ссылка путь:строка")
    bad = [r for r in refs if not CODE_REF_RE.match(r) or not lines.text(r.rpartition(":")[0], int(r.rpartition(":")[2]))]
    if bad:
        raise Fail(f"строки кода нет или она пустая — {', '.join(bad)}")
    struct = read_md(p)
    raw = p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    hit = next(((i, j, title) for s, e in file_spans(rel, struct) for i, j, title, anchor in sections_in(struct, s, e)
                if sec in (anchor, title)), None)
    if hit is None:
        if any(sec in (anchor, title) for _, _, title, anchor in sections_in(struct, 0, len(struct))):
            raise Outside("«Код:» вне правок — перенесёт закрытие (relocate.py, map.py close)")
        raise Fail(f"раздела «{sec}» нет")
    i, j, title = hit
    new = "Код: " + " · ".join(f"`{r}`" for r in refs)
    k = next((x for x in range(i + 1, j) if raw[x].startswith("Код:")), None)
    if k is None:
        k = j
        while k - 1 > i and not raw[k - 1].strip():
            k -= 1
        raw.insert(k, new)
    else:
        raw[k] = new
    p.write_text("\n".join(raw), encoding="utf-8", newline="\n")
    for r in refs:
        path, _, n = r.rpartition(":")
        remembered[r] = anchors.stored(lines.text(path, int(n)) or "")
    return f"{rel}:{k + 1} — «{title}»: {new}"


def code_relocate(root: Path) -> list[str]:
    """Ссылки «Код:» правок «как будет» — по запомненному тексту (TOBE/.anchors.json): следующий блок переписал код
    прежнего, номер сдвинулся. Текст на месте совпадает с запомненным — ссылка верна; нет — та же строка в нынешнем
    файле, из нескольких ближайшая к прежнему номеру, запомненный текст переходит к новому номеру; не нашлась —
    «вручную». Только строки «Код:» внутри правок «новое» и «меняется» (вне правок — «как есть», его переносит
    закрытие). Повтор безопасен."""
    if not (root / "TOBE" / "README.md").is_file():
        raise Fail("изменения нет: обложки TOBE/README.md нет")
    lines = anchors.Lines(root.parent)
    remembered = anchors.load(root, "TOBE")
    moved, manual, files = [], [], 0
    for p in sorted((root / "TOBE").rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        struct = read_md(p)
        raw = p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
        dirty = False
        for s, e in file_spans(rel, struct):
            title = None
            for k in range(s, min(e, len(raw))):
                if raw[k].startswith("#"):
                    title = raw[k].lstrip("#").strip()
                if not raw[k].startswith("Код:"):
                    continue
                refs = CODE_LINE_REF_RE.findall(raw[k])
                want = []
                for path, n in refs:
                    key, num = f"{path}:{n}", int(n)
                    text = remembered.get(key)
                    if text is None or anchors.stored(lines.text(path, num) or "") == text:
                        want.append(key)
                        continue
                    code_lines = lines.get(path) or []
                    hits = [x + 1 for x, ln in enumerate(code_lines) if text and anchors.stored(ln.strip()) == text]
                    if not hits:
                        manual.append(f"вручную: {rel}:{k + 1} «{title}»: {key} «{text[:70]}» — такой строки в файле нет")
                        want.append(key)
                        continue
                    to = min(hits, key=lambda x: abs(x - num))
                    remembered[f"{path}:{to}"] = text
                    moved.append(f"перенесено: {rel}:{k + 1} «{title}»: {key} → :{to}")
                    want.append(f"{path}:{to}")
                if want != [f"{f}:{n}" for f, n in refs]:
                    it = iter(want)
                    raw[k] = CODE_LINE_REF_RE.sub(lambda _: f"`{next(it)}`", raw[k])
                    dirty = True
        if dirty:
            p.write_text("\n".join(raw), encoding="utf-8", newline="\n")
            files += 1
    if moved:
        (root / "TOBE" / ".anchors.json").write_text(anchors.dump(remembered), encoding="utf-8", newline="\n")
    return moved + manual + [f"перенос ссылок «как будет»: перенесено {len(moved)}, вручную {len(manual)}, "
                             f"файлов изменено {files}"]


def code_items(text: str) -> list[tuple[str, list[str]]]:
    """Список из файла: строка — «<копия>#<раздел> → путь:строка · путь:строка»; без «→» раздел — до первого
    пробела (якорь). Делит по последней «→»: в ссылках её нет, а в заголовке раздела бывает («### → orders»)."""
    items = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        target, _, rest = line.rpartition("→") if "→" in line else line.partition(" ")
        refs = [r.strip("`") for r in re.split(r"[\s·]+", rest) if r.strip("`")]
        items.append((target.strip(), refs))
    return items


def block_numbers(chg: ChangeModel, block: str) -> set[str]:
    """Номера правок задач блока: «Задачи:» блока → «Правки:» каждой задачи."""
    work = next((w for w in chg.work if w.get("anchor") == block), None)
    if work is None:
        raise Fail(f"блока {block} нет в TOBE/blocks.md")
    tasks = re.findall(r"\[\[(k-[a-z0-9-]+)\]\]", str(work.get("Задачи") or ""))
    return {c for k in tasks for c in re.findall(r"\[\[(c-[a-z0-9-]+)\]\]", str(chg.tasks.get(k, {}).get("Правки") or ""))}


def gaps(root: Path, block: str | None) -> list[str]:
    chg = ChangeModel(root)
    if not chg.open:
        raise Fail("изменения нет: обложки TOBE/README.md нет")
    out = code_gaps(chg, block_numbers(chg, block) if block else None)
    return out or ["у разделов правок «Код:» есть" + (f" (блок {block})" if block else "")]


def code_refs(lines: list[str]) -> list[str]:
    return [r for x in lines if x.startswith("Код:") for r in re.findall(r"`([^`\s]+?:\d+)`", x)]


def gone_nodes(root: Path) -> set[str]:
    """Узлы доски «как будет» со status gone — сервис уходит целиком: его папки в «как есть» не остаётся."""
    p = root / "TOBE" / "board.yaml"
    nodes = ((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("nodes") or {}) if p.is_file() else {}
    return {n for n, v in nodes.items() if (v or {}).get("status") == "gone"}


def apply(root: Path, yes: bool) -> list[str]:
    """«Как будет» → «как есть» механически: копии без пометок поверх файлов «как есть», ушедшие целиком файлы
    процессов и срезы удаляются, папка ушедшего сервиса (узел доски gone) — целиком, запомненные строки «Код:»
    правок — в .anchors.json «как есть»."""
    chg = ChangeModel(root)
    gone = gone_nodes(root)
    if not chg.open:
        raise Fail("изменения нет: обложки TOBE/README.md нет")
    if chg.errors:
        raise Fail(f"в «как будет» ошибок формата: {len(chg.errors)}; первая — {chg.errors[0]}")
    undone = [w["anchor"] for w in chg.work if w.get("anchor") and not w.get("Сделано")]  # «После блоков» — не блок
    if undone:
        raise Fail(f"блоки без «Сделано:»: {', '.join(undone)} — переносить рано")
    stale, empty, plan, already = [], [], [], 0
    for asis_rel, tobe_rel in sorted(chg.copies.items()):
        lines = (root / tobe_rel).read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
        wl, _ = world_lines(lines)
        name = asis_rel.rsplit("/", 1)[-1]
        if any(x.strip() for x in wl):
            want = wl
        elif asis_rel.startswith("ASIS/_processes/") or _is_slice(asis_rel[5:]) or asis_rel.split("/")[1] in gone:
            want = None
        elif name in EMPTY_LINE:
            want = [EMPTY_LINE[name], ""]
        else:
            empty.append(asis_rel)
            continue
        p = root / asis_rel
        asis = p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n") if p.is_file() else None
        if asis == want:  # уже перенесено (повтор после перерыва)
            already += 1
            continue
        if asis is not None and asis_rel not in chg.new_files and tobe_checks.diverged(lines, asis):
            stale.append(asis_rel)
            continue
        plan.append((asis_rel, want))
    if stale:
        raise Fail("вне правок копия разошлась с «как есть» — сначала map.py sync: " + ", ".join(stale))
    if empty:
        raise Fail("в мире «как будет» файл пуст, а строки пустого файла у него нет: " + ", ".join(empty))
    msg = [f"{'перенесу' if wl is not None else 'удалю'}: {rel}" for rel, wl in plan]
    gone_dirs = sorted(root / "ASIS" / s for s in gone if (root / "ASIS" / s).is_dir())
    msg += [f"удалю папку ушедшего сервиса: {d.relative_to(root).as_posix()}" for d in gone_dirs]
    msg += [f"уже перенесено файлов: {already}"] if already else []
    msg += [f"без «Код:»: {x}" for x in code_gaps(chg)]
    msg += [f"ссылка изменения в тексте — в «как есть» её быть не может (25.15), убрать после переноса: {rel}:{i} — {m}"
            for rel, wl in plan if wl for i, line in enumerate(wl, 1)
            for m in re.findall(r"\[\[(?:c|d|k|t)-[a-z0-9-]+\]\]", line)]
    if not yes:
        return msg + ["чтобы перенести — тот же вызов с --yes"]
    remembered = anchors.load(root, "TOBE")
    merged: dict[str, dict[str, str]] = {}
    clash = []
    for rel, wl in plan:
        p = root / rel
        if wl is None:
            p.unlink(missing_ok=True)
            p.with_suffix(".html").unlink(missing_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(wl), encoding="utf-8", newline="\n")
        folder = anchors.owner_dir(rel)
        data = merged.setdefault(folder, anchors.load(root, folder))
        for r in code_refs(wl):
            if r in remembered:
                if data.get(r, remembered[r]) != remembered[r]:
                    clash.append(f"{r} — было «{data[r]}», правка запомнила «{remembered[r]}»")
                data[r] = remembered[r]
    for folder, data in merged.items():
        (root / folder / ".anchors.json").write_text(anchors.dump(data), encoding="utf-8", newline="\n")
    for d in gone_dirs:  # остатки — факты, запомненные строки, страница; запись реестра убирает человек (шаг 3)
        shutil.rmtree(d)
    msg = [x.replace("перенесу", "перенесено", 1).replace("удалю", "удалено", 1) for x in msg]
    msg += [f"проверить: одна ссылка у старого и нового текста — {x}" for x in clash]
    # отметка «перенос сделан»: после правок находок «как есть» законно расходится с копиями — повторный close перенос
    # пропускает; очистка «как будет» удаляет отметку вместе с остальными файлами TOBE/
    (root / "TOBE" / APPLIED).write_text("перенос «как будет» в «как есть» сделан (map.py apply --yes)\n", encoding="utf-8")
    return msg + ["дальше: relocate.py → build.py → done.py; разделы без «Код:» — поставить в «как есть»"]


# ─── как есть ────────────────────────────────────────────────────────────────────────────────────


def accept(root: Path, ref: str) -> list[str]:
    m = MapModel(root)
    for folder, keys in anchors.refs(m).items():
        if ref in keys:
            path, _, n = ref.rpartition(":")
            now = anchors.Lines(m.repo).text(path, int(n))
            if now is None:
                raise Fail(f"{ref}: строки в коде нет")
            data = anchors.load(root, folder)
            was = data.get(ref)
            data[ref] = anchors.stored(now)
            (root / folder / ".anchors.json").write_text(anchors.dump(data), encoding="utf-8", newline="\n")
            return [f"{ref}: принято — было «{was}», теперь «{data[ref]}»"]
    raise Fail(f"{ref}: такой ссылки в «Код:» карты нет")


def incoming(m: MapModel, md: str) -> list[str]:
    """Ссылки других md на ключи этого md и md-ссылки на сам файл."""
    keys = {(e.service, e.addr) for e in m.entities.values() if e.file == md}
    out = [f"{ln.src_file}:{ln.src_line} — [[{ln.raw}]]" for ln in m.links
           if (ln.service, ln.key) in keys and ln.src_file != md]
    name = Path(md).name
    target = (m.root / md).resolve()
    for rel in m.files:
        if rel == md:
            continue
        for i, line in enumerate((m.root / rel).read_text(encoding="utf-8").split("\n"), 1):
            # ссылка md — от папки файла, где стоит: одноимённый файл в другой папке — не этот
            for link in re.findall(rf"\]\(((?:[^)]*/)?{re.escape(name)})(?:#[^)]*)?\)", line):
                if ((m.root / rel).parent / link).resolve() == target:
                    out.append(f"{rel}:{i} — ссылка md на {name}")
    return out


def rm_tobe(root: Path, rel: str, yes: bool) -> list[str]:
    """Удалить копию «как будет» — «как есть» не трогается."""
    p = root / rel
    if not p.is_file() or p.suffix != ".md":
        raise Fail(f"{rel}: копии «как будет» нет")
    if not yes:
        return [f"удалю копию «как будет»: {rel} («как есть» не трогаю)", "чтобы удалить — тот же вызов с --yes"]
    p.unlink()
    p.with_suffix(".html").unlink(missing_ok=True)
    return [f"удалено: {rel}; дальше — сборка build.py"]


def rm(root: Path, md: str, yes: bool) -> list[str]:
    m = MapModel(root)
    if md not in m.files:
        raise Fail(f"{md}: это не md карты")
    msg = [f"сломаются: {x}" for x in incoming(m, md)]
    page = root / md.replace(".md", ".html") if md.startswith("ASIS/_processes/") else None
    if not yes:
        return msg + [f"удалю: {md}" + (f", {page.relative_to(root).as_posix()}" if page and page.exists() else ""),
                      "чтобы удалить — тот же вызов с --yes"]
    (root / md).unlink()
    if page and page.exists():
        page.unlink()
    return msg + [f"удалено: {md}; дальше — поправить ссылки выше и собрать build.py"]


def mv(root: Path, old: str, new: str, yes: bool) -> list[str]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", new):
        raise Fail(f"ключ процесса — латиница, цифры, дефис: «{new}»")
    proc = root / "ASIS" / "_processes" / f"{old}.md"
    if not proc.is_file():
        raise Fail(f"процесса {old} нет")
    moves = [(proc, proc.with_name(f"{new}.md"))]
    moves += [(p, p.with_name(f"{new}.md")) for p in sorted((root / "ASIS").glob(f"*/processes/{old}.md"))]
    edits = []
    for p in sorted((root / "ASIS").rglob("*.md")):
        text = p.read_text(encoding="utf-8")
        new_text = re.sub(rf"(\]\((?:[^)]*/)?){re.escape(old)}\.md", rf"\g<1>{new}.md", text)
        if new_text != text:
            edits.append((p, new_text))
    msg = [f"переименую: {a.relative_to(root).as_posix()} → {b.name}" for a, b in moves]
    msg += [f"поправлю ссылки md: {p.relative_to(root).as_posix()}" for p, _ in edits]
    if not yes:
        return msg + ["адреса шагов <сервис>/" + old + "#… меняются на " + new + " — в «как будет» и тексте их поправить",
                      "чтобы сделать — тот же вызов с --yes"]
    for p, text in edits:
        p.write_text(text, encoding="utf-8", newline="\n")
    for a, b in moves:
        a.rename(b)
        html = a.with_suffix(".html")
        if html.exists():
            html.unlink()
    return msg + ["сделано; дальше — сборка build.py"]


def name_forms(old: str, new: str) -> list[tuple[str, str]]:
    """Написания имени сервиса — от длинных к коротким: «Strategy Service», «StrategyService», «STRATEGY_SERVICE»,
    «Strategy-service», «strategy-service», «strategy_service»."""
    o, n = old.split("-"), new.split("-")
    pairs = [
        (" ".join(w.capitalize() for w in o), " ".join(w.capitalize() for w in n)),
        ("".join(w.capitalize() for w in o), "".join(w.capitalize() for w in n)),
        ("_".join(o).upper(), "_".join(n).upper()),
        (old.capitalize(), new.capitalize()),
        (old, new),
        ("_".join(o), "_".join(n)),
    ]
    return [(a, b) for a, b in pairs if a != b]


def mv_service(root: Path, old: str, new: str, also: list[str], yes: bool) -> list[str]:
    """Переименовать сервис во всей карте: папки ASIS/ и TOBE/, все написания имени в md, yaml и json карты (реестр,
    доска, факты, запомненные строки, пути «Код:»); also — ещё пары «старое=новое» (имя базы и т. п.). Инструменты
    (tools/) и страницы html не трогает: страницы пересоберёт build.py."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", new):
        raise Fail(f"ключ сервиса — латиница, цифры, дефис: «{new}»")
    if not (root / "ASIS" / old).is_dir():
        raise Fail(f"сервиса {old} в ASIS/ нет")
    pairs = name_forms(old, new)
    for x in also:
        a, sep, b = x.partition("=")
        if not sep or not a or not b:
            raise Fail(f"--also ждёт «старое=новое»: {x}")
        pairs.insert(0, (a, b))
    moves = [(root / w / old, root / w / new) for w in ("ASIS", "TOBE") if (root / w / old).is_dir()]
    busy = [b for _, b in moves if b.exists()]
    if busy:
        raise Fail(f"папка уже есть: {', '.join(b.relative_to(root).as_posix() for b in busy)}")
    edits, total = [], 0
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if not p.is_file() or rel.startswith(("tools/", "_shared/")) or p.suffix not in (".md", ".yaml", ".yml", ".json", ".jsonl"):
            continue
        text = p.read_text(encoding="utf-8")
        new_text = text
        for a, b in pairs:
            total += new_text.count(a)
            new_text = new_text.replace(a, b)
        if new_text != text:
            edits.append((p, new_text))
    msg = [f"переименую: {a.relative_to(root).as_posix()} → {b.relative_to(root).as_posix()}" for a, b in moves]
    msg.append(f"замены имени: {total} в {len(edits)} файлах ({', '.join(a for a, _ in pairs)})")
    if not yes:
        return msg + ["чтобы сделать — тот же вызов с --yes"]
    for p, text in edits:
        p.write_text(text, encoding="utf-8", newline="\n")
    for a, b in moves:
        a.rename(b)
    return msg + ["сделано; дальше — extract.py <новое имя>, relocate.py, build.py"]


CODE_LINE_REF_RE = re.compile(r"`([^`\s]+?):(\d+)`")  # ссылки в строке «Код:»: (путь, номер)


def code_sections(text_lines: list[str]) -> dict[str | None, list[tuple[int, list[tuple[str, str]]]]]:
    """Раздел (строка заголовка) → строки «Код:» в нём: (номер строки md, ссылки (путь, номер))."""
    out: dict[str | None, list[tuple[int, list[tuple[str, str]]]]] = {}
    head = None
    for i, line in enumerate(text_lines):
        if line.startswith("#"):
            head = line
        elif line.startswith("Код:"):
            out.setdefault(head, []).append((i, CODE_LINE_REF_RE.findall(line)))
    return out


def diff_left(root: Path, mark: dict) -> list[str]:
    """Повтор close после сверки по диффу: ничего не сдвигает — номера в «как есть» уже нынешнего кода (сверены или
    поставлены руками), а прочитанные как номера до изменения они сдвинулись бы второй раз (однажды: 49 ложных
    «вручную» и ссылка CalcTabs.tsx:157 → :151). Напоминает «вручную» первого прохода, которые стоят где стояли."""
    left: dict[str, tuple[list[str], str]] = {}
    for rel, head, ref, hint in mark.get("manual", []):
        p = root / rel
        if not p.is_file():
            continue
        secs = code_sections(p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n"))
        if any(f"{f}:{n}" == ref for _, refs in secs.get(head, []) for f, n in refs):
            left.setdefault(ref, ([], hint))[0].append(f"{rel} {(head or '')[:40]}")
    out = [f"вручную по диффу: {k} — строку переписали, {hint}; где: {'; '.join(where)}"
           for k, (where, hint) in sorted(left.items())]
    return out + [f"по диффу: сверено прошлым close от {mark.get('base', '?')[:9]} (TOBE/{DIFFCHECKED}) — повтор не "
                  f"сдвигает; не поправлено вручную {len(left)} из {len({m[2] for m in mark.get('manual', [])})}"]


def merge_base(root: Path, repo: Path) -> str | None:
    """Код, по которому писан «как есть» до переноса: родитель squash-коммита первого PR с обложки («PR: #N»)."""
    cover = root / "TOBE" / "README.md"
    if not cover.is_file():
        return None
    prs = [n for line in cover.read_text(encoding="utf-8").splitlines() if line.startswith("PR:")
           for n in re.findall(r"#(\d+)", line)]
    for n in prs:
        res = subprocess.run(["git", "log", "-1", "--format=%H", "--fixed-strings", f"--grep=(#{n})"], cwd=repo,
                             capture_output=True, text=True, encoding="utf-8")
        if res.stdout.strip():
            return res.stdout.strip() + "^"
    return None


def diff_check(root: Path) -> list[str]:
    """Перенос ссылок «Код:» вне правок — по диффу кода. Перенос по запомненному тексту ошибается в двух случаях:
    строку переписали (не находит — «вручную») и номер старой ссылки совпал с номером новой (одна ссылка у старого
    и нового текста — старая остаётся на чужой строке, а живая проверка не видит: текст на месте совпадает с
    запомненным для новой). Здесь: раздел «как есть» до изменения (коммит до слияния PR) против раздела после
    переноса и relocate —
    у каждой ссылки старая строка по диффу кода от коммита до изменения переходит в новую; не совпало — номер по
    диффу; строку переписали — где на её месте новый код и все md с этой ссылкой; совпало — запомненный текст ключа
    по нынешней строке (снимает ложное «строка изменилась» у ключа, который правка запомнила с другим текстом).
    Разделы, где «Код:» стоит внутри блока правки, не сверяются: ссылки там писал блок, по другому коду.
    Сверка — один раз: отметка TOBE/.diffchecked с «вручную»; повтор — diff_left."""
    root = root.resolve()
    mark = root / "TOBE" / DIFFCHECKED
    if mark.is_file():
        return diff_left(root, json.loads(mark.read_text(encoding="utf-8")))
    repo = root.parent
    base = merge_base(root, repo)
    if base is None:
        return ["по диффу: коммит слияния PR с обложки не найден — вписать «PR: #N» на обложку и повторить close"]

    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                              errors="replace").stdout

    changed = set(git("diff", "--name-only", base).split())
    lines = anchors.Lines(repo)
    before: dict[str, list[str]] = {}
    maps: dict[str, tuple[dict[int, int], list[tuple[str, int, int, int, int]]]] = {}

    def mapping(path: str) -> tuple[dict[int, int], list[tuple[str, int, int, int, int]]]:
        """Строка кода до изменения → строка сейчас (у неизменных кусков) и куски диффа."""
        if path not in maps:
            before[path] = git("show", f"{base}:{path}").replace("\r\n", "\n").split("\n")
            ops = difflib.SequenceMatcher(None, before[path], lines.get(path) or [], autojunk=False).get_opcodes()
            maps[path] = ({i1 + k + 1: j1 + k + 1 for tag, i1, i2, j1, _ in ops if tag == "equal"
                           for k in range(i2 - i1)}, ops)
        return maps[path]

    def spot(ops: list[tuple[str, int, int, int, int]], n: int) -> str:
        """Где в нынешнем коде то, что заменило строку n."""
        for tag, i1, i2, j1, j2 in ops:
            if tag != "equal" and i1 < n <= i2:
                return f"на её месте строки :{j1 + 1}–{j2}" if j2 > j1 else f"строка удалена (рядом :{j1})"
        return "места не нашёл"

    skip: set[tuple[str, str | None]] = set()  # (md «как есть», раздел) — «Код:» внутри блока правки
    for asis_rel, tobe_rel in ChangeModel(root).copies.items():
        tl = (root / tobe_rel).read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
        ranges, head = block_ranges(tl), None
        for i, line in enumerate(tl):
            if line.startswith("#"):
                head = line
            elif line.startswith("Код:") and any(s < i < e for s, e, _ in ranges):
                skip.add((asis_rel, head))

    fixed: list[str] = []
    manual: dict[str, tuple[list[tuple[str, str]], str]] = {}  # ссылка → ((md, раздел)…, что на месте строки в коде)
    verified: dict[str, set[str]] = {}  # папка .anchors.json → ключи, подтверждённые диффом
    for p in sorted((root / "ASIS").rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        # «Как есть» — с коммита до изменения, а не HEAD: в HEAD уже лежат ссылки, которые изменение само перевело на
        # новый код (агент учёта блока), и сдвиг по диффу двинул бы их второй раз (однажды: −16 строк).
        old = git("show", f"{base}:{p.relative_to(repo).as_posix()}")
        if not old:
            continue
        new_lines = p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
        old_secs, new_secs, dirty = code_sections(old.replace("\r\n", "\n").split("\n")), code_sections(new_lines), False
        for head in old_secs.keys() & new_secs.keys():
            if (rel, head) in skip:
                continue
            # Кандидат на перенос — ссылка, которая стоит в разделе тем же путём и номером, что и до изменения: её
            # не трогали. Новые и нарочно переставленные пишущим не сверяются по позиции (однажды позиционное
            # сопоставление переставило поставленную ссылку на соседнюю) — их проверяет живая проверка.
            untouched = {(f, n) for _, a in old_secs[head] for f, n in a}
            for li, b in new_secs[head]:
                want = []
                for f1, n1 in b:
                    num, f0, n0 = n1, f1, n1
                    if (f1, n1) in untouched and f0 in changed:
                        eq, ops = mapping(f0)
                        to = eq.get(int(n0))
                        if to is not None and to != int(n1):
                            num = str(to)
                            fixed.append(f"по диффу: {rel} {head[:50]}: {f1}:{n1} → :{to}")
                        elif to is not None:
                            verified.setdefault(anchors.owner_dir(rel), set()).add(f"{f1}:{n1}")
                        elif 0 < int(n0) <= len(before[f0]) and lines.text(f1, int(n1)) != before[f0][int(n0) - 1].strip():
                            manual.setdefault(f"{f1}:{n1}", ([], spot(ops, int(n0))))[0].append((rel, head))
                    want.append(f"{f1}:{num}")
                if [f"{f}:{n}" for f, n in b] != want:
                    it = iter(want)
                    new_lines[li] = CODE_LINE_REF_RE.sub(lambda _: f"`{next(it)}`", new_lines[li])
                    dirty = True
        if dirty:
            p.write_text("\n".join(new_lines), encoding="utf-8", newline="\n")
    accepted = 0
    for folder, keys in verified.items():
        data, before_n = anchors.load(root, folder), accepted
        for key in keys:
            path, _, n = key.rpartition(":")
            now = lines.text(path, int(n))
            if key in data and now is not None and data[key] != anchors.stored(now):
                data[key] = anchors.stored(now)
                accepted += 1
        if accepted > before_n:
            (root / folder / ".anchors.json").write_text(anchors.dump(data), encoding="utf-8", newline="\n")
    mark.write_text(json.dumps({"base": base, "manual": [[rel, head, k, hint] for k, (where, hint) in manual.items()
                                                         for rel, head in where]}, ensure_ascii=False, indent=1),
                    encoding="utf-8", newline="\n")
    out = fixed + [f"вручную по диффу: {k} — строку переписали, {hint}; где: "
                   + "; ".join(f"{rel} {head[:40]}" for rel, head in where) for k, (where, hint) in sorted(manual.items())]
    return out + [f"по диффу от {base[:9]}: поправлено {len(fixed)}, вручную {len(manual)}, "
                  f"запомненный текст обновлён у {accepted}"]


SKILLS = Path(__file__).resolve().parents[2] / ".claude" / "skills"


def _template(step: str, name: str, values: dict[str, str]) -> str:
    """Шаблон шага без его комментария-подсказки, с подставленными значениями."""
    p = SKILLS / step / "templates" / name
    if not p.is_file():
        raise Fail(f"шаблона {p} нет")
    text = re.sub(r"\A<!--.*?-->\s*", "", p.read_text(encoding="utf-8"), flags=re.S)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def start(root: Path, name: str, title: str, theme: str, small: bool, use_git: bool) -> list[str]:
    """Старт изменения: ветка, обложка из шаблона, задача бэклога как требования. Решения и текст пишет сессия через Edit."""
    cover = root / "TOBE" / "README.md"
    if cover.is_file():
        raise Fail("обложка уже есть: идёт другое изменение (одно за раз)")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", theme):
        raise Fail("имя и тема — латиницей через дефис")
    branch = f"change/{name}"
    out = []
    if use_git:
        res = subprocess.run(["git", "switch", "-c", branch], cwd=root.parent, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        if res.returncode != 0:
            raise Fail(f"ветка {branch} не создана: {res.stderr.strip()[:200]}")
        out.append(f"ветка {branch}")
    try:
        paths, done = backlog.ensure(root.parent, theme, title)
        out += done + backlog.take(root.parent, theme, branch)
    except backlog.Fail as e:
        raise Fail(str(e)) from e
    req_link = " · ".join(f"[{p}](../../{p})" for p in paths)
    size = "Размер: маленькое\n" if small else ""
    text = _template("dev-start", "cover.md", {"название": title, "имя": name, "требования": req_link, "размер": size})
    cover.parent.mkdir(parents=True, exist_ok=True)
    cover.write_text(text, encoding="utf-8", newline="\n")
    out.append("обложка TOBE/README.md из шаблона: заполнить через Edit")
    return out


BLANKS = {"blocks": ("blocks.md", "TOBE/blocks.md"), "board": ("board.yaml", "TOBE/board.yaml")}


def blank(root: Path, what: str, service: str | None) -> list[str]:
    """Заготовка документа описания из шаблона: blocks, board, tasks <сервис>. Готовый файл не перезаписывает."""
    if what == "tasks":
        if not service:
            raise Fail("blank tasks ждёт сервис")
        name, rel = "tasks.md", f"TOBE/{service}/tasks.md"
    elif what in BLANKS:
        name, rel = BLANKS[what]
    else:
        raise Fail("blank: blocks, board или tasks <сервис>")
    p = root / rel
    if p.exists():
        raise Fail(f"{rel} уже есть")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_template("dev-describe", name, {}), encoding="utf-8", newline="\n")
    return [f"{rel} из шаблона: заполнить через Edit"]


def _section(lines: list[str], anchor: str) -> tuple[int, int] | None:
    """Раздел с якорем: строка заголовка и строка после конца раздела — до следующего заголовка того же или старшего уровня."""
    for i, line in enumerate(lines):
        if line.startswith("#") and line.rstrip().endswith("{#" + anchor + "}"):
            level = len(line) - len(line.lstrip("#"))
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("#") and len(lines[j]) - len(lines[j].lstrip("#")) <= level:
                    return i, j
            return i, len(lines)
    return None


def _add_last(lines: list[str], start: int, end: int, field: str) -> None:
    """Поле последней строкой раздела: перед пустыми строками, которыми раздел кончается."""
    at = end
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1
    lines.insert(at, field)


def block_done(root: Path, block: str, commits: str, summary: str, tests_src: str | None, code_src: str | None,
               relocate: bool) -> list[str]:
    """Блок готов: ссылки «Код:» его правок, имена новых тестов, «Сделано:» у задач и блока, проверка «как будет».
    Всё или ничего: задача или тест не найдены — ничего не записано, кроме ссылок «Код:», поставленных до этого."""
    tobe = root / "TOBE"
    blocks_p = tobe / "blocks.md"
    if not blocks_p.is_file():
        raise Fail("TOBE/blocks.md нет")
    if not commits.strip() or not summary.strip():
        raise Fail("нужны --commits и --summary: по ним через месяц должно быть понятно, чем доказано «готово»")
    blocks = blocks_p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    where = _section(blocks, block)
    if where is None:
        raise Fail(f"блока {block} нет в TOBE/blocks.md")
    body = blocks[where[0]:where[1]]
    if any(x.startswith("Сделано:") for x in body):
        raise Fail(f"у блока {block} «Сделано:» уже стоит")
    tasks = re.findall(r"\[\[(k-[a-z0-9-]+)\]\]", next((x for x in body if x.startswith("Задачи:")), ""))
    if not tasks:
        raise Fail(f"у блока {block} нет поля «Задачи:»")
    files = {p: p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n") for p in sorted(tobe.glob("*/tasks.md"))}
    names = {}
    if tests_src:
        for raw in Path(tests_src).read_text(encoding="utf-8").splitlines():
            if raw.strip():
                key, _, name = raw.partition("=")
                if not name.strip():
                    raise Fail(f"«{raw}» — нужно «t-… = имя теста»")
                names[key.strip()] = name.strip()
    found = {}
    for key in [*tasks, *names]:
        hit = next((p for p, ls in files.items() if _section(ls, key)), None)
        if hit is None:
            raise Fail(f"{key} нет ни в одном tasks.md")
        found[key] = hit
    out: list[str] = []
    if relocate:
        out += code_relocate(root)
    if code_src:
        out += code(root, code_items(Path(code_src).read_text(encoding="utf-8")))
        if any(x.startswith("нельзя:") for x in out):
            raise Fail("ссылки «Код:» не легли:\n" + "\n".join(x for x in out if x.startswith("нельзя:")))
    today = date.today().isoformat()
    for key, name in names.items():
        ls = files[found[key]]
        start, end = _section(ls, key)
        at = next((i for i in range(start, end) if ls[i].startswith("Тест:")), None)
        if at is not None:
            ls[at] = f"Тест: {name}"
        else:
            ls.insert(next((i for i in range(start, end) if ls[i].startswith("Проверяет:")), end), f"Тест: {name}")
    for key in tasks:
        ls = files[found[key]]
        start, end = _section(ls, key)
        if any(x.startswith("Сделано:") for x in ls[start:end]):
            out.append(f"пропущено: у {key} «Сделано:» уже стоит")
            continue
        _add_last(ls, start, end, f"Сделано: {today} · {commits.strip()}")
    _add_last(blocks, where[0], where[1], f"Сделано: {today} · коммиты {commits.strip()}; {summary.strip()}")
    for p, ls in files.items():
        p.write_text("\n".join(ls), encoding="utf-8", newline="\n")
    blocks_p.write_text("\n".join(blocks), encoding="utf-8", newline="\n")
    out.append(f"«Сделано:» — у блока {block} и задач: {', '.join(tasks)}" + (f"; тестов с именем: {len(names)}" if names else ""))
    left = gaps(root, block)
    out += left
    code_rc, checked = run_tool("build.py", "--check", "--root", str(root))
    out += [x for x in checked if x.startswith("ошибка")]
    out.append("проверка «как будет»: 0 ошибок" if code_rc == 0 else f"проверка «как будет»: код {code_rc} — ошибки выше")
    return out


def run_tool(name: str, *args: str) -> tuple[int, list[str]]:
    """Соседний инструмент карты: код выхода и строки вывода."""
    res = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / name), *args],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    return res.returncode, res.stdout.strip().splitlines()


def close(root: Path, rename: list[str], also: list[str], finish: bool) -> list[str]:
    """Закрытие одним проходом. Без --finish: «как будет» в «как есть» (apply), переименование сервиса (если задано),
    факты задетых сервисов без тестов (тесты прогнали блоки), перенос ссылок (relocate), сверка (done.py с живой
    проверкой) — в ответ только то, что требует руки. С --finish: сверка зелёная → очистка «как будет» и одна полная
    сборка. Каждый шаг разбирает карту сам; повтор безопасен: перенесённое apply пропускает."""
    r = ["--root", str(root)]
    if finish:
        code, out = run_tool("done.py", *r)
        if code != 0:
            raise Fail("сверка не зелёная — сначала правки:\n" + "\n".join(x for x in out if x.startswith("не сделано")))
        msg = [out[-1] if out else "done.py: ?"] + clean_tobe(root, True, [], done_ok=True)
        code, out = run_tool("build.py", *r)
        return msg + [x for x in out if x.startswith("ошибка")] + [out[-1] if out else "build.py: ?"]
    if (root / "TOBE" / APPLIED).is_file():
        msg = ["перенос уже сделан (TOBE/.applied) — пропущен"]
    else:
        msg = [x for x in apply(root, True) if not x.startswith(("перенесу", "дальше"))]
    if rename and (root / "ASIS" / rename[0]).is_dir():  # повтор после переименования — шаг пропускается
        msg += mv_service(root, rename[0], rename[1], also, True)[-2:-1]
    svcs = sorted(ChangeModel(root).services())
    for s in svcs:
        code, out = run_tool("extract.py", s, *r)
        if code != 0:
            msg.append(f"факты {s}: " + (out[-1] if out else "?"))
    msg.append(f"факты сняты: {', '.join(svcs)}")
    code, out = run_tool("relocate.py", *r)
    msg += [x for x in out if x.startswith(("вручную", "перенос ссылок"))]
    msg += diff_check(root)
    added = 0  # строки новых ссылок на код — до сверки: иначе живая проверка требует полной сборки, а она — после сверки
    for folder, (data, n_new, _) in anchors.remember(MapModel(root)).items():
        (root / folder / ".anchors.json").write_text(anchors.dump(data), encoding="utf-8", newline="\n")
        added += n_new
    msg.append(f"строк кода запомнено новых: {added}")
    code, out = run_tool("done.py", *r)
    review = [x for x in out if x.startswith("сверить")]
    msg += [x for x in out if x.startswith("не сделано")]
    msg.append(f"сверить смысл глазами — правок: {len(review)} (done.py, строки «сверить»)")
    msg.append((out[-1] if out else "done.py: ?") + ("" if code == 0 else " — правки выше, затем map.py close ещё раз"))
    return msg


def clean_tobe(root: Path, yes: bool, done_args: list[str], done_ok: bool = False) -> list[str]:
    tobe_dir = root / "TOBE"
    files = sorted(p for p in tobe_dir.rglob("*") if p.is_file() and p.name != ".gitkeep")
    if not files:
        return ["«как будет» пусто — чистить нечего"]
    if yes and not done_ok:  # список показывается всегда, очищается — только при зелёном done.py
        done = Path(__file__).resolve().parent / "done.py"
        res = subprocess.run([sys.executable, str(done), "--root", str(root), *done_args], capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            raise Fail("done.py не зелёный — после очистки сверять будет нечего: " +
                       ((res.stdout.strip().splitlines() or ["?"])[-1]))
    board_p = root / "project" / "board.yaml"
    tobe_board = (yaml.safe_load((tobe_dir / "board.yaml").read_text(encoding="utf-8")) or {}).get("nodes") or {} \
        if (tobe_dir / "board.yaml").is_file() else {}
    board_text = board_p.read_text(encoding="utf-8")
    msg = []
    for node, v in tobe_board.items():
        v = v or {}
        if v.get("status") == "new" and v.get("pos"):
            board_text = board_with_node(board_text, node, list(v["pos"]))
            msg.append(f"доска: {node} — место {list(v['pos'])} в project/board.yaml")
        if v.get("status") == "gone":
            board_text = re.sub(rf"^\s+{re.escape(node)}:.*\n", "", board_text, flags=re.M)
            msg.append(f"доска: {node} — убран из project/board.yaml")
    msg += [f"удалю: {p.relative_to(root).as_posix()}" for p in files]
    if not yes:
        return msg + ["чтобы очистить — тот же вызов с --yes (очистит, только если done.py зелёный)"]
    board_p.write_text(board_text, encoding="utf-8", newline="\n")
    for p in files:
        p.unlink()
    for d in sorted((p for p in tobe_dir.rglob("*") if p.is_dir()), key=lambda x: -len(x.parts)):
        if not any(d.iterdir()):
            d.rmdir()
    (tobe_dir / ".gitkeep").touch()
    return msg + ["«как будет» очищено: папка TOBE/ оставлена (в ней .gitkeep), опустевшие папки сервисов убраны; "
                  "дальше — сборка build.py и build.py --check"]


def board_with_node(text: str, node: str, pos: list) -> str:
    """Текст доски с новым узлом. В новом проекте доска — «nodes: {}»: дописанный под ней узел сломал бы YAML."""
    text = re.sub(r"^nodes:[ \t]*\{\}[ \t]*$", "nodes:", text, flags=re.M)
    return text.rstrip("\n") + f"\n  {node}: {pos}\n"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="map.py", description="Работа с файлами карты (шапка файла — подробно).")
    ap.add_argument("cmd", choices=["tobe", "sync", "draft", "code", "gone", "apply", "accept", "rm", "mv", "mv-service",
                                    "close", "clean-tobe", "block-done", "start", "blank"])
    ap.add_argument("--small", action="store_true", help="start: маленькая доработка — поле «Размер: маленькое»")
    ap.add_argument("--commits", default="", help="block-done: хэши коммитов блока")
    ap.add_argument("--summary", default="", help="block-done: тесты с числами; вживую что и числа")
    ap.add_argument("--tests", help="block-done: файл «t-… = имя теста» — строка на тест")
    ap.add_argument("--rename", nargs=2, default=[], metavar=("СТАРОЕ", "НОВОЕ"), help="close: переименовать сервис")
    ap.add_argument("--finish", action="store_true", help="close: очистить «как будет» и собрать карту")
    ap.add_argument("--also", action="append", default=[], help="mv-service: ещё пара «старое=новое» (имя базы и т. п.)")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--root")
    ap.add_argument("--from", dest="src", help="code, gone: список из файла — строка на правку")
    ap.add_argument("--gaps", action="store_true", help="code: разделы правок без «Код:» (аргумент — блок)")
    ap.add_argument("--relocate", action="store_true", help="code: ссылки «Код:» правок — по запомненному тексту")
    ap.add_argument("--no-live", action="store_true", help="clean-tobe: done.py без живой проверки (проверочные карты)")
    ap.add_argument("--no-git", action="store_true", help="clean-tobe: done.py без git (проверочные карты)")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else Path(__file__).resolve().parent.parent
    if not (root / "project" / "settings.yaml").is_file():
        print(f"ошибка: {root} — не корень карты", file=sys.stderr)
        return 2
    if a.cmd == "code":
        if not ((a.gaps and len(a.args) <= 1) or (a.relocate and not a.args) or (a.src and not a.args)
                or (not a.gaps and not a.relocate and not a.src and len(a.args) >= 2)):
            print("ошибка: code ждёт <копия>#<раздел> путь:строка…, --from <файл>, --gaps [блок] или --relocate",
                  file=sys.stderr)
            return 2
    elif a.cmd == "gone":
        if not ((a.src and not a.args) or (not a.src and len(a.args) == 3)):
            print("ошибка: gone ждёт <номер> <решения> <md>[#раздел[|раздел…]] или --from <файл>", file=sys.stderr)
            return 2
    elif a.cmd == "start":
        if len(a.args) != 3:
            print("ошибка: start ждёт <имя ветки> <название> <тема требований>", file=sys.stderr)
            return 2
    elif a.cmd == "blank":
        if len(a.args) not in (1, 2):
            print("ошибка: blank ждёт blocks, board или tasks <сервис>", file=sys.stderr)
            return 2
    else:
        need = {"tobe": 1, "sync": 1, "draft": 1, "apply": 0, "accept": 1, "rm": 1, "mv": 2, "mv-service": 2, "close": 0,
                "clean-tobe": 0, "block-done": 1}[a.cmd]
        if len(a.args) != need:
            print(f"ошибка: {a.cmd} ждёт аргументов: {need}", file=sys.stderr)
            return 2
    try:
        if a.cmd == "code" and a.gaps:
            out = gaps(root, a.args[0] if a.args else None)
        elif a.cmd == "code" and a.relocate:
            out = code_relocate(root)
        elif a.cmd == "code":
            items = code_items(Path(a.src).read_text(encoding="utf-8")) if a.src else [(a.args[0], a.args[1:])]
            out = code(root, items)
        elif a.cmd == "gone":
            out = gone(root, gone_items(Path(a.src).read_text(encoding="utf-8")) if a.src else [tuple(a.args)])
        elif a.cmd == "apply":
            out = apply(root, a.yes)
        elif a.cmd == "rm" and is_tobe(root, a.args[0]):
            out = rm_tobe(root, "TOBE/" + raw_rel(root, a.args[0]).split("/", 1)[1], a.yes)
        elif a.cmd == "tobe":
            out = tobe(root, rel_md(root, a.args[0]))
        elif a.cmd == "sync":
            out = sync(root, rel_md(root, a.args[0]))
        elif a.cmd == "draft":
            out = draft(root, a.args[0])
        elif a.cmd == "accept":
            out = accept(root, a.args[0].replace("\\", "/"))
        elif a.cmd == "rm":
            out = rm(root, rel_md(root, a.args[0]), a.yes)
        elif a.cmd == "mv":
            out = mv(root, a.args[0], a.args[1], a.yes)
        elif a.cmd == "mv-service":
            out = mv_service(root, a.args[0], a.args[1], a.also, a.yes)
        elif a.cmd == "close":
            out = close(root, a.rename, a.also, a.finish)
        elif a.cmd == "block-done":
            out = block_done(root, a.args[0], a.commits, a.summary, a.tests, a.src, a.relocate)
        elif a.cmd == "start":
            out = start(root, a.args[0], a.args[1], a.args[2], a.small, not a.no_git)
        elif a.cmd == "blank":
            out = blank(root, a.args[0], a.args[1] if len(a.args) > 1 else None)
        else:
            out = clean_tobe(root, a.yes, [x for x, on in (("--no-live", a.no_live), ("--no-git", a.no_git)) if on])
    except Fail as e:
        print(f"нельзя: {e}")
        return 1
    print("\n".join(out))
    if a.cmd == "code" and any(x.startswith("нельзя:") for x in out):
        return 1
    if a.cmd == "block-done" and out[-1] != "проверка «как будет»: 0 ошибок":
        return 1
    return 1 if a.cmd == "sync" and any(x.startswith("пересмотреть") for x in out) else 0


if __name__ == "__main__":
    sys.exit(main())
