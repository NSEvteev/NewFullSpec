"""Проверки «как будет» (№25): правки, копии, решения, задачи и блоки, судьбы, последствия, доска, мир «как будет».

Зачем. Описание изменения показывают человеку на «да», а по «да» пишут код. Дыра в описании — правка без задачи,
задача вне блока, правка «решено» на предложенном решении, копия, разошедшаяся с «как есть», — всплывёт посреди
кода. Проверки ловят такие дыры до показа: ворота ready открываются, только когда здесь нет ошибок.

Кто зовёт. build.py при сборке, если изменение открыто; where.py --gate ready; тесты tools/tests/test_checks.py.
Отдельно: python <карта>/tools/tobe_checks.py [--root <карта>] — сообщения; код выхода 1, если есть ошибки.
Что читает. Модель «как есть» и изменения (mapmodel.py: MapModel, ChangeModel), код по «Удаляется:». Ничего не пишет.

Номера — как в списке проверок «как будет»:
  25.1  правка: вид, номер (уникален), статус из списка, «Почему:» — ловит модель изменения; не пустая
  25.2  копия: вне блоков совпадает с «как есть» (иначе — map.py sync); у «меняется» и «уходит» раздел есть в
        «как есть», у «новое» — нет (кроме «вместо»)
  25.3  правки не спорят: одно поле одного раздела — в одной правке
  25.4  статус правки не сильнее решений, на которые она ссылается в «Почему:»
  25.5  решение того, кто решает (пункт требований с якорем d-…, без пометки), — с его словами «…»; ссылки
        [[d-…]] ведут в существующее; обложка и набор требований разбираются (ошибки модели изменения)
  25.6  задача — ровно в одном блоке; задача из «После:» — не в более позднем блоке; «После:» блока — только выше
  25.7  правка «решено» в README, справочнике (кроме проблем), срезе, own.md — хотя бы в одной задаче; тест проверяет
        хотя бы одну правку; задача делает правдой хотя бы одну правку
  25.8  «Удаляется:»: пока задача не сделана — всё из списка есть в коде; после — ничего нет
  25.9  у высокой проблемы, на которую ссылается задетый метод или шаг, есть судьба на обложке
  25.10 процесс из «Последствий» есть в «как есть» и в «как будет» не задет
  25.11 в «Связях» появился или ушёл подраздел ### или #### — узел changes в TOBE/board.yaml; новый сервис — new
  25.12 проверки карты в мире «как будет»
  25.14 остатков старого формата нет (TOBE/.source/*.tobe.json, tools/tobe.yaml)
  25.15 обложки нет — в «как есть» нет «:::» и [[c-…]], [[d-…]], [[k-…]], [[t-…]]
  25.16 «Сделано:» у блока — только если блоки из его «После:» сделаны; в поле — дата и чем проверено
  25.17 (предупреждение) в «новое» и «меняется» нет слов истории («больше не», «теперь», «по-прежнему»…): правка
        пишется так, как будет стоять в «как есть», — закрытие переносит её командой, не переписывая
  25.18 (предупреждение) «Почему:» — только ссылки на решения ([[d-…]]) или «по рекомендации»: само «почему» —
        словами в тексте правки, где оно и останется после переноса
  25.19 у правок сделанных задач «Код:» есть там, где его требует «как есть» (map.py code --gaps): иначе ошибки
        всплывают только после переноса на закрытии

Чего не делает. Не судит смысл правок и не решает за человека; 25.13 (как есть поменялся под блоком) — часть 25.2.
"""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402
from mapmodel import BLOCK_OPEN_RE, HEAD_RE, Block, ChangeModel, MapModel, code_files, code_gaps, keys_in, read_md  # noqa: E402

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def outside(lines: list[str]) -> list[str]:
    """Строки копии вне блоков и без строки «Правка:» нового файла."""
    out, inside = [], False
    for line in lines:
        if line.startswith(":::"):
            inside = line.strip() != ":::"
            continue
        if not inside:
            out.append(line)
    return out


def as_was(lines: list[str]) -> list[str]:
    """Копия «как было»: «уходит» раскрыт (внутри — то, что было), «меняется» и «новое» — метки «\\0c-…»: на их месте
    в «как есть» стоит старое значение или ничего."""
    out: list[str] = []
    kind = None
    for line in lines:
        m = BLOCK_OPEN_RE.match(line)
        if m:
            kind = m.group(1)
            if kind != "уходит":
                out.append("\0" + m.group(2))
            continue
        if kind and line.strip() == ":::":
            kind = None
            continue
        if kind == "уходит" and not line.startswith("Почему:"):
            out.append(line)
        elif kind is None:
            out.append(line)
    return out


def diverged(copy_lines: list[str], asis_lines: list[str]) -> list[int]:
    """Номера строк «как есть» (с 1), где копия вне блоков с ним разошлась не на месте правки."""
    was = [x for x in as_was(copy_lines) if x.strip()]  # пустые строки знания не несут — без них
    nums = [i + 1 for i, x in enumerate(asis_lines) if x.strip()]
    asis = [x for x in asis_lines if x.strip()]
    bad = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, was, asis, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        at = nums[j1] if j1 < len(nums) else len(asis_lines)
        marks = [x for x in was[max(0, i1 - 1) : i2 + 1] if x.startswith("\0")]  # на месте правки или вплотную
        if not marks:  # расхождение без правки рядом
            bad.append(at)
        elif tag == "replace":
            plain = [x for x in was[i1:i2] if not x.startswith("\0")]
            if plain and not all(x in asis[j1:j2] for x in plain):
                bad.append(at)
    return bad


def head_in(lines: list[str], head: tuple) -> bool:
    lv, title, anchor = head
    for x in lines:
        m = HEAD_RE.match(x)
        if m and len(m.group(1)) == lv and (m.group(3) or m.group(2).strip()) == (anchor or title):
            return True
    return False


def run(asis: MapModel, chg: ChangeModel) -> checks.Report:
    r = checks.Report()
    if not chg.open:
        _after_close(asis, r)
        return r
    if (asis.root / "TOBE" / ".applied").is_file():
        return r  # закрытие перенесло «как будет» (map.py apply): дальше сверяет done.py, копии с «как есть» не сравнить
    statuses = asis.settings.get("statuses") or []
    rank = {s: i for i, s in enumerate(statuses)}
    root = asis.root
    for b in chg.blocks:
        _block(asis, chg, b, r, rank)
    _copies(chg, root, r)
    _conflicts(chg, r)
    _decisions(chg, r, statuses)
    _tasks_blocks(chg, r)
    _removed(asis, chg, r)
    _fates(asis, chg, r)
    _consequences(asis, chg, r)
    _board(chg, r)
    if chg.world:
        w = checks.run(chg.world, [(t, root / t) for t in chg.copies.values()])
        r.errors += [f"мир «как будет»: {e}" for e in chg.world.errors + w.errors]
    if (root / "TOBE" / ".source").is_dir() or (root / "tools" / "tobe.yaml").is_file():
        r.err("TOBE/.source/ или tools/tobe.yaml — остатки старого формата «как будет»: убрать")
    return r


HISTORY_RE = re.compile(r"(?i)(?<!\w)(больше не|теперь|по-прежнему|отныне|как раньше|как прежде|уже не)(?!\w)")
WHY_LINKS_RE = re.compile(r"^(?:\[\[d-[a-z0-9-]+\]\](?:\s*·\s*|\s*,\s*|\s+)?)+$|^по рекомендации$")


def _block(asis: MapModel, chg: ChangeModel, b: Block, r: checks.Report, rank: dict) -> None:
    """25.1 — не пустая; 25.4 — статус не сильнее решений; 25.17 — без слов истории; 25.18 — «Почему:» — ссылки."""
    if b.kind != "уходит":
        for line in b.body:
            m = HISTORY_RE.search(re.sub(r"`[^`]*`|\[\[[^\]]*\]\]", "", line))
            if m:
                r.warn(f"{b.file}:{b.line} — {b.number}: «{m.group(1)}» — слово истории; правка пишется так, как будет "
                       "стоять в «как есть» (STANDARD.md, 7.3)")
                break
    if b.why and not WHY_LINKS_RE.match(b.why.strip()):
        r.warn(f"{b.file}:{b.line} — {b.number}: в «Почему:» текст — «почему» пишется словами в тексте правки, "
               "в «Почему:» — только [[d-…]] или «по рекомендации» (STANDARD.md, 7.3)")
    decs = [k for k in keys_in(b.why) if k.startswith("d-")]
    for d in decs:
        if d not in chg.decisions:
            r.err(f"{b.file}:{b.line} — {b.number}: решения [[{d}]] в требованиях нет — якорь {{#{d}}} у пункта")
            continue
        ds = chg.decisions[d].get("Статус")
        if ds in rank and b.status in rank and rank[b.status] < rank[ds]:
            r.err(f"{b.file}:{b.line} — {b.number}: статус «{b.status}» сильнее решения {d} («{ds}»): ставь «{ds}»")
    if b.kind == "меняется" and b.what == "поля":
        p = asis.root / b.asis_file
        if p.is_file():
            lines = set(read_md(p))
            body = [x for x in b.body if x.strip()]
            # целыми строками, не подстрокой: укороченное поле («Участники: a» из «Участники: a · b») — правка, не пустая
            if body and all(x in lines for x in body):
                r.err(f"{b.file}:{b.line} — {b.number}: «меняется», а внутри то же, что в «как есть» — правка пустая")


def _copies(chg: ChangeModel, root: Path, r: checks.Report) -> None:
    """25.2 — копия вне блоков совпадает с «как есть»; места «меняется», «уходит», «новое»."""
    for asis_rel, tobe_rel in chg.copies.items():
        if asis_rel in chg.new_files or not (root / asis_rel).is_file():
            continue  # новый файл; ушедший целиком — сверять не с чем
        copy_lines = (root / tobe_rel).read_text(encoding="utf-8").split("\n")
        asis_lines = (root / asis_rel).read_text(encoding="utf-8").split("\n")
        bad = diverged(copy_lines, asis_lines)
        if bad:
            r.err(
                f"{tobe_rel} — вне блоков копия разошлась с {asis_rel} (строка {bad[0]}): «как есть» поменялся после копии или копию "
                f"правили мимо блока — map.py sync {asis_rel}, потом пересмотреть правки рядом"
            )
        for b in chg.blocks_in(asis_rel):
            if b.what not in ("раздел", "этап") or not b.head:
                continue
            exists = head_in(asis_lines, b.head)
            if b.kind in ("меняется", "уходит") and not exists:
                r.err(f"{b.file}:{b.line} — {b.number} «{b.kind}»: раздела «{b.head[1]}» нет в «как есть»")
            if b.kind == "новое" and exists and not b.instead:
                r.err(f"{b.file}:{b.line} — {b.number} «новое»: раздел «{b.head[1]}» уже есть в «как есть» — "
                      f"это «меняется» или «новое … · вместо …»")


def _conflicts(chg: ChangeModel, r: checks.Report) -> None:
    """25.3 — одно поле одного раздела — в одной правке."""
    seen: dict[tuple, str] = {}
    for b in chg.blocks:
        if b.what != "поля" or not b.owner:
            continue
        for f in b.fields:
            k = (b.file, b.owner[-1], f)
            if k in seen:
                r.err(f"{b.file}:{b.line} — поле «{f}:» правят две правки: {seen[k]} и {b.number}")
            seen[k] = b.number


def _decisions(chg: ChangeModel, r: checks.Report, statuses: list[str]) -> None:
    """25.5 — решение того, кто решает, — с его словами в тексте пункта требований: «<имя>[, дата…]: «…»» или
    «выбрал «<вариант>»». Просто кавычки не годятся: ими пишутся и надписи на экране."""
    top = statuses[0] if statuses else None
    name = re.escape(str((chg.asis.settings.get("decider") or {}).get("name") or ""))
    words = re.compile(rf"{name}[^«»]{{0,80}}«[^»]+»|выбрал[аи]? «[^»]+»" if name else r"выбрал[аи]? «[^»]+»")
    for k, d in chg.decisions.items():
        if d.get("Статус") == top and not words.search(" ".join(d.get("text", []))):
            r.err(f"{d['file']}:{d['line']} — {k} «{top}»: нужны его слова дословно — «{name.replace(chr(92), '')}, <дата>: «…»» "
                  f"или «выбрал «…»»: без них пункт не отличить от вывода пишущего")


def _tasks_blocks(chg: ChangeModel, r: checks.Report) -> None:
    """25.6, 25.7, 25.16 — задачи, тесты, блоки."""
    order = [w.get("anchor") for w in chg.work]
    where: dict[str, list[str]] = {}
    for w in chg.work:
        for k in keys_in(w.get("Задачи", [])):
            where.setdefault(k, []).append(w["anchor"])
        for a in keys_in(w.get("После", [])):
            if a not in order or order.index(a) >= order.index(w["anchor"]):
                r.err(f"TOBE/blocks.md — {w['anchor']}: «После: [[{a}]]» — блок должен стоять выше")
        done = w.get("Сделано")
        if done:
            if not DATE_RE.search(str(done)):
                r.err(f"TOBE/blocks.md — {w['anchor']}: в «Сделано:» нужна дата и чем проверено")
            for a in keys_in(w.get("После", [])):
                dep = next((x for x in chg.work if x.get("anchor") == a), None)
                if dep and not dep.get("Сделано"):
                    r.err(f"TOBE/blocks.md — {w['anchor']} сделан, а {a} из его «После:» — нет")
    for k, t in chg.tasks.items():
        bl = where.get(k, [])
        if len(bl) != 1:
            r.err(f"TOBE/{t['service']}/tasks.md:{t['line']} — задача {k} в блоках: {', '.join(bl) or 'ни в одном'} — нужно ровно в одном")
        for dep in keys_in(t.get("После", [])):
            if dep in where and bl and where[dep] and order.index(where[dep][0]) > order.index(bl[0]):
                r.err(f"TOBE/{t['service']}/tasks.md:{t['line']} — {k} после {dep}, а {dep} в более позднем блоке")
        if not keys_in(t.get("Правки", [])):
            r.err(f"TOBE/{t['service']}/tasks.md:{t['line']} — у задачи {k} нет «Правки:»")
    in_tasks = {c for t in chg.tasks.values() for c in keys_in(t.get("Правки", []))}
    weak = set((chg.asis.settings.get("statuses") or [])[2:])
    for b in chg.blocks:
        parts = b.file.split("/")
        svc_file = len(parts) > 2 and parts[1] != "_processes" and not b.file.endswith("problems.md")
        if svc_file and b.status not in weak and b.number not in in_tasks:
            r.err(f"{b.file}:{b.line} — правка {b.number} «{b.status}» не входит ни в одну задачу: кто сделает её правдой?")
    for k, t in chg.tests.items():
        if not keys_in(t.get("Проверяет", [])):
            r.err(f"TOBE/{t['service']}/tasks.md:{t['line']} — тест {k} ничего не проверяет: нет «Проверяет:»")
    done = {c for t in chg.tasks.values() if t.get("Сделано") for c in keys_in(t.get("Правки", []))}
    for gap in code_gaps(chg, done) if done else []:
        r.err(f"{gap} — задача сделана, а «как есть» требует «Код:»: map.py code")


def _removed(asis: MapModel, chg: ChangeModel, r: checks.Report) -> None:
    """25.8 — «Удаляется:» против кода: пока задача не сделана — есть в коде, после — нет."""
    for k, t in chg.tasks.items():
        gone = t.get("Удаляется")
        if not gone:
            continue
        items = gone if isinstance(gone, list) else [gone]
        names = [n for x in items for n in re.findall(r"`([^`]+)`", x)]
        texts = [text for _, text in code_files(asis.repo / asis.registry.get(t["service"], {}).get("root", ""))]
        for n in names:
            rx = re.compile(rf"\b{re.escape(n)}\b")
            present = any(rx.search(text) for text in texts)
            if t.get("Сделано") and present:
                r.err(f"TOBE/{t['service']}/tasks.md:{t['line']} — {k} сделана, а «{n}» ещё есть в коде")
            if not t.get("Сделано") and not present:
                r.err(f"TOBE/{t['service']}/tasks.md:{t['line']} — {k}: «{n}» из «Удаляется:» в коде нет — опечатка?")


def _touched(chg: ChangeModel) -> set[tuple[str | None, str]]:
    """Сущности «как есть», которые правят блоки: (сервис, адрес)."""
    out = set()
    for b in chg.blocks:
        head = b.head or (b.owner[-1] if b.owner else None)
        if not head:
            continue
        for e in chg.asis.entities.values():
            if e.file == b.asis_file and (e.anchor or e.title) == (head[2] or head[1]):
                out.add((e.service, e.addr))
    return out


def _fates(asis: MapModel, chg: ChangeModel, r: checks.Report) -> None:
    """25.9 — у высокой проблемы на задетом методе или шаге есть судьба."""
    fates = " ".join(chg.fates)
    for svc, addr in _touched(chg):
        for ln in asis.links:
            if ln.src != addr or not ln.key.startswith("p-") or asis._service_of_file(ln.src_file) != svc:
                continue
            p = asis.get(ln.service, ln.key)
            if p and "Важность" in p.fields and p.fields["Важность"].value == "высокая":
                if f"{ln.service}: {ln.key}" not in fates:
                    r.err(f"TOBE/README.md — высокая проблема [[{ln.service}: {ln.key}]] на задетом {addr}: "
                          f"нет судьбы в «Судьбы проблем»")


def _consequences(asis: MapModel, chg: ChangeModel, r: checks.Report) -> None:
    """25.10 — процессы из «Последствий» есть и не задеты."""
    touched = set(chg.processes())
    for line in chg.consequences:
        m = re.search(r"`([a-z0-9-]+)`", line)
        if not m:
            continue
        proc = m.group(1)
        if proc not in asis.processes:
            r.err(f"TOBE/README.md — в «Последствиях» процесс {proc}, а его нет в «как есть»")
        elif proc in touched:
            r.err(f"TOBE/README.md — процесс {proc} и в «Последствиях», и задет правками: одно из двух")


def _board(chg: ChangeModel, r: checks.Report) -> None:
    """25.11 — в «Связях» появился или ушёл подраздел ### или #### → узел changes; новый сервис → new.

    Правка текста или полей внутри подраздела линий доски не меняет — узла не требует (STANDARD.md, 7.1)."""
    board = chg.board or {}
    for b in chg.blocks:
        parts = b.file.split("/")
        if len(parts) != 3 or parts[2] != "README.md" or b.kind not in ("новое", "уходит") or b.what != "раздел":
            continue
        owners = [h[1] for h in b.owner]
        subs = [ln for ln in b.body if re.match(r"^#{3,4} ", ln)]
        if subs and ("Связи" in owners or any(ln.startswith("### → ") for ln in subs)):
            svc = parts[1]
            if (board.get(svc) or {}).get("status") not in ("changes", "new"):
                r.err(f"TOBE/board.yaml — в «Связях» {svc} {'появился' if b.kind == 'новое' else 'ушёл'} "
                      f"подраздел ({b.number}), а узла changes нет")
    for svc in chg.world.services if chg.world else []:
        if svc not in chg.asis.registry and (board.get(svc) or {}).get("status") != "new":
            r.err(f"TOBE/board.yaml — новый сервис {svc} без узла new")


def _after_close(asis: MapModel, r: checks.Report) -> None:
    """25.15 — обложки нет: в «как есть» не осталось пометок «как будет»."""
    for rel in asis.files:
        for i, line in enumerate((asis.root / rel).read_text(encoding="utf-8").split("\n"), 1):
            if line.startswith(":::") or re.search(r"\[\[[cdkt]-[a-z0-9-]+\]\]", line):
                r.err(f"{rel}:{i} — в «как есть» осталась пометка «как будет»: закрытие не доделано")
                break


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    root = Path(args[args.index("--root") + 1]) if "--root" in args else Path(__file__).resolve().parent.parent
    asis = MapModel(root)
    chg = ChangeModel(root, asis)
    r = run(asis, chg)
    for e in chg.errors + r.errors:
        print("ошибка:", e)
    for w in r.warnings:
        print("предупреждение:", w)
    print(f"«как будет»: ошибок {len(chg.errors) + len(r.errors)}")
    return 1 if chg.errors or r.errors else 0


if __name__ == "__main__":
    sys.exit(main())
