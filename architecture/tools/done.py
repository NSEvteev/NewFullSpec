"""«Сделано»: каждая правка «как будет» нашлась в свежем «как есть», удаляемое ушло из кода, живая проверка чиста.

Зачем. На закрытии «как есть» переписывается по коду, а «как будет» остаётся черновиком. Чтобы убедиться, что
изменение сделано целиком, каждую правку надо найти в свежем «как есть»: новое появилось, ушедшее ушло,
изменённое изменилось. Руками это сверяется долго и неполно; команда сверяет по номерам, якорям и id.

Кто зовёт. Шаг закрытия — перед очисткой; where.py --gate done; map.py clean-tobe — до очистки. Из корня репо:
  python <карта>/tools/done.py              всё изменение
  python <карта>/tools/done.py orders       только правки и задачи сервиса orders
  … --no-live    без живой проверки (проверочные карты); --no-git — без сверки с началом изменения
  … --root <карта>
Что сверяет (по видам):
  новое: раздел, шаг, этап, файл, поля    ключ, якорь, id или поле есть в свежем «как есть»
  новое: строки стрелок                   id стрелки есть в процессе
  уходит: раздел, строки, поля            ключа, якоря, id, поля нет; у метода нет и факта
  меняется: поле только в md (Значение, Единицы, Колонки, Ошибки, События)   совпадает с правкой точно
  меняется: текст, раздел, другие поля    раздел «как есть» изменился с начала изменения (коммит, в котором
                                          появилась обложка); смысл сверяет пишущий — без git «сверить вручную»
  меняется: строки стрелок                «кто → кому», «как», «вид» — точно; «что» и «внутри» — изменились
  тест                                    новый — есть в коде (def <имя> в папках тестов сервиса; у сервиса с фактами
                                          vitest — it/test/describe("<имя>") в *.test.ts(x)), уходящий — нет
  судьба «закрывает»                      проблемы нет в свежем «как есть»
  «Удаляется:» задач                      ни одного имени из списка нет в коде сервиса (целым словом)
  живая проверка                          live.py — 0 ошибок
Последствия для процессов — списком «показать дифф»: их сверяет пишущий.
Вывод — «сделано N из N» по видам и список несделанного с подсказкой.

Коды выхода: 0 — всё сделано; 1 — нет; 2 — ошибка вызова или изменения нет.

Чего не делает. Не правит «как есть» и «как будет»; не судит смысл текста — показывает, что сверить.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapmodel import (  # noqa: E402
    FIELD_RE,
    HEAD_RE,
    LINK_RE,
    Block,
    ChangeModel,
    Entity,
    MapModel,
    code_files,
    read_md,
)

MD_EXACT = ("Значение", "Единицы", "Колонки", "Ошибки", "События")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


class Done:
    def __init__(self, root: Path, svc: str | None, use_git: bool, live: bool):
        self.root = root.resolve()
        self.repo = self.root.parent
        self.svc = svc
        self.use_git = use_git
        self.live = live
        self.asis = MapModel(self.root)
        self.chg = ChangeModel(self.root, self.asis)
        if not self.chg.open:
            raise SystemExit("изменения нет: обложки TOBE/README.md нет")
        self.maprel = self.root.relative_to(self.repo).as_posix()
        self.start = self._start_commit() if use_git else None
        self.ok: Counter = Counter()
        self.total: Counter = Counter()
        self.left: list[str] = []
        self.review: list[str] = []

    def _start_commit(self) -> str | None:
        res = subprocess.run(
            ["git", "-C", str(self.repo), "log", "--diff-filter=A", "--format=%H", "--", f"{self.maprel}/TOBE/README.md"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        lines = res.stdout.split()
        # git log — от новых к старым; обложка появляется заново у каждого изменения: начало этого — последнее появление
        return lines[0] if res.returncode == 0 and lines else None

    def mark(self, kind: str, ok: bool, msg: str) -> None:
        self.total[kind] += 1
        if ok:
            self.ok[kind] += 1
        else:
            self.left.append(msg)

    # где что -------------------------------------------------------------------------------------

    def block_service(self, b: Block) -> str | None:
        parts = b.file.split("/")
        return parts[1] if len(parts) > 2 and parts[1] in self.asis.registry else None

    def covered(self, b: Block) -> list[Entity]:
        """Сущности мира «как будет», которые правка «новое» вносит целиком."""
        asis_rel = b.asis_file
        lm = self.chg.line_map.get(asis_rel, [])
        out = []
        for e in self.chg.world.entities.values():
            if e.file != asis_rel or not e.line or e.kind in ("документ",):
                continue
            cl = lm[e.line - 1] if 0 < e.line <= len(lm) else 0
            if b.line <= cl <= b.end:
                out.append(e)
        return out

    def asis_section(self, b: Block) -> Entity | None:
        """Раздел «как есть», к которому относится правка: по заголовку блока или ближайшему заголовку над ним."""
        head = b.head or (b.owner[-1] if b.owner else None)
        if head is None:  # сводка файла — блок до первого заголовка: сущность самого файла
            return next((e for e in self.asis.entities.values() if e.file == b.asis_file and e.line == 1), None)
        lv, title, anchor = head
        svc = self.block_service(b)
        for e in self.asis.entities.values():
            if e.file == b.asis_file and (e.anchor or e.title) == (anchor or title):
                return e
            if svc and e.service == svc and e.title == title and e.file.rsplit("/", 1)[-1] == b.asis_file.rsplit("/", 1)[-1]:
                return e
        return None

    def section_text(self, rel: str, key: str | None, at: str | None) -> str | None:
        """Текст раздела в файле «как есть» — сейчас или на коммите at. Раздел — по якорю или заголовку
        (так находятся и постоянные разделы без ключа, «Связанные процессы»); key None — сводка файла:
        всё до первого заголовка «## » (у процесса — с заголовком и полями шапки)."""
        if at:
            res = subprocess.run(["git", "-C", str(self.repo), "show", f"{at}:{self.maprel}/{rel}"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
            if res.returncode != 0:
                return None
            lines = res.stdout.split("\n")
        else:
            if not (self.root / rel).is_file():
                return None
            lines = read_md(self.root / rel)
        if key is None:
            end = next((j for j, x in enumerate(lines) if (h := HEAD_RE.match(x)) and len(h.group(1)) == 2), len(lines))
            return "\n".join(lines[:end])
        for i, x in enumerate(lines):
            hm = HEAD_RE.match(x)
            if hm and (hm.group(3) or hm.group(2).strip()) == key:
                lv = len(hm.group(1))
                end = next((j for j in range(i + 1, len(lines)) if (h := HEAD_RE.match(lines[j])) and len(h.group(1)) <= lv), len(lines))
                return "\n".join(lines[i:end])
        return None

    @staticmethod
    def block_key(b: Block) -> str | None:
        """Ключ раздела правки для section_text: якорь или заголовок; None — сводка файла."""
        head = b.head or (b.owner[-1] if b.owner else None)
        return None if head is None else (head[2] or head[1])

    def text_changed(self, b: Block) -> tuple[bool, str]:
        """Раздел правки есть в «как есть» и изменился с начала изменения; второе — где он (для сверки глазами)."""
        key = self.block_key(b)
        was = self.section_text(b.asis_file, key, self.start)
        now = self.section_text(b.asis_file, key, None)
        return now is not None and was != now, b.asis_file

    # проверки ------------------------------------------------------------------------------------

    def check_block(self, b: Block) -> None:
        if self.svc and self.block_service(b) != self.svc:
            return
        name = f"{b.number} ({b.kind}, {b.what})"
        if b.what == "строки":
            self.check_rows(b, name)
            return
        if b.kind == "новое":
            if b.what in ("раздел", "этап", "файл"):
                ents = self.covered(b)
                missing = [e.addr for e in ents if not self.asis.get(e.service, e.addr)]
                self.mark("новое", bool(ents) and not missing,
                          f"{name}: в свежем «как есть» нет {', '.join(missing) or 'раздела'}")
            elif not b.fields and self.start:
                # новый текст без полей (абзац, пункт «Связанных процессов») — раздел есть и изменился
                changed, where = self.text_changed(b)
                self.mark("новое", changed, f"{name}: раздел в {where} не менялся с начала изменения")
                if changed:
                    self.review.append(f"{name}: смысл сверить — {where}")
            else:
                e = self.asis_section(b)
                miss = [f for f in b.fields if not (e and f in e.fields)]
                self.mark("новое", e is not None and not miss, f"{name}: в «как есть» нет полей {', '.join(miss) or b.fields}")
            return
        if b.kind == "уходит":
            if b.what in ("раздел", "этап"):
                e = self.asis_section(b)
                self.mark("уходит", e is None, f"{name}: раздел «{b.head[1] if b.head else ''}» ещё есть в «как есть»")
            else:
                e = self.asis_section(b)
                still = [f for f in b.fields if e and f in e.fields]
                self.mark("уходит", not still, f"{name}: в «как есть» ещё есть поля {', '.join(still)}")
            return
        # меняется
        e = self.asis_section(b)
        if e is None and self.section_text(b.asis_file, self.block_key(b), None) is None:
            self.mark("меняется", False, f"{name}: раздела нет в свежем «как есть»")
            return
        exact = [f for f in b.fields if f in MD_EXACT]
        if exact and e is not None:
            want = {}
            cur = None
            for line in b.body:
                fm = FIELD_RE.match(line.strip())
                if fm:
                    cur = fm.group(1)
                    want[cur] = [fm.group(2) or ""]
                elif cur and line.strip().startswith("- "):
                    want[cur].append(line.strip()[2:])
            bad = [f for f in exact if norm(" ".join([e.fields[f].value] + e.fields[f].items)) != norm(" ".join(want.get(f, [])))
                   if f in e.fields] + [f for f in exact if f not in e.fields]
            # одна правка — одна отметка: точные поля не сошлись — не сделана; сошлись и других нет — сделана;
            # есть ещё текстовые поля — решает сверка текста ниже
            if bad or len(exact) == len(b.fields):
                self.mark("меняется", not bad, f"{name}: поля {', '.join(bad)} в «как есть» не такие, как в правке")
                return
        where = f"{e.file}:{e.line}" if e is not None else b.asis_file
        if not self.start:
            self.total["меняется"] += 1
            self.ok["меняется"] += 1
            self.review.append(f"{name}: сверить вручную — {where} (без git начала изменения не узнать)")
            return
        key = self.block_key(b)
        was = self.section_text(b.asis_file, key, self.start)
        now = self.section_text(b.asis_file, key, None)
        # раздела под этим путём и заголовком в начале не было, а сейчас есть — его переименовали (сервис, ключ): изменён
        self.mark("меняется", now is not None and was != now,
                  f"{name}: раздел {where} не менялся с начала изменения")
        if now is not None and was != now:
            self.review.append(f"{name}: смысл сверить — {where}" + (" (в начале — под другим именем)" if was is None else ""))

    def check_rows(self, b: Block, name: str) -> None:
        rows = [r for r in b.body if r.lstrip().startswith("|") and not re.match(r"^\|?\s*:?-{3,}", r.strip())]
        if not b.asis_file.startswith("ASIS/_processes/"):  # не стрелки (правила прокси и т. п.) — строки целиком
            now = {x.strip() for x in read_md(self.root / b.asis_file)} if (self.root / b.asis_file).is_file() else set()
            for r in rows:
                there = r.strip() in now
                self.mark(b.kind, there if b.kind != "уходит" else not there,
                          f"{name}: строка «{r.strip()[:60]}» — в {b.asis_file} {'нет' if b.kind != 'уходит' else 'ещё есть'}")
            return
        proc = Path(b.asis_file).stem
        arrows = {a.id: a for a in self.asis.arrows.get(proc, [])}
        head = ["id", "кто → кому", "что", "как", "вид", "внутри"]
        for r in rows:
            cells = [c.strip() for c in r.strip().strip("|").split("|")]
            row = dict(zip(head, cells))
            aid = row.get("id", "")
            a = arrows.get(aid)
            if b.kind == "новое":
                self.mark("новое", a is not None, f"{name}: стрелки {aid} нет в процессе {proc}")
            elif b.kind == "уходит":
                self.mark("уходит", a is None, f"{name}: стрелка {aid} ещё есть в процессе {proc}")
            else:
                same = a is not None and f"{a.sender} → {a.receiver}" == norm(row.get("кто → кому", "")) \
                    and norm(a.how) == norm(row.get("как", "")) and a.kind == row.get("вид", "")
                self.mark("меняется", same, f"{name}: стрелка {aid} — «кто → кому», «как» или «вид» не как в правке")

    def check_tests(self) -> None:
        for tid, t in self.chg.tests.items():
            svc = t.get("service")
            if self.svc and svc != self.svc:
                continue
            name = t.get("Тест") or ""
            kind = str(t.get("Вид") or "")
            if t.get("Набор") == "проверка вживую":
                continue
            if not name:  # имя нового теста дописывает блок, когда тест написан
                self.mark("тест", False, f"{tid}: у теста нет имени в «Тест:» — его дописывает блок")
                continue
            info = self.asis.registry.get(svc, {})
            dirs = [self.repo / info.get("root", "") / d for d in info.get("tests") or []]
            files = [p.read_text(encoding="utf-8", errors="replace") for d in dirs if d.is_dir() for p in d.rglob("*.py")]

            def has(one: str) -> bool:
                if any(re.search(rf"\bdef {re.escape(one)}\b", text) for text in files):
                    return True
                return "vitest" in (info.get("facts") or []) and self._vitest_has(self.repo / info.get("root", ""), one)

            # «Тест:» — одно имя или несколько через « · » (тест правки — несколько функций)
            names = [n.strip() for n in name.split(" · ") if n.strip()]
            if kind == "уходит":
                still = [n for n in names if has(n)]
                self.mark("тест", not still, f"{tid}: тест {', '.join(still)} ещё есть в коде")
            else:
                missing = [n for n in names if not has(n)]
                self.mark("тест", not missing, f"{tid}: теста {', '.join(missing)} нет в коде ({svc})")

    @staticmethod
    def _vitest_has(root: Path, name: str) -> bool:
        """Тест интерфейса: имя — строкой в it(…), test(…) или describe(…) файлов *.test.ts(x) вне node_modules."""
        pattern = re.compile(rf"\b(?:it|test|describe)\(\s*([\"'`]){re.escape(name)}\1")
        for p in root.rglob("*.test.ts*"):
            if "node_modules" in p.parts or p.suffix not in (".ts", ".tsx"):
                continue
            if pattern.search(p.read_text(encoding="utf-8", errors="replace")):
                return True
        return False

    def check_fates(self) -> None:
        for line in self.chg.fates:
            if "закрывает" not in line:
                continue
            for raw in LINK_RE.findall(line.split("закрывает")[0]):
                svc, _, key = raw.partition(": ")
                if not key.startswith("p-") or (self.svc and svc != self.svc):
                    continue
                self.mark("судьба", self.asis.get(svc, key) is None, f"{raw}: проблема ещё есть в «как есть»")

    def check_removed(self) -> None:
        for kid, t in self.chg.tasks.items():
            svc = t.get("service")
            gone = t.get("Удаляется")
            if not gone or (self.svc and svc != self.svc):
                continue
            items = gone if isinstance(gone, list) else [gone]
            names = [n for x in items for n in re.findall(r"`([^`]+)`", x)]
            info = self.asis.registry.get(svc)
            if info:
                files = code_files(self.repo / info.get("root", ""))
            else:  # ушедший сервис: записи реестра и папки нет — хвост искать в коде вне живых сервисов и вне карты
                alive = [(self.repo / r["root"]).resolve() for r in self.asis.registry.values() if r.get("root")]
                files = [(p, text) for p, text in code_files(self.repo)
                         if p.relative_to(self.repo).parts[0] != "architecture"
                         and not any(p.resolve().is_relative_to(a) for a in alive)]
            for n in names:
                rx = re.compile(rf"\b{re.escape(n)}\b")
                hit = next((p for p, text in files if rx.search(text)), None)
                self.mark("удаляется", hit is None, f"{kid}: «{n}» ещё есть в коде — {hit.relative_to(self.repo).as_posix() if hit else ''}")

    def check_live(self) -> None:
        if not self.live:
            return
        args = [sys.executable, str(Path(__file__).resolve().parent / "live.py"), "--root", str(self.root)]
        if self.svc:
            args += ["--service", self.svc]
        res = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
        lines = res.stdout.strip().splitlines()
        errs = [x.removeprefix("ошибка:").strip() for x in lines if x.startswith("ошибка")]
        # сами ошибки, каждая строкой, а не их число: иначе, чтобы их увидеть, нужен ещё один прогон live.py
        self.total["живая проверка"] += 1
        if res.returncode == 0:
            self.ok["живая проверка"] += 1
        else:
            self.left += [f"живая проверка — {e}" for e in errs] or [(lines or ["live.py: ?"])[-1]]

    def run(self) -> list[str]:
        for b in self.chg.blocks:
            self.check_block(b)
        self.check_tests()
        self.check_fates()
        self.check_removed()
        self.check_live()
        out = []
        for kind in self.total:
            out.append(f"{kind}: {self.ok[kind]} из {self.total[kind]}")
        out += [f"не сделано: {x}" for x in self.left]
        out += [f"сверить: {x}" for x in self.review]
        out += [f"показать дифф: {x}" for x in self.chg.consequences] if not self.svc else []
        n, t = sum(self.ok.values()), sum(self.total.values())
        out.append(f"сделано {n} из {t}")
        return out


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="done.py", description="Сделано ли изменение (шапка файла — подробно).")
    ap.add_argument("service", nargs="?")
    ap.add_argument("--no-live", action="store_true")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--root")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else Path(__file__).resolve().parent.parent
    if not (root / "project" / "settings.yaml").is_file():
        print(f"ошибка: {root} — не корень карты", file=sys.stderr)
        return 2
    try:
        d = Done(root, a.service, not a.no_git, not a.no_live)
    except SystemExit as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2
    out = d.run()
    print("\n".join(out))
    return 0 if not d.left else 1


if __name__ == "__main__":
    sys.exit(main())
