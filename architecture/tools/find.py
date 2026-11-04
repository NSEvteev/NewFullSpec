"""Поиск по карте для Claude: что известно о ключе, шаге и связи, кто пишет и читает, кого задевает правка.

Зачем. Чтобы ответить «кто вызывает метод», «кто читает колонку», «кто участвует в процессе», не нужно открывать
страницы и md подряд: одна команда печатает то же, что генератор показывает на странице. Разбор и всё производное —
из mapmodel.py, теми же функциями, что у build.py, поэтому ответ и страница не расходятся. Человек ищет строкой поиска
в шапке страниц; это — поиск для Claude и агентов.

Кто зовёт. Claude и агенты — когда нужно найти знание в карте; скиллы процесса — на шагах, где спрашивают участников
и задетое. Из корня репо, из Bash (не `find` и не `where`: в Windows это свои команды); <карта> — папка карты:
  python <карта>/tools/find.py '<ключ>'                        раздел, факты, производное, все ссылки на ключ
  python <карта>/tools/find.py '<сервис>/<процесс>#<якорь>'    шаг среза; шаг своей работы — '<сервис>/own#<якорь>'
  python <карта>/tools/find.py '<сервис> → <кому>[: <ключ>]'   связь: поведение вызова, где принимают, кто зовёт
  python <карта>/tools/find.py --text <слова>                  где упоминаются все слова (без регистра, ё = е)
  python <карта>/tools/find.py --code <путь[:строка[-строка]]> …   какие описания опираются на этот код
  python <карта>/tools/find.py --code --diff <ветка>           то же по всем строкам `git diff <ветка>`
  python <карта>/tools/find.py --chain '<ключ>'                кого задевает правка ключа — деревом; у колонки под
                                                               методом, который её отдаёт, — только те, кто упоминает
                                                               её имя (остальные — числом; --all — все)
  python <карта>/tools/find.py --process <процесс>             участники, их срезы и шаги; ключом или названием
  python <карта>/tools/find.py --service <сервис>              что делает сервис, где участвует, связи, проблемы
  python <карта>/tools/find.py --list [вид] [сервис] [важность]   ключи списком: адрес · сервис · вид · «что»
  … --tobe          любой режим в мире «как будет» идущего изменения; ключом бывают и номера c-…, d-…, k-…, t-…, b1
  … --all           списки целиком: без него — до 30 строк
  … --root <карта>  другая карта (проверочная), а не та, в которой лежит скрипт
Ключ — в одинарных кавычках: в нём бывают пробелы, {}, «:» и «#». [[…]] вокруг снимается; «сервис:ключ» без пробела
понимается; ключ без имени сервиса ищется у всех сервисов. Стрелку связи можно набрать и как «->». Страница пишется
с именем сервиса ('web: /orders'): голый /orders Git Bash превращает в путь C:/Program Files/Git/orders — это
снимается. Адрес шага никогда не начинается с «#» — в оболочке это комментарий.
Виды для --list: метод, функция, страница, правило прокси, команда, таблица, колонка, файл данных, колонка файла,
папка, ключ Redis, память браузера, настройка, другая настройка, постоянная, фоновая работа, ограничитель, проблема,
набор тестов, связь, срез, шаг, процесс, этап, стрелка; с --tobe — ещё правка, решение, задача, тест, блок;
важность — высокая, средняя, низкая.

Что читает. Карту, в которой лежит: корень — папка над tools/ с project/settings.yaml. md, .facts.json и yaml — через
mapmodel.py; с --tobe — ещё TOBE/ (ChangeModel); с --diff — вывод git diff. Код не читает: --code сравнивает номера
строк в «Код:». Ничего не пишет.

Вывод. UTF-8 — и в трубу. Первая строка — итог: что нашлось. Пути — от корня репо, «путь:строка»; строка md — строка
заголовка раздела. Списки — до 30 строк, дальше «показано 30 из N — --all»; выдержка из текста — до 200 знаков.
Порядок — по реестру сервисов, по файлу, по строке. Предупреждения — в stderr.

Коды выхода: 0 — нашлось; 1 — не нашлось; 2 — ошибка ввода или карты.

Чего не делает. Не проверяет карту (это build.py), не ходит в сеть, не вынимает факты. Сдвинутый код по запомненным
строкам (.anchors.json) не узнаёт, пока их не пишет сборка: --code сравнивает номера строк.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapmodel import (  # noqa: E402
    FIELD_RE,
    HEAD_RE,
    KIND_RU,
    LINK_RE,
    Arrow,
    Block,
    ChangeModel,
    Entity,
    Link,
    MapModel,
    facts_settings,
    read_md,
    split_key,
    world_lines,
)
from tobe_checks import as_was  # noqa: E402

LIMIT = 30
EXCERPT = 200
SEVERITY = ("высокая", "средняя", "низкая")
ENTRY_KINDS = ("метод", "функция", "страница", "команда")
STORE_KINDS = (
    "таблица",
    "колонка",
    "файл данных",
    "колонка файла",
    "папка",
    "ключ Redis",
    "память браузера",
)
READ_KINDS = ("настройка", "другая настройка", "постоянная", "ограничитель")
NOT_KEYS = {"документ", "раздел"}  # части файла, а не ключи справочника
LIST_KINDS = (
    "метод",
    "функция",
    "страница",
    "правило прокси",
    "команда",
    "таблица",
    "колонка",
    "файл данных",
    "колонка файла",
    "папка",
    "ключ Redis",
    "память браузера",
    "настройка",
    "другая настройка",
    "постоянная",
    "фоновая работа",
    "ограничитель",
    "проблема",
    "набор тестов",
    "связь",
    "срез",
    "шаг",
    "процесс",
    "этап",
    "стрелка",
    "правка",
    "решение",
    "задача",
    "тест",
    "блок",
)
TOBE_KINDS = ("правка", "решение", "задача", "тест", "блок")  # виды «как будет» — только с --tobe
KIND_ALIAS = {"шаг среза": "шаг", "своя работа": "срез"}
LINK_ORDER = ("обрабатывает", "зовёт", "пишет", "читает")
STEP_RE = re.compile(r"^([a-z0-9_-]+)/([a-z0-9_-]+)#([a-z0-9-]+)$")
ITEM_RE = re.compile(r"^([a-z0-9_-]+)#([a-z0-9-]+)$")
CHANGE_RE = re.compile(r"^(?:[cdkt]-[a-z0-9-]+|b\d+)$")
GITBASH_RE = re.compile(r"^[A-Za-z]:/(?:Program Files/)?Git(/.*)$")
SERVICE_COLON_RE = re.compile(r"^([a-z0-9_-]+):(\S.*)$")
RANGE_RE = re.compile(r"^(.*?):(\d+)(?:-(\d+))?$")


class InputError(Exception):
    """Ошибка ввода: код выхода 2."""


def norm(s: str) -> str:
    return s.casefold().replace("ё", "е")


def clip(s: str, n: int = EXCERPT) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def excerpt(text: str, word: str) -> str:
    """До 200 знаков вокруг первой находки слова."""
    i = norm(text).find(word)
    if i < 0 or len(text) <= EXCERPT:
        return clip(text)
    start = max(0, i - 80)
    out = text[start : start + EXCERPT - 2]
    return (
        ("…" if start else "") + out + ("…" if start + EXCERPT - 2 < len(text) else "")
    )


class Finder:
    def __init__(self, root: Path, full: bool, tobe: bool):
        self.full = full
        self.tobe = tobe
        self.asis = MapModel(root)
        self.chg: ChangeModel | None = None
        self.m = self.asis
        self.out: list[str] = []
        self.prefix = (
            self.asis.root.relative_to(self.asis.repo).as_posix() + "/"
            if self.asis.root != self.asis.repo
            else ""
        )
        if self.asis.errors:
            warn(
                f"в карте {len(self.asis.errors)} ошибок разбора — ответ по разобранному; "
                f"первая: {self.asis.errors[0]}"
            )
        if tobe:
            self.chg = ChangeModel(self.asis.root, self.asis)
            if not self.chg.open:
                warn("изменения нет — ответ по «как есть»")
                self.chg = None
            else:
                self.m = self.chg.world

    # вывод ---------------------------------------------------------------------------------------

    def add(self, line: str = "") -> None:
        self.out.append(line)

    def items(self, rows: list[str], indent: str = "  ") -> None:
        show = rows if self.full or len(rows) <= LIMIT else rows[:LIMIT]
        for r in show:
            self.add(indent + r)
        if len(show) < len(rows):
            self.add(f"{indent}показано {LIMIT} из {len(rows)} — --all")

    def path(self, file: str, line: int | None = None) -> str:
        """md от корня карты → путь от корня репо; в мире «как будет» — копия в TOBE/ и её строка."""
        if self.chg and file in self.chg.copies and self.m is self.chg.world:
            lm = self.chg.line_map.get(file, [])
            if line:
                line = lm[line - 1] if 0 < line <= len(lm) else line
            file = self.chg.copies[file]
        return f"{self.prefix}{file}" + (f":{line}" if line else "")

    # общее ---------------------------------------------------------------------------------------

    def svc_order(self, svc: str | None) -> int:
        return (
            self.m.services.index(svc)
            if svc in self.m.services
            else len(self.m.services)
        )

    def link_order(self, ln: Link) -> tuple:
        return (
            self.svc_order(self.m._service_of_file(ln.src_file)),
            ln.src_file,
            ln.src_line,
        )

    def src_entity(self, ln: Link) -> Entity | None:
        return self.m.get(self.m._service_of_file(ln.src_file), ln.src)

    def label(self, e: Entity) -> str:
        if e.kind in ("шаг", "проблема", "ограничитель", "фоновая работа", "этап"):
            return f"{e.addr} «{e.title}»"
        if e.kind == "процесс":
            return f"{e.addr} «{e.title}»"
        return e.addr

    def src_label(self, ln: Link) -> str:
        e = self.src_entity(ln)
        return self.label(e) if e else ln.src

    def process_title(self, proc: str) -> str:
        pe = self.m.processes.get(proc)
        return f"{proc} «{pe.title}»" if pe else proc

    def code_str(self, e: Entity) -> str:
        parts: list[str] = []
        last = None
        for r in e.code:
            parts.append(f":{r.line}" if r.path == last else f"{r.path}:{r.line}")
            last = r.path
        return " ".join(parts) + "".join(f" · {x}" for x in e.live)

    def fields_lines(self, e: Entity, skip: tuple[str, ...] = ()) -> list[str]:
        out = []
        for name, f in e.fields.items():
            if name == "Код" or name in skip:
                continue
            out.append(f"{name}: " + (f.value if f.value else " · ".join(f.items)))
        return out

    def marks(self, e: Entity, chg: ChangeModel | None = None) -> list[str]:
        """Правки «как будет» на разделе мира «как будет»: обёрнут целиком или правятся его поля, строки, текст."""
        chg = chg or self.chg
        if not chg or e.file not in chg.copies or not e.line:
            return []
        lm = chg.line_map.get(e.file, [])
        cl = lm[e.line - 1] if 0 < e.line <= len(lm) else 0
        out = []
        level = (
            1 if e.kind == "процесс" else e.level
        )  # у процесса заголовок «# название»
        for b in chg.blocks_in(e.file):
            inside = b.line < cl < b.end
            owner = b.owner[-1] if b.owner else None
            own = (
                owner is not None
                and owner[0] == level
                and (owner[2] or owner[1]) == (e.anchor or e.title)
            ) or (owner is None and e.line == 1)
            if b.kind != "уходит" and (
                inside or own and b.what in ("поля", "текст", "строки")
            ):
                out.append(f"{b.number} · {b.kind} · {b.status}")
            elif b.kind == "уходит" and own and b.what in ("поля", "текст", "строки"):
                out.append(f"{b.number} · уходит часть · {b.status}")
        return out

    def gone_block(self, e: Entity) -> Block | None:
        """Правка «уходит», которая убирает раздел «как есть» e."""
        if not self.chg:
            return None
        for b in self.chg.blocks_in(e.file):
            if (
                b.kind == "уходит"
                and b.head
                and (b.head[2] or b.head[1]) == (e.anchor or e.title)
            ):
                return b
        return None

    # ключ ----------------------------------------------------------------------------------------

    def normalize(self, q: str) -> str:
        q = q.strip()
        if q.startswith("[[") and q.endswith("]]"):
            q = q[2:-2].strip()
        g = GITBASH_RE.match(q.replace("\\", "/"))
        if g:
            q = g.group(1)
        q = re.sub(r"\s*->\s*", " → ", q)  # стрелку набирают и как «->»
        sc = SERVICE_COLON_RE.match(q)
        if sc and sc.group(1) in self.m.registry:
            q = f"{sc.group(1)}: {sc.group(2)}"
        return q

    def key_mode(self, q: str) -> int:
        m = self.m
        if CHANGE_RE.match(q):
            return self.change_card(q)
        st = STEP_RE.match(q)
        if st:
            e = m.get(st.group(1), q)
            if e:
                self.step_card(e)
                return 0
            return self.not_found(q)
        if "→" in q:
            return self.link_card(q)
        proc = self.find_process(q)
        if proc:
            return self.process_mode(proc)
        it = ITEM_RE.match(q)
        if it and it.group(1) in m.processes:
            return self.item_card(it.group(1), it.group(2))
        svc, key = split_key(q, set(m.services))
        if svc and svc.startswith("external:"):
            return self.provider_card(svc, key)
        if svc:
            e = m.get(svc, key)
            if e and e.kind not in NOT_KEYS:
                self.add(f"{q} — нашлось")
                self.card(e)
                return 0
            fm = self.fact_method(svc, key)
            if fm:
                self.add(f"{q} — есть только в фактах")
                self.fact_method_card(svc, fm)
                return 0
            old = self.asis.get(svc, key) if self.chg else None
            if old and old.kind not in NOT_KEYS:
                return self.gone_card(old)
            return self.not_found(q, svc, key)
        hits = [m.get(s, key) for s in m.services]
        hits = [e for e in hits if e and e.kind not in NOT_KEYS]
        facts_hits = [
            (s, self.fact_method(s, key)) for s in m.services if not m.get(s, key)
        ]
        facts_hits = [(s, f) for s, f in facts_hits if f]
        n = len(hits) + len(facts_hits)
        if n >= 3:
            who = [e.service for e in hits] + [
                f"{s} (только в фактах)" for s, _ in facts_hits
            ]
            self.add(f"{key} — есть у {n} сервисов: уточни '<сервис>: {key}'")
            self.items(who)
            return 0
        if not n:
            return self.not_found(q, None, key)
        self.add(f"{key} — нашлось у {n} " + ("сервиса" if n == 1 else "сервисов"))
        for e in hits:
            self.add()
            self.card(e)
        for s, f in facts_hits:
            self.add()
            self.fact_method_card(s, f)
        return 0

    def not_found(self, q: str, svc: str | None = None, key: str | None = None) -> int:
        m = self.m
        key = key or q
        self.add(f"не нашлось: {q}")
        others = [
            s
            for s in m.services
            if s != svc and m.get(s, key) and m.get(s, key).kind not in NOT_KEYS
        ]
        if others:
            self.add(f"  такой ключ есть у: {', '.join(others)} — '{others[0]}: {key}'")
        if self.chg is None and (self.asis.root / "TOBE" / "README.md").is_file():
            chg = ChangeModel(self.asis.root, self.asis)
            w = (
                chg.world.get(svc, key)
                if svc
                else next(
                    (
                        chg.world.get(s, key)
                        for s in chg.world.services
                        if chg.world.get(s, key)
                    ),
                    None,
                )
            )
            if w:
                nums = [x.split(" · ")[0] for x in self.marks(w, chg)]
                self.add(
                    f"  есть в «как будет» ({', '.join(nums) or 'TOBE'}): добавь --tobe"
                )
        pool = [
            (f"{e.service}: {e.addr}" if e.service else e.addr)
            for e in m.entities.values()
            if e.kind not in NOT_KEYS and (svc is None or e.service == svc)
        ]
        near = [p for p in pool if norm(key) in norm(p)][:5]
        if len(near) < 5:
            near += [
                p
                for p in difflib.get_close_matches(
                    f"{svc}: {key}" if svc else key, pool, n=5, cutoff=0.6
                )
                if p not in near
            ]
        if near:
            self.add("  похожие: " + " · ".join(near[:5]))
        return 1

    def gone_card(self, old: Entity) -> int:
        """Ключ, который в «как будет» уходит: раздел «как есть» и кто в мире «как будет» его ещё зовёт."""
        b = self.gone_block(old)
        svc = old.service or ""
        self.add(
            f"{svc}: {old.addr} — уходит в «как будет»"
            + (f" ({b.number} · {b.status})" if b else "")
        )
        self.add(f"{old.addr} · {svc} · {old.kind} — {self.asis.what(old)}")
        self.add(f"md «как есть»: {self.prefix}{old.file}:{old.line}")
        if b:
            self.add(f"правка: {self.prefix}{b.file}:{b.line} · Почему: {b.why}")
        left = sorted(self.m.links_to(svc, old.addr), key=self.link_order)
        if left:
            self.add(f"останется звать убранное ({len(left)}):")
            self.items(
                [
                    f"{self.path(ln.src_file, ln.src_line)} · {ln.kind} · {ln.src}"
                    for ln in left
                ]
            )
        else:
            self.add("ссылок на него в «как будет» нет")
        return 0

    def find_process(self, q: str) -> str | None:
        if q in self.m.processes:
            return q
        for proc, pe in self.m.processes.items():
            if norm(pe.title) == norm(q):
                return proc
        return None

    def fact_method(self, svc: str, key: str) -> dict | None:
        for x in (self.m.facts.get(svc, {}).get("fastapi-openapi") or {}).get(
            "methods", []
        ):
            if f"{x['method']} {x['path']}" == key:
                return x
        return None

    def facts_date(self, svc: str) -> str:
        return (self.m.facts.get(svc, {}).get("extracted_at") or "")[:10]

    def fact_method_line(self, svc: str, fm: dict) -> str:
        def fl(fields: list[dict]) -> str:
            return ", ".join(
                f"{x['name']} ({', '.join(v for v in (x.get('in'), x.get('type')) if v)}"
                f"{', обяз.' if x.get('required') else ''})"
                for x in fields
            )

        parts = [
            f"обработчик {fm.get('ref', '')}",
            "вход — да" if fm.get("auth") else "вход — нет",
            "есть в живой схеме" if fm.get("in_schema") else "в живой схеме нет",
        ]
        if fm.get("request"):
            parts.append("запрос: " + fl(fm["request"]))
        if fm.get("response"):
            parts.append("ответ: " + fl(fm["response"]))
        return f"факты ({self.facts_date(svc)}): " + " · ".join(parts)

    def fact_method_card(self, svc: str, fm: dict) -> None:
        key = f"{fm['method']} {fm['path']}"
        self.add(f"{key} · {svc} · метод · раздела нет — служебный или не описан")
        self.add(self.fact_method_line(svc, fm))
        self.derived_entry(svc, key)
        self.links_block(svc, key)

    def card(self, e: Entity) -> None:
        m = self.m
        what = m.what(e)
        head = f"{e.addr} · {e.service} · {e.kind}" + (f" — {what}" if what else "")
        if e.extra.get("facts_only"):
            head += " · раздела нет"
        self.add(head)
        for mk in self.marks(e):
            self.add(f"как будет: {mk}")
        if e.line:
            self.add(f"md: {self.path(e.file, e.line)}")
        for t in e.text:
            self.add(f"  {t}")
        for x in self.fields_lines(
            e, ("Что делает", "Что на странице")
        ):  # они уже в первой строке
            self.add(f"  {x}")
        if e.code or e.live:
            self.add(f"  Код: {self.code_str(e)}")
        svc = e.service or ""
        self.facts_lines(e)
        if e.kind in ENTRY_KINDS:
            self.derived_entry(svc, e.addr)
        elif e.kind in STORE_KINDS:
            self.derived_store(svc, e)
        elif e.kind in READ_KINDS:
            self.list_links("кто читает", m.links_to(svc, e.addr, ("читает",)))
        elif e.kind == "проблема":
            self.where_problem(e)
        elif e.kind in ("связь", "связь-метод"):
            self.add("связь — подробно: find.py " + f"'{e.addr}'")
        self.links_block(svc, e.addr)

    def facts_lines(self, e: Entity) -> None:
        m, svc = self.m, e.service or ""
        if e.kind == "метод":
            fm = self.fact_method(svc, e.addr)
            if fm:
                self.add(self.fact_method_line(svc, fm))
        elif e.kind == "колонка":
            tc = m.column_facts(svc, e.addr)
            if tc:
                c = tc[1]
                parts = [
                    f"тип {c.get('type') or '—'}",
                    "может быть пустой"
                    if c.get("nullable")
                    else "обязательна"
                    if c.get("nullable") is False
                    else "",
                    f"умолчание {c['default']}" if c.get("default") else "",
                    f"описание в базе: {c['db_comment']}"
                    if c.get("db_comment")
                    else "",
                    f"описание в коде: {c['comment']}"
                    if c.get("comment") and not c.get("db_comment")
                    else "",
                    f"модель {c['ref']}" if c.get("ref") else "",
                ]
                self.add(
                    f"факты ({self.facts_date(svc)}): "
                    + " · ".join(p for p in parts if p)
                )
        elif e.kind == "таблица":
            pg = m.facts.get(svc, {}).get("postgres") or {}
            t = next((t for t in pg.get("tables", []) if t["name"] == e.addr), None)
            if t:
                parts = [
                    f"строк {t['rows']} на {pg.get('rows_at', '')}"
                    if t.get("rows") is not None
                    else "строк — нет данных",
                    f"колонок {len(t.get('columns', []))}",
                ] + [f"уникальный: {u}" for u in t.get("uniques", [])]
                self.add(f"факты ({self.facts_date(svc)}): " + " · ".join(parts))
        elif e.kind == "настройка":
            s = next(
                (
                    s
                    for s in facts_settings(m.facts.get(svc, {}))
                    if s["name"] == e.addr
                ),
                None,
            )
            if s:
                val = (
                    "значение — секрет, не выводится"
                    if s.get("secret")
                    else f"значение {s['value']}"
                    if s.get("value")
                    else "значения нет"
                )
                parts = [
                    val,
                    f"откуда: {s.get('source')} {s.get('source_ref') or ''}".strip()
                    if s.get("source")
                    else "",
                    f"умолчание {s['default']}" if s.get("default") else "",
                    "обязательна" if s.get("required") else "",
                    f"в коде {s['ref']}" if s.get("ref") else "",
                    f"читают в коде: {len(s.get('used_refs') or [])}"
                    if s.get("used_refs")
                    else "",
                ]
                self.add(
                    f"факты ({self.facts_date(svc)}): "
                    + " · ".join(p for p in parts if p)
                )
        elif e.kind == "функция":
            ex = (m.facts.get(svc, {}).get("python-exports") or {}).get("exports", [])
            x = next((x for x in ex if x["name"] == e.addr), None)
            if x:
                self.add(
                    f"факты ({self.facts_date(svc)}): {x.get('kind', '')} {x.get('signature') or ''}".rstrip()
                    + f" · {x.get('ref', '')}"
                )

    def callers_rows(self, svc: str, key: str) -> list[str]:
        """Кто вызывает точку входа: шаги, «Связи» вызывающих, вручную, стрелки человека и провайдера."""
        m = self.m
        rows: dict[str, list[str]] = {}
        for c in m.incoming(svc):
            if m.get(c.service, f"{c.addr}: {key}"):
                rows.setdefault(c.service or "", []).append(f"связь «{c.addr}»")
        for c in m.callers(svc, key):
            if c["via"] == "шаг":
                st = c.get("entity")
                rows.setdefault(c["who"] or "", []).append(
                    f"шаг {st.addr}" if st else f"ссылка {c['link'].src}"
                )
            elif c["via"] == "вручную":
                rows.setdefault("вручную", []).append(c["text"])
            else:
                a: Arrow = c["arrow"]
                rows.setdefault(a.sender, []).append(
                    f"процесс {a.process}, стрелка {a.number} {a.id}"
                )
        return [
            f"{who} — {'; '.join(dict.fromkeys(parts))}" for who, parts in rows.items()
        ]

    def derived_entry(self, svc: str, key: str) -> None:
        m = self.m
        callers = self.callers_rows(svc, key)
        if callers:
            self.add(f"кто вызывает ({len(callers)}):")
            self.items(callers)
        else:
            self.add("кто вызывает: никто — ни связей, ни шагов, ни «Вручную:»")
        steps = m.steps_handling(svc, key)
        if steps:
            self.add("как работает: " + self.steps_short(steps))
        touch = self.touch_str(m.touches(svc, key))
        if touch:
            self.add(f"что трогает: {touch}")
        probs = self.problems_of([key] + [s.addr for s in steps], svc)
        if probs:
            self.add("проблемы: " + " · ".join(probs))

    def steps_short(self, steps: list[Entity]) -> str:
        out, last = [], None
        for s in steps:
            head = s.addr.split("#")[0]
            out.append(f"#{s.anchor}" if head == last else s.addr)
            last = head
        return " · ".join(out)

    def touch_str(self, links: list[Link]) -> str:
        groups: dict[str, list[str]] = {}
        for ln in links:
            lst = groups.setdefault(ln.kind, [])
            if ln.raw not in lst:
                lst.append(ln.raw)
        return " · ".join(
            f"{k} {', '.join(groups[k])}" for k in LINK_ORDER if groups.get(k)
        )

    def problems_of(self, srcs: list[str], svc: str) -> list[str]:
        """Проблемы из полей «Проблемы:» разделов и шагов srcs."""
        m, out = self.m, []
        for ln in m.links:
            if (
                ln.src in srcs
                and ln.key.startswith("p-")
                and m._service_of_file(ln.src_file) == svc
            ):
                p = m.get(ln.service, ln.key)
                imp = p.fields["Важность"].value if p and "Важность" in p.fields else ""
                s = f"{ln.raw} «{p.title}»" if p else ln.raw
                s += f" ({imp})" if imp else ""
                if ln.src != srcs[0]:
                    s += f" — шаг {ln.src}"
                if s not in out:
                    out.append(s)
        return out

    def list_links(self, title: str, links: list[Link]) -> None:
        rows = [
            f"{self.path(ln.src_file, ln.src_line)} · {self.src_label(ln)}"
            for ln in sorted(links, key=self.link_order)
        ]
        if rows:
            self.add(f"{title} ({len(rows)}):")
            self.items(rows)

    def derived_store(self, svc: str, e: Entity) -> None:
        m = self.m
        wr = m.writers_readers(svc, e.addr)
        if not wr["пишет"] and not wr["читает"]:
            self.add("кто пишет и кто читает: ссылок с видом нет")
        self.list_links("кто пишет", wr["пишет"])
        self.list_links("кто читает", wr["читает"])
        if e.kind == "колонка":
            table = e.addr.split(".", 1)[0]
            self.list_links(
                f"через таблицу {table} — пишут и читают её целиком",
                wr["через таблицу"],
            )
            users = self.field_users(svc, e)
            if users:
                self.add(
                    f"кто получает её через метод и упоминает «{e.addr.split('.', 1)[1]}» ({len(users)}):"
                )
                self.items(
                    [
                        f"{self.path(u.file, u.line)} · {u.addr} «{u.title}» — через {msvc}: {mkey}"
                        for u, msvc, mkey in users
                    ]
                )
        if e.kind == "таблица":
            cols: dict[str, dict[str, list[str]]] = {}
            for ln in sorted(m.links, key=self.link_order):
                if (
                    ln.service == svc
                    and ln.key.startswith(e.addr + ".")
                    and ln.kind in ("пишет", "читает")
                ):
                    lst = cols.setdefault(ln.key, {}).setdefault(ln.kind, [])
                    if ln.src not in lst:
                        lst.append(ln.src)
            if cols:
                self.add(f"колонки — кто пишет и кто читает ({len(cols)}):")
                self.items(
                    [
                        f"{k} — "
                        + "; ".join(
                            f"{'пишут' if v == 'пишет' else 'читают'}: {', '.join(n[v])}"
                            for v in ("пишет", "читает")
                            if v in n
                        )
                        for k, n in sorted(cols.items())
                    ]
                )

    @staticmethod
    def mentions(e: Entity, word: str) -> bool:
        """Упоминает ли раздел слово — в заголовке, тексте или полях (поле колонки — по имени)."""
        text = " ".join([e.title, *e.text, *(f.value for f in e.fields.values())])
        return word.lower() in text.lower()

    def field_users(self, svc: str, e: Entity) -> list[tuple[Entity, str, str]]:
        """Кто получает колонку через метод: шаги и методы других мест, которые зовут метод, читающий колонку или
        её таблицу целиком, и упоминают имя колонки: (кто, сервис метода, метод)."""
        m = self.m
        col = e.addr.split(".", 1)[1]
        wr = m.writers_readers(svc, e.addr)
        out: dict[tuple, tuple[Entity, str, str]] = {}
        for ln in wr["читает"] + [x for x in wr["через таблицу"] if x.kind == "читает"]:
            src_svc = m._service_of_file(ln.src_file) or ""
            src = m.get(src_svc, ln.src)
            if not src:
                continue
            entries = (
                [src.addr]
                if src.kind in ENTRY_KINDS
                else [
                    x.key
                    for x in m.links
                    if x.src == src.addr
                    and x.kind == "обрабатывает"
                    and m._service_of_file(x.src_file) == src_svc
                ]
            )
            for key in entries:
                for c in m.callers(src_svc, key):
                    ce = c.get("entity")
                    if c["via"] == "шаг" and ce and self.mentions(ce, col):
                        out.setdefault((ce.service, ce.addr), (ce, src_svc, key))
        return sorted(out.values(), key=lambda x: (self.svc_order(x[0].service or ""), x[0].file, x[0].line))

    def where_problem(self, e: Entity) -> None:
        m = self.m
        rows = []
        for ln in sorted(m.links_to(e.service or "", e.addr), key=self.link_order):
            src = self.src_entity(ln)
            if (
                src
                and "Проблемы" in src.fields
                and src.fields["Проблемы"].line == ln.src_line
            ):
                rows.append(
                    f"{self.path(ln.src_file, ln.src_line)} · {self.label(src)}"
                )
        if rows:
            self.add(f"где проявляется ({len(rows)}):")
            self.items(rows)

    def links_block(self, svc: str, key: str) -> None:
        """Все места, где ключ упомянут: ссылки с видом и без, «как» и «внутри» стрелок, «Связи» вызывающих."""
        m = self.m
        rows: list[tuple] = []
        for ln in m.links_to(svc, key):
            kind = "стрелка «как»" if ln.kind == "как" else ln.kind
            rows.append(
                (
                    self.link_order(ln),
                    f"{self.path(ln.src_file, ln.src_line)} · {kind} · {ln.src}",
                )
            )
        for proc, arrows in m.arrows.items():
            for a in arrows:
                for ins in a.inside:
                    lm = LINK_RE.fullmatch(ins)
                    if lm and split_key(lm.group(1), set(m.services)) == (svc, key):
                        rows.append(
                            (
                                (len(m.services), a.file, a.line),
                                f"{self.path(a.file, a.line)} · стрелка «внутри» · {proc}#{a.id}",
                            )
                        )
        for c in m.incoming(svc):
            sub = m.get(c.service, f"{c.addr}: {key}")
            if sub:
                rows.append(
                    (
                        (self.svc_order(c.service), sub.file, sub.line),
                        f"{self.path(sub.file, sub.line)} · связь · {c.addr}",
                    )
                )
        rows.sort(key=lambda x: x[0])
        if not rows:
            self.add("ссылок нет")
            return
        self.add(f"ссылки ({len(rows)}):")
        self.items([r for _, r in rows])

    # шаг, связь, провайдер, этап и стрелка ------------------------------------------------------

    def step_card(self, e: Entity) -> None:
        m = self.m
        proc = e.extra.get("process", "")
        self.add(f"{e.addr} · шаг «{e.title}» — {e.first_phrase()}")
        for mk in self.marks(e):
            self.add(f"как будет: {mk}")
        self.add(
            "процесс: "
            + ("своя работа сервиса" if proc == "own" else self.process_title(proc))
        )
        self.add(f"md: {self.path(e.file, e.line)}")
        for t in e.text:
            self.add(f"  {t}")
        for x in self.fields_lines(e):
            self.add(f"  {x}")
        if e.code or e.live:
            self.add(f"  Код: {self.code_str(e)}")
        arrows = m.arrows_to_step(e)
        if arrows:
            self.add(
                "стрелки: "
                + " · ".join(
                    f"{a.number} {a.id} {a.sender} → {a.receiver} «{a.what}»"
                    for a in arrows
                )
            )
        own = [
            ln
            for ln in m.links
            if ln.src == e.addr and m._service_of_file(ln.src_file) == e.service
        ]
        for ln in own:
            if ln.kind == "обрабатывает":
                who = sorted(
                    {
                        r.split(" — ")[0]
                        for r in self.callers_rows(ln.service or "", ln.key)
                    }
                )
                self.add(
                    f"обрабатывает: {ln.service}: {ln.key}"
                    + (f" — его зовёт {', '.join(who)}" if who else " — никто не зовёт")
                )
        calls = [ln for ln in own if ln.kind == "зовёт"]
        if calls:
            self.add("вызовы шага:")
            for ln in calls:
                self.add(f"  → {ln.raw} — {self.call_behavior(e.service or '', ln)}")
        probs = self.problems_of([e.addr], e.service or "")
        if probs:
            self.add("проблемы: " + " · ".join(probs))

    def call_behavior(self, svc: str, ln: Link) -> str:
        """Поведение вызова — из «Связей» вызывающего: поля метода связи поверх полей связи."""
        m = self.m
        to = ln.service or ""
        conn = m.get(svc, f"{svc} → {to}")
        if conn is None:
            return (
                "функция пакета"
                if m.registry.get(to, {}).get("kind") in ("package", "library")
                else "в «Связях» нет"
            )
        sub = m.get(svc, f"{conn.addr}: {ln.key}")
        parts = []
        for name in ("Ожидание", "При отказе", "Не доходит"):
            f = (sub.fields.get(name) if sub else None) or conn.fields.get(name)
            if f:
                parts.append(f"{name}: {f.value or ' · '.join(f.items)}")
        return " · ".join(parts) or f"связь {conn.addr} — без полей поведения"

    def link_card(self, q: str) -> int:
        m = self.m
        mm = re.match(r"^([a-z0-9_-]+) → (\S+?)(?:: (.+))?$", q)
        if not mm:
            raise InputError(
                f"связь пишется так: '<сервис> → <кому>' или '<сервис> → <кому>: <ключ>' — дано: {q}"
            )
        svc, to, key = mm.group(1), mm.group(2), mm.group(3)
        conn = m.get(svc, f"{svc} → {to}")
        if not conn:
            return self.not_found(q, svc, f"{svc} → {to}")
        subs = [
            e
            for e in m.by_service.get(svc, [])
            if e.kind == "связь-метод" and e.parent == conn.addr
        ]
        if key:
            subs = [e for e in subs if e.addr == f"{conn.addr}: {key}"]
            if not subs:
                return self.not_found(q, svc, f"{conn.addr}: {key}")
        self.add(
            f"{conn.addr} · связь — {plural(len(subs), 'метод', 'метода', 'методов')}"
        )
        for mk in self.marks(conn):
            self.add(f"как будет: {mk}")
        self.add(f"md: {self.path(conn.file, conn.line)}")
        for x in self.fields_lines(conn):
            self.add(f"  {x}")
        for t in conn.text:
            self.add(f"  {t}")
        if conn.code or conn.live:
            self.add(f"  Код: {self.code_str(conn)}")
        for sub in subs:
            k = sub.addr.split(": ", 1)[1]
            self.add(f"{k}:")
            for mk in self.marks(sub):
                self.add(f"  как будет: {mk}")
            self.add(f"  md: {self.path(sub.file, sub.line)}")
            for x in self.fields_lines(sub):
                self.add(f"  {x}")
            for t in sub.text:
                self.add(f"  {t}")
            if sub.code or sub.live:
                self.add(f"  Код: {self.code_str(sub)}")
            target = m.get(to, k) if to in m.registry else None
            if to.startswith("external:"):
                self.add("  принимает: внешний провайдер — справочника нет")
            elif target:
                fm = self.fact_method(to, k)
                self.add(
                    f"  принимает: {self.path(target.file, target.line)}"
                    + (f" · обработчик {fm['ref']}" if fm else "")
                )
            else:
                fm = self.fact_method(to, k)
                self.add(
                    f"  принимает: {to} — раздела нет"
                    + (f"; обработчик {fm['ref']}" if fm else "")
                )
            steps = [
                ln
                for ln in m.links
                if ln.kind == "зовёт"
                and ln.service == to
                and ln.key == k
                and m._service_of_file(ln.src_file) == svc
            ]
            if steps:
                self.add(
                    "  зовут шаги: " + " · ".join(self.src_label(ln) for ln in steps)
                )
        return 0

    def provider_card(self, prov: str, key: str) -> int:
        m = self.m
        found = [
            e
            for s in m.services
            for e in m.by_service.get(s, [])
            if e.kind == "связь-метод" and e.addr == f"{s} → {prov}: {key}"
        ]
        if not found:
            return self.not_found(f"{prov}: {key}")
        self.add(
            f"{prov}: {key} — внешний провайдер; справочника нет, вызов описан в «Связях» вызывающих ({len(found)})"
        )
        for e in found:
            self.add()
            self.link_card(e.addr)
        return 0

    def item_card(self, proc: str, item: str) -> int:
        m = self.m
        st = m.get(None, f"{proc}#{item}")
        if st and st.kind == "этап":
            arrows = [a for a in m.arrows.get(proc, []) if a.stage == item]
            self.add(
                f"{proc}#{item} · этап «{st.title}» процесса {self.process_title(proc)} — стрелок {len(arrows)}"
            )
            self.add(f"md: {self.path(st.file, st.line)}")
            for t in st.text:
                self.add(f"  {t}")
            self.items([self.arrow_row(a) for a in arrows])
            return 0
        a = next((a for a in m.arrows.get(proc, []) if a.id == item), None)
        if not a:
            return self.not_found(f"{proc}#{item}")
        self.add(
            f"{proc}#{a.id} · стрелка {a.number} процесса {self.process_title(proc)}"
        )
        self.add(f"md: {self.path(a.file, a.line)}")
        self.add(f"  {a.sender} → {a.receiver} · {a.kind}")
        self.add(f"  что: {a.what}")
        if a.how:
            self.add(f"  как: {a.how}")
        self.add(f"  внутри: {' · '.join(a.inside) or '???'}")
        for ins in a.inside:
            if "#" in ins and not ins.startswith("[["):
                s, anc = ins.split("#", 1)
                e = m.get(s, f"{s}/{proc}#{anc}")
                if e:
                    self.add(f"  шаг {e.addr} «{e.title}» — {e.first_phrase()}")
        return 0

    def arrow_row(self, a: Arrow) -> str:
        how = f" · {a.how}" if a.how else ""
        return f"{a.number} {a.id} · {a.sender} → {a.receiver} · «{a.what}»{how} · {a.kind} · {' · '.join(a.inside)}"

    # процесс и сервис ----------------------------------------------------------------------------

    def process_mode(self, proc: str) -> int:
        m = self.m
        pe = m.processes[proc]
        arrows = m.arrows.get(proc, [])
        stages = [
            e for e in m.entities.values() if e.kind == "этап" and e.parent == proc
        ]
        self.add(f"{proc} «{pe.title}» · процесс")
        for mk in self.marks(pe):
            self.add(f"как будет: {mk}")
        self.add(f"md: {self.path(pe.file, 1)}")
        if pe.text:
            self.add(f"  {pe.text[0]}")
        for name in (
            "Кто запускает",
            "Чем кончается",
            "Работает ли сейчас",
            "Не происходит",
        ):
            f = pe.fields.get(name)
            if f:
                self.add(f"  {name}: " + (f.value or " · ".join(f.items)))
        parts = pe.extra.get("participants", [])
        self.add(f"участники ({len(parts)}):")
        for p in parts:
            sl = m.slices.get((p, proc))
            if sl:
                self.add(f"  {p} — срез {self.path(sl.file)}")
                for addr in sl.extra.get("steps", []):
                    st = m.get(p, addr)
                    if st:
                        mk = "".join(f" [{x}]" for x in self.marks(st))
                        self.add(
                            f"    #{st.anchor} «{st.title}»{mk} — {clip(st.first_phrase(), 160)}"
                        )
                if self.chg:
                    for b in self.chg.blocks_in(sl.file):
                        if b.kind == "уходит" and b.what == "раздел" and b.head:
                            self.add(
                                f"    #{b.head[2] or b.head[1]} «{b.head[1]}» [{b.number} · уходит]"
                            )
            elif p in m.registry:
                keys = []
                for a in arrows:
                    if a.receiver == p:
                        keys += [
                            r
                            for r in LINK_RE.findall(a.how)
                            if split_key(r, set(m.services))[0] == p
                        ]
                self.add(
                    f"  {p} — среза нет; отвечает: "
                    + (" · ".join(dict.fromkeys(keys)) or "—")
                )
            else:
                self.add(f"  {p} — участник без среза")
        self.add(f"стрелок: {len(arrows)} · этапов: {len(stages)}")
        probs = []
        for p in parts:
            sl = m.slices.get((p, proc))
            if sl:
                probs += self.problems_of_steps(p, sl.extra.get("steps", []))
        if probs:
            self.add("проблемы на пути: " + " · ".join(dict.fromkeys(probs)))
        for p in parts:
            if p in m.registry and not any(p in (a.sender, a.receiver) for a in arrows):
                warn(f"{proc}: {p} есть в «Участники:», а стрелок с ним нет")
        for (s, pr), _ in m.slices.items():
            if pr == proc and s not in parts:
                warn(f"{proc}: у {s} есть срез, а в «Участники:» его нет")
        return 0

    def problems_of_steps(self, svc: str, steps: list[str]) -> list[str]:
        out = []
        for addr in steps:
            for s in self.problems_of([addr], svc):
                out.append(f"{s} — шаг {addr}")
        return out

    def service_mode(self, svc: str) -> int:
        m = self.m
        if svc not in m.registry:
            near = difflib.get_close_matches(svc, m.services, n=3, cutoff=0.5)
            self.add(
                f"не нашлось: сервиса {svc} нет в реестре"
                + (f"; похожие: {', '.join(near)}" if near else "")
            )
            return 1
        rd = m.get(svc, "README.md")
        kind = m.registry[svc].get("kind", "")
        self.add(f"{svc} · {KIND_RU.get(kind, kind)}")
        if rd:
            self.add(f"md: {self.path(rd.file, 1)}")
            if rd.text:
                self.add(f"  {rd.text[0]}")
        rows = []
        for proc, pe in m.processes.items():
            parts = pe.extra.get("participants", [])
            sl = m.slices.get((svc, proc))
            inside = any(
                x.startswith(f"{svc}#") or x.startswith(f"[[{svc}: ")
                for a in m.arrows.get(proc, [])
                for x in a.inside
            )
            if not (svc in parts or sl or inside):
                continue
            if sl:
                rows.append(
                    f"{proc} «{pe.title}» — срез, шагов {len(sl.extra.get('steps', []))}"
                )
            elif inside:
                keys = [
                    x[2:-2].split(": ", 1)[1]
                    for a in m.arrows.get(proc, [])
                    for x in a.inside
                    if x.startswith(f"[[{svc}: ")
                ]
                rows.append(
                    f"{proc} «{pe.title}» — отвечает методом: "
                    + " · ".join(dict.fromkeys(keys))
                )
            else:
                rows.append(f"{proc} «{pe.title}» — только в «Участники:»")
                warn(
                    f"{svc}: в «Участники:» процесса {proc} есть, а ни среза, ни «внутри» нет"
                )
            if sl and svc not in parts:
                warn(f"{svc}: срез {proc} есть, а в «Участники:» процесса его нет")
        self.add(f"процессы ({len(rows)}):")
        self.items(rows)
        own = m.own.get(svc)
        if own:
            self.add("своя работа:")
            self.items(
                [
                    f"{st.addr} «{st.title}» — {clip(st.first_phrase(), 160)}"
                    for st in (m.get(svc, a) for a in own.extra.get("steps", []))
                    if st
                ]
            )
        out_c = [
            f"→ {c.extra.get('to')}"
            + (f" «{c.fields['Подпись'].value}»" if "Подпись" in c.fields else "")
            for c in m.connections(svc)
        ]
        inc = sorted({c.service or "" for c in m.incoming(svc)}, key=self.svc_order)
        if kind in ("package", "library"):
            inc = sorted(
                {
                    m._service_of_file(ln.src_file) or ""
                    for ln in m.links
                    if ln.service == svc
                    and ln.kind == "зовёт"
                    and m._service_of_file(ln.src_file) != svc
                },
                key=self.svc_order,
            )
        self.add("связи — исходящие: " + (" · ".join(out_c) or "нет"))
        self.add("связи — входящие: " + (" · ".join(f"← {s}" for s in inc) or "нет"))
        counts = []
        for name in (
            "methods",
            "exports",
            "pages",
            "commands",
            "storage",
            "settings",
            "problems",
            "tests",
        ):
            doc = m.get(svc, f"{name}.md")
            n = sum(
                1
                for e in m.by_service.get(svc, [])
                if e.file == f"ASIS/{svc}/{name}.md" and e.kind not in NOT_KEYS
            )
            counts.append(f"{name} {'нет' if not doc or doc.extra.get('empty') else n}")
        self.add("справочник: " + " · ".join(counts))
        probs = [e for e in m.by_service.get(svc, []) if e.kind == "проблема"]
        if probs:
            self.add(f"проблемы ({len(probs)}):")
            for sev in SEVERITY + ("",):
                lst = [
                    p
                    for p in probs
                    if (p.fields["Важность"].value if "Важность" in p.fields else "")
                    == sev
                ]
                if lst:
                    self.add(
                        f"  {sev or 'без важности'}: "
                        + " · ".join(f"{p.addr} «{p.title}»" for p in lst)
                    )
        else:
            self.add("проблем нет")
        return 0

    # список ------------------------------------------------------------------------------------

    def list_mode(self, words: list[str]) -> int:
        m = self.m
        kinds, svcs, sev = set(), set(), set()
        for w in words:
            k = KIND_ALIAS.get(w, w)
            if k in LIST_KINDS:
                kinds.add(k)
            elif w in m.registry:
                svcs.add(w)
            elif w in SEVERITY:
                sev.add(w)
                kinds.add("проблема")
            else:
                raise InputError(
                    f"не знаю слова «{w}». Виды: {', '.join(LIST_KINDS)}; сервисы: "
                    f"{', '.join(m.services)}; важность: {', '.join(SEVERITY)}. "
                    "Вид из двух слов — в кавычках: 'ключ Redis'"
                )
        if kinds & set(TOBE_KINDS) and not self.chg:
            raise InputError(f"{', '.join(sorted(kinds & set(TOBE_KINDS)))} — виды «как будет»: добавь --tobe")
        rows: list[tuple] = []

        def take(kind: str, svc: str | None) -> bool:
            return (not kinds or kind in kinds) and (not svcs or svc in svcs)

        for e in m.entities.values():
            kind = "связь" if e.kind == "связь-метод" else e.kind
            if (
                e.kind in NOT_KEYS
                or e.kind == "правила прокси"
                or not take(kind, e.service)
            ):
                continue
            if (
                sev
                and (e.fields["Важность"].value if "Важность" in e.fields else "")
                not in sev
            ):
                continue
            what = m.what(e)
            if e.kind == "процесс":
                what = f"{e.title} — {what}" if what else e.title
            tail = (f" · «{clip(what, 140)}»" if what else "") + (
                " · раздела нет" if e.extra.get("facts_only") else ""
            )
            rows.append(
                (
                    (self.svc_order(e.service), e.file, e.line, e.addr),
                    f"{e.addr} · {e.service or '—'} · {kind}{tail}",
                )
            )
            if e.kind == "файл данных":
                for r in e.table:
                    col = next(iter(v for k, v in r.items() if k != "_line"), "")
                    if col and take("колонка файла", e.service):
                        rows.append(
                            (
                                (self.svc_order(e.service), e.file, r["_line"], col),
                                f"{e.addr}.{col.strip('`')} · {e.service} · колонка файла",
                            )
                        )
        for e in m.entities.values():
            if e.kind == "правила прокси" and take("правило прокси", e.service):
                for r in e.table:
                    cells = [v for k, v in r.items() if k != "_line"]
                    if cells:
                        rows.append(
                            (
                                (
                                    self.svc_order(e.service),
                                    e.file,
                                    r["_line"],
                                    cells[0],
                                ),
                                f"{cells[0].strip('`')} · {e.service} · правило прокси · «→ {cells[1] if len(cells) > 1 else ''}»",
                            )
                        )
        if take("стрелка", None) and not svcs:
            for proc, arrows in m.arrows.items():
                for a in arrows:
                    rows.append(
                        (
                            (len(m.services), a.file, a.line, a.id),
                            f"{proc}#{a.id} · — · стрелка · «{clip(a.what, 140)}»",
                        )
                    )
        if self.chg and "правка" in kinds:
            for b in self.chg.blocks:
                svc = (
                    b.file.split("/")[1] if b.file.split("/")[1] in m.registry else None
                )
                if svcs and svc not in svcs:
                    continue
                title = (
                    b.head[1]
                    if b.head
                    else (b.owner[-1][1] if b.owner else "сводка файла")
                )
                rows.append(
                    (
                        (self.svc_order(svc), b.file, b.line, b.number),
                        f"{b.number} · {svc or '—'} · правка · «{b.kind} · {b.status} — {title}»",
                    )
                )
        if self.chg and not svcs and "решение" in kinds:
            for k, d in self.chg.decisions.items():
                rows.append(((-1, d["file"], d["line"], k),
                             f"{k} · — · решение · «{d.get('Статус') or '?'} — {d['title']}»"))
        for kind, recs in (("задача", self.chg.tasks if self.chg else {}), ("тест", self.chg.tests if self.chg else {})):
            if kind not in kinds:
                continue
            for k, t in recs.items():
                if svcs and t["service"] not in svcs:
                    continue
                state = (f" · {t.get('Вид')}" if kind == "тест" and t.get("Вид") else "") + (
                    " · сделано" if t.get("Сделано") else " · не сделано" if kind == "задача" else "")
                rows.append(((self.svc_order(t["service"]), f"TOBE/{t['service']}/tasks.md", t["line"], k),
                             f"{k} · {t['service']} · {kind} · «{t['title']}»{state}"))
        if self.chg and not svcs and "блок" in kinds:
            for i, w in enumerate(x for x in self.chg.work if x.get("anchor")):
                rows.append(((len(m.services), "TOBE/blocks.md", i, w["anchor"]),
                             f"{w['anchor']} · — · блок · «{w['title']}» · {'сделано' if w.get('Сделано') else 'не сделано'}"))
        rows.sort(key=lambda x: x[0])
        filt = " ".join(words)
        self.add(f"ключей: {len(rows)}" + (f" — {filt}" if filt else ""))
        self.items([r for _, r in rows], indent="")
        return 0 if rows else 1

    # слово -------------------------------------------------------------------------------------

    def text_mode(self, words: list[str]) -> int:
        m = self.m
        ws = [norm(w) for w in words if w.strip()]
        if not ws:
            raise InputError("--text: нужны слова")

        def hit(s: str) -> bool:
            t = norm(s)
            return all(w in t for w in ws)

        first: list[tuple] = []
        seen: set[str] = set()
        ents = sorted(
            m.entities.values(),
            key=lambda e: (self.svc_order(e.service), e.file, e.line),
        )
        for e in ents:
            if e.kind in ("документ",):
                continue
            for s in (e.addr, m.what(e), e.title):
                if s and hit(s):
                    first.append(
                        (
                            e.kind,
                            e.addr,
                            e.service or "—",
                            self.path(e.file, e.line or None),
                            excerpt(s, ws[0]),
                        )
                    )
                    seen.add(f"{e.service}::{e.addr}")
                    break
        for proc, arrows in m.arrows.items():
            for a in arrows:
                if hit(a.what):
                    first.append(
                        (
                            "стрелка",
                            f"{proc}#{a.id}",
                            "—",
                            self.path(a.file, a.line),
                            excerpt(a.what, ws[0]),
                        )
                    )
        second: list[tuple] = []
        file_lines: dict[str, list[str]] = {}
        for e in ents:
            if f"{e.service}::{e.addr}" in seen or not e.line:
                continue
            blob = "\n".join(
                e.text + [f.value + " " + " ".join(f.items) for f in e.fields.values()]
            )
            if not hit(blob):
                continue
            cached = getattr(m, "md_cache", {}).get(e.file)  # мир «как будет»: его временной копии уже нет
            lines = file_lines.setdefault(e.file, cached if cached is not None else read_md(m.root / e.file))
            nxt = min(
                (x.line for x in ents if x.file == e.file and x.line > e.line),
                default=len(lines) + 1,
            )
            n, text = e.line, blob
            for i in range(e.line, min(nxt, len(lines) + 1)):
                if ws[0] in norm(lines[i - 1]):
                    n, text = i, lines[i - 1]
                    break
            second.append(
                (
                    e.kind,
                    e.addr,
                    e.service or "—",
                    self.path(e.file, n),
                    excerpt(text, ws[0]),
                )
            )
        for svc in m.services:
            for t in (m.facts.get(svc, {}).get("postgres") or {}).get("tables", []):
                for c in t.get("columns", []):
                    k = f"{t['name']}.{c['name']}"
                    d = c.get("db_comment") or ""
                    if d and hit(d) and f"{svc}::{k}" not in seen:
                        second.append(
                            (
                                "колонка",
                                k,
                                svc,
                                f"факты {self.prefix}ASIS/{svc}/.facts.json",
                                excerpt(d, ws[0]),
                            )
                        )
        total = len(first) + len(second)
        self.add(
            f"«{' '.join(words)}»: {plural(total, 'находка', 'находки', 'находок')} — {len(first)} в именах и «что», {len(second)} в текстах"
        )
        rows = [f"{k} · {a} · {s} · {p} — {x}" for k, a, s, p, x in first]
        if second:
            rows += ["в текстах:"] + [
                f"  {k} · {a} · {s} · {p} — {x}" for k, a, s, p, x in second
            ]
        self.items(rows, indent="")
        return 0 if total else 1

    # код ---------------------------------------------------------------------------------------

    def code_ranges(
        self, args: list[str]
    ) -> list[tuple[str, int | None, int | None, str]]:
        out = []
        repo = self.asis.repo
        for raw in args:
            s = raw.replace("\\", "/")
            g = RANGE_RE.match(s)
            path, a, b = (
                (g.group(1), int(g.group(2)), int(g.group(3) or g.group(2)))
                if g
                else (s, None, None)
            )
            p = Path(path)
            if p.is_absolute():
                path = Path(
                    os.path.relpath(p.resolve(), repo)
                ).as_posix()  # вне репо — через «..»
            while path.startswith("./"):
                path = path[2:]
            out.append((path, a, b, raw))
        return out

    def diff_ranges(self, branch: str) -> list[tuple[str, int | None, int | None, str]]:
        try:
            res = subprocess.run(
                ["git", "-C", str(self.asis.repo), "diff", "-U0", branch, "--"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as e:
            raise InputError(f"git diff {branch} не получился: {e}") from e
        out, path = [], None
        for line in res.stdout.split("\n"):
            if line.startswith("--- "):
                path = (
                    None
                    if line.endswith("/dev/null")
                    else line[6:]
                    if line.startswith("--- a/")
                    else line[4:]
                )
            hm = re.match(r"^@@ -(\d+)(?:,(\d+))? \+", line)
            if hm and path:
                a, n = int(hm.group(1)), int(hm.group(2) or 1)
                out.append((path, a, a + max(n, 1) - 1, f"{path}:{a}"))
        return out

    def code_mode(self, args: list[str], branch: str | None) -> int:
        m = self.m
        ranges = self.diff_ranges(branch) if branch else self.code_ranges(args)
        if not ranges:
            if branch:
                self.add(f"git diff {branch}: изменённых строк нет")
                return 1
            raise InputError("--code: нужен путь или --diff <ветка>")
        hits: dict[tuple, list[int]] = {}
        order: dict[tuple, tuple] = {}

        def match(path: str, line: int) -> bool:
            return any(
                path == p and (a is None or a <= line <= b) for p, a, b, _ in ranges
            )

        for e in m.entities.values():
            for r in e.code:
                if match(r.path, r.line):
                    k = (e.service, e.addr)
                    hits.setdefault(k, []).append(r.line)
                    order[k] = (self.svc_order(e.service), e.file, e.line)
        for svc in m.services:
            for fm in (m.facts.get(svc, {}).get("fastapi-openapi") or {}).get(
                "methods", []
            ):
                p, _, ln = (fm.get("ref") or "").rpartition(":")
                if p and ln.isdigit() and match(p, int(ln)):
                    k = (svc, f"{fm['method']} {fm['path']}")
                    e = m.get(*k)
                    hits.setdefault(k, []).append(int(ln))
                    if (
                        k not in order
                    ):  # раздел md есть — его место; нет — после разделов сервиса
                        order[k] = (
                            self.svc_order(svc),
                            e.file if e else "￿",
                            e.line if e else 0,
                        )
        keys = sorted(hits, key=lambda k: order[k])
        steps = [m.get(*k) for k in keys if m.get(*k) and m.get(*k).kind == "шаг"]
        what = f"git diff {branch}" if branch else " ".join(x[3] for x in ranges)
        nref = sum(len(v) for v in hits.values())
        self.add(
            f"{what} — {plural(len(keys), 'описание', 'описания', 'описаний')} (шагов {len(steps)}), "
            f"{plural(nref, 'ссылка', 'ссылки', 'ссылок')}"
        )
        rows = []
        for k in keys:
            e = m.get(*k)
            lines = " ".join(f":{n}" for n in sorted(set(hits[k])))
            if e:
                rows.append(
                    f"{self.path(e.file, e.line)} · {e.kind} {self.label(e) if e.kind != 'шаг' else e.addr + ' «' + e.title + '»'} · {lines}"
                )
            else:
                rows.append(
                    f"факты {k[0]} · обработчик метода {k[1]} (раздела нет) · {lines}"
                )
        self.items(rows, indent="")
        if steps or keys:
            second = []
            arr = [
                f"{a.process}#{a.id} → #{st.anchor}"
                for st in steps
                for a in m.arrows_to_step(st)
            ]
            if arr:
                second.append("стрелки: " + " · ".join(dict.fromkeys(arr)))
            entries = []
            for st in steps:
                for ln in m.links:
                    if (
                        ln.src == st.addr
                        and ln.kind == "обрабатывает"
                        and m._service_of_file(ln.src_file) == st.service
                    ):
                        entries.append((ln.service or "", ln.key))
            entries += [
                k
                for k in keys
                if m.get(*k) and m.get(*k).kind in ENTRY_KINDS or not m.get(*k)
            ]
            for svc, key in dict.fromkeys(entries):
                who = sorted({r.split(" — ")[0] for r in self.callers_rows(svc, key)})
                second.append(
                    f"точка входа: {svc}: {key} — "
                    + (f"её зовёт {', '.join(who)}" if who else "никто не зовёт")
                )
            if second:
                self.add("второй круг:")
                self.items(second)
        return 0 if keys else 1

    # цепочка -----------------------------------------------------------------------------------

    def chain_mode(self, q: str) -> int:
        m = self.m
        svc, key = split_key(q, set(m.services))
        if not svc:
            hits = [
                s
                for s in m.services
                if m.get(s, key) and m.get(s, key).kind not in NOT_KEYS
            ]
            if len(hits) != 1:
                if not hits:
                    return self.not_found(q, None, key)
                self.add(
                    f"{key} — есть у {len(hits)} сервисов: уточни '<сервис>: {key}'"
                )
                self.items(hits)
                return 0
            svc = hits[0]
        e = m.get(svc, key)
        if not e or e.kind in NOT_KEYS:
            return self.not_found(q, svc, key)
        seen: set = set()
        nodes: list[tuple] = []
        wr = m.writers_readers(svc, key)
        # у колонки под методом, который отдаёт её или таблицу, — только те, кто поле упоминает (они и задеты)
        self.field = key.split(".", 1)[1] if e.kind == "колонка" and not self.full else None
        for kind in ("пишет", "читает"):
            for ln in sorted(wr[kind], key=self.link_order):
                nodes.append(self.src_node(kind, ln, seen))
        if e.kind in ENTRY_KINDS:
            nodes += self.caller_nodes(svc, key, seen, None)
        if e.kind == "колонка" and wr["через таблицу"]:  # кто пишет и читает таблицу целиком — задеты и они
            table = key.split(".", 1)[0]
            nodes.append(
                (
                    f"через таблицу {table}: {len(wr['через таблицу'])}",
                    [
                        self.src_node(ln.kind, ln, seen)
                        for ln in sorted(wr["через таблицу"], key=self.link_order)
                    ],
                )
            )
        lines = [f"{key} ({svc} · {e.kind})"]
        self.render(nodes, "", lines)
        if len(nodes) == 0:
            lines.append("└─ ссылок с видом нет: правка никого не задевает по цепочке")
        plain = [ln for ln in m.links_to(svc, key, ("указатель",))]
        self.out.append(lines[0])
        self.items(lines[1:], indent="")
        self.add(
            f"ещё упоминается без вида: {len(plain)}"
            + ("" if self.full or not plain else " — --all")
        )
        if self.full:
            self.items(
                [
                    f"{self.path(ln.src_file, ln.src_line)} · {ln.src}"
                    for ln in sorted(plain, key=self.link_order)
                ]
            )
        return 0

    def render(self, nodes: list[tuple], prefix: str, out: list[str]) -> None:
        for i, (label, ch) in enumerate(nodes):
            last = i == len(nodes) - 1
            out.append(prefix + ("└─ " if last else "├─ ") + label)
            self.render(ch, prefix + ("   " if last else "│  "), out)

    def src_node(self, kind: str, ln: Link, seen: set) -> tuple:
        m = self.m
        svc = m._service_of_file(ln.src_file)
        e = m.get(svc, ln.src)
        if e is None:
            return (f"{kind}: {ln.src}", [])
        if e.kind == "шаг":
            return self.step_node(kind, e, seen)
        if e.kind in ENTRY_KINDS:
            k = ("entry", svc, e.addr)
            if k in seen:
                return (f"{kind}: {svc}: {e.addr} ↺ выше", [])
            seen.add(k)
            return (
                f"{kind}: {svc}: {e.addr}",
                self.caller_nodes(svc or "", e.addr, seen, None),
            )
        return (f"{kind}: {svc}: {self.label(e)}", [])

    def step_node(self, kind: str, st: Entity, seen: set) -> tuple:
        k = ("step", st.addr)
        if k in seen:
            return (f"{kind}: {st.addr} «{st.title}» ↺ выше", [])
        seen.add(k)
        m = self.m
        proc = st.extra.get("process", "")
        end = (
            ("своя работа сервиса", [])
            if proc == "own"
            else (f"процесс: {self.process_title(proc)}", [])
        )
        ch = []
        for ln in m.links:
            if (
                ln.src != st.addr
                or ln.kind != "обрабатывает"
                or m._service_of_file(ln.src_file) != st.service
            ):
                continue
            ek = ("entry", ln.service, ln.key)
            who = sorted(
                {r.split(" — ")[0] for r in self.callers_rows(ln.service or "", ln.key)}
            )
            label = f"обрабатывает: {ln.service}: {ln.key} — " + (
                f"его зовёт {', '.join(who)}" if who else "никто не зовёт"
            )
            if ek in seen:
                ch.append((label + " ↺ выше", []))
                continue
            seen.add(ek)
            calls = [
                c["entity"]
                for c in m.callers(ln.service or "", ln.key)
                if c["via"] == "шаг"
                and c.get("entity")
                and c["entity"].extra.get("process") != proc
            ]
            sub = [self.call_node("зовёт", ce, seen) for ce in self.by_field(calls)]
            if len(sub) < len(calls):
                sub.append(
                    (f"ещё зовут, поле «{self.field}» не упоминают: {len(calls) - len(sub)} — --all", [])
                )
            ch.append((label, sub + [end]))
        if not ch:
            ch = [end]
        return (f"{kind}: {st.addr} «{st.title}»", ch)

    def by_field(self, ents: list[Entity]) -> list[Entity]:
        """В цепочке колонки — только упоминающие её имя; иначе все."""
        field = getattr(self, "field", None)
        return [x for x in ents if self.mentions(x, field)] if field else ents

    def call_node(self, kind: str, ce: Entity, seen: set) -> tuple:
        """Тот, кто зовёт: шаг — со своим процессом; метод или страница, которые зовут сами (строка «Справочник:» у
        точки входа без шагов), — как точка входа: кто зовёт её саму."""
        if ce.kind == "шаг":
            return self.step_node(kind, ce, seen)
        svc = ce.service or ""
        if ce.kind in ENTRY_KINDS:
            k = ("entry", svc, ce.addr)
            who = sorted({r.split(" — ")[0] for r in self.callers_rows(svc, ce.addr)})
            label = f"{kind}: {svc}: {ce.addr} — " + (f"его зовёт {', '.join(who)}" if who else "никто не зовёт")
            if k in seen:
                return (label + " ↺ выше", [])
            seen.add(k)
            return (label, self.caller_nodes(svc, ce.addr, seen, None))
        return (f"{kind}: {svc}: {self.label(ce)}", [])

    def caller_nodes(
        self, svc: str, key: str, seen: set, proc: str | None
    ) -> list[tuple]:
        m = self.m
        out = []
        steps = self.by_field([c["entity"] for c in m.callers(svc, key) if c["via"] == "шаг" and c.get("entity")])
        for c in m.callers(svc, key):
            if c["via"] == "шаг" and c.get("entity"):
                if c["entity"] in steps:
                    out.append(self.call_node("зовёт", c["entity"], seen))
            elif c["via"] == "вручную":
                out.append((f"вручную: {c['text']}", []))
            elif c["via"] == "стрелка":
                a = c["arrow"]
                out.append(
                    (
                        f"{a.sender}: процесс {self.process_title(a.process)}, стрелка {a.number}",
                        [],
                    )
                )
        hidden = sum(1 for c in m.callers(svc, key) if c["via"] == "шаг" and c.get("entity")) - len(steps)
        if hidden:
            out.append((f"ещё зовут, поле «{self.field}» не упоминают: {hidden} — --all", []))
        step_callers = {c["who"] for c in m.callers(svc, key) if c["via"] == "шаг"}
        for c in m.incoming(svc):
            if m.get(c.service, f"{c.addr}: {key}") and c.service not in step_callers:
                out.append((f"связь {c.addr} — шага, который зовёт, нет", []))
        return out or [("дальше никто не зовёт", [])]

    # «как будет» -------------------------------------------------------------------------------

    def change_card(self, num: str) -> int:
        if not self.chg:
            if (self.asis.root / "TOBE" / "README.md").is_file():
                self.add(
                    f"не нашлось: {num} — номера изменения ищутся в «как будет»: добавь --tobe"
                )
            else:
                self.add(f"не нашлось: {num} — изменения нет")
            return 1
        chg = self.chg
        if num.startswith("c-"):
            bs = [b for b in chg.blocks if b.number == num]
            if not bs:
                return self.not_found_change(num)
            b = bs[0]
            title = (
                b.head[1] if b.head else (b.owner[-1][1] if b.owner else "сводка файла")
            )
            self.add(
                f"{num} · правка · {b.kind} · {b.status}"
                + (f" · вместо {b.instead}" if b.instead else "")
                + f" — {title}"
            )
            self.add(f"md: {self.prefix}{b.file}:{b.line}")
            self.add(
                f"обёрнуто: {b.what}"
                + (f" ({', '.join(b.fields)})" if b.fields else "")
                + (f" ({', '.join(b.rows)})" if b.rows else "")
            )
            self.add(("уходит:" if b.kind == "уходит" else "станет:"))
            # новый файл — правка целиком: «станет» — сам файл без строк «Правка:» и «Почему:»
            body = world_lines(read_md(self.asis.root / b.file))[0] if b.what == "файл" else b.body
            for x in body:
                if x.strip():
                    self.add(f"  {x}")
            if b.kind == "меняется":
                was = self.was_lines(b)
                self.add(f"было ({self.prefix}{b.asis_file}):")
                for x in was or ["в «как есть» не найдено"]:
                    self.add(f"  {x}")
            self.add(f"Почему: {b.why}")
            tasks = [
                k
                for k, t in chg.tasks.items()
                if f"[[{num}]]" in str(t.get("Правки", ""))
            ]
            tests = [
                k
                for k, t in chg.tests.items()
                if f"[[{num}]]" in str(t.get("Проверяет", ""))
            ]
            if tasks:
                self.add(
                    "задачи: "
                    + " · ".join(f"{k} «{chg.tasks[k]['title']}»" for k in tasks)
                )
            if tests:
                self.add(
                    "тесты: "
                    + " · ".join(f"{k} «{chg.tests[k]['title']}»" for k in tests)
                )
            return 0
        if num.startswith(("k-", "t-")):
            rec = (chg.tasks if num.startswith("k-") else chg.tests).get(num)
            if not rec:
                return self.not_found_change(num)
            kind = "задача" if num.startswith("k-") else "тест"
            self.add(f"{num} · {kind} «{rec['title']}» · {rec['service']}")
            self.add(f"md: {self.prefix}TOBE/{rec['service']}/tasks.md:{rec['line']}")
        elif num.startswith("d-"):
            rec = chg.decisions.get(num)
            if not rec:
                return self.not_found_change(num)
            self.add(f"{num} · решение «{rec['title']}»")
            self.add(f"md: {rec['file']}:{rec['line']}")
        else:
            rec = next((w for w in chg.work if w.get("anchor") == num), None)
            if not rec:
                return self.not_found_change(num)
            self.add(f"{num} · блок «{rec['title']}»")
            lines = read_md(chg.dir / "blocks.md")
            n = next(
                (i for i, x in enumerate(lines, 1) if x.endswith(f"{{#{num}}}")), 1
            )
            self.add(f"md: {self.prefix}TOBE/blocks.md:{n}")
        for t in rec.get("text", []):
            self.add(f"  {t}")
        for k, v in rec.items():
            if k in ("title", "service", "line", "text", "anchor", "file"):
                continue
            self.add(f"  {k}: " + (" · ".join(v) if isinstance(v, list) else str(v)))
        return 0

    def not_found_change(self, num: str) -> int:
        chg = self.chg
        pool = (
            [b.number for b in chg.blocks]
            + list(chg.tasks)
            + list(chg.tests)
            + list(chg.decisions)
            + [w.get("anchor") or "" for w in chg.work]
        )
        near = difflib.get_close_matches(num, pool, n=5, cutoff=0.5)
        self.add(
            f"не нашлось: {num}" + (f"\n  похожие: {' · '.join(near)}" if near else "")
        )
        return 1

    def was_lines(self, b: Block) -> list[str]:
        """«Было» правки «меняется»: то же место в «как есть» (раздел, поля, строки, текст)."""
        p = self.asis.root / b.asis_file
        if not p.is_file():
            return []
        lines = read_md(p)
        if b.what not in ("раздел", "этап"):
            # вне блоков копия совпадает с «как есть»: «было» — строки «как есть» на месте метки правки, между теми же
            # соседними строками; поиск по разделу брал абзацы и поля всего раздела вместе с подразделами
            was = [x for x in as_was(read_md(self.asis.root / b.file)) if x.strip()]
            asis = [x for x in lines if x.strip()]
            ops = difflib.SequenceMatcher(None, was, asis, autojunk=False).get_opcodes()
            for tag, i1, i2, j1, j2 in ops:
                if tag != "equal" and "\0" + b.number in was[i1:i2]:
                    return asis[j1:j2]

        def section(head: tuple | None) -> tuple[int, int]:
            if head is None:
                end = next(
                    (i for i, x in enumerate(lines) if HEAD_RE.match(x)), len(lines)
                )
                return 0, end
            lv, title, anc = head
            for i, x in enumerate(lines):
                hm = HEAD_RE.match(x)
                if (
                    hm
                    and len(hm.group(1)) == lv
                    and (hm.group(3) or hm.group(2).strip()) == (anc or title)
                ):
                    end = next(
                        (
                            j
                            for j in range(i + 1, len(lines))
                            if (h := HEAD_RE.match(lines[j])) and len(h.group(1)) <= lv
                        ),
                        len(lines),
                    )
                    return i, end
            return -1, -1

        if b.what in ("раздел", "этап"):
            a, z = section(b.head)
            return [x for x in lines[a:z] if x.strip()] if a >= 0 else []
        a, z = section(b.owner[-1] if b.owner else None)
        if a < 0:
            return []
        body = lines[a:z]
        if b.what == "поля":
            out, cur = [], False
            for x in body:
                fm = FIELD_RE.match(x.strip())
                if fm:
                    cur = fm.group(1) in b.fields
                elif not x.strip().startswith("- "):
                    cur = False
                if cur:
                    out.append(x)
            return out
        if b.what == "строки":
            return [
                x
                for x in body
                if x.lstrip().startswith("|")
                and x.strip("| ").split("|")[0].strip() in b.rows
            ]
        return [  # текст — абзацы: без таблицы стрелок и пунктов списков, иначе «было» — весь раздел
            x
            for x in body
            if x.strip()
            and not HEAD_RE.match(x)
            and not FIELD_RE.match(x.strip())
            and not x.lstrip().startswith(("|", "- "))
        ]


def plural(n: int, one: str, few: str, many: str) -> str:
    """«1 метод», «2 метода», «5 методов»."""
    k = n % 100
    form = (
        many
        if 11 <= k <= 14
        else one
        if n % 10 == 1
        else few
        if 2 <= n % 10 <= 4
        else many
    )
    return f"{n} {form}"


def warn(msg: str) -> None:
    print(f"предупреждение: {msg}", file=sys.stderr)


def parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="find.py", description="Поиск по карте (шапка файла — подробно)."
    )
    ap.add_argument("query", nargs="*")
    ap.add_argument("--text", action="store_true")
    ap.add_argument("--code", action="store_true")
    ap.add_argument("--diff")
    ap.add_argument("--chain", action="store_true")
    ap.add_argument("--process", action="store_true")
    ap.add_argument("--service", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--tobe", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--root")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(
            stream, "reconfigure"
        ):  # в трубе на Windows иначе не UTF-8; перехват вывода в тесте — без него
            stream.reconfigure(encoding="utf-8")
    try:
        a = parse(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:
        return 2 if e.code else 0
    root = Path(a.root) if a.root else Path(__file__).resolve().parent.parent
    if not (root / "project" / "settings.yaml").is_file():
        print(
            f"ошибка: {root} — не корень карты (нет project/settings.yaml)",
            file=sys.stderr,
        )
        return 2
    modes = [
        x
        for x in ("text", "code", "chain", "process", "service", "list")
        if getattr(a, x)
    ]
    if len(modes) > 1:
        print(
            f"ошибка: режим один, а дано: {', '.join('--' + x for x in modes)}",
            file=sys.stderr,
        )
        return 2
    try:
        f = Finder(root, a.all, a.tobe)
        q = [f.normalize(x) for x in a.query]
        if a.text:
            rc = f.text_mode(q)
        elif a.code:
            rc = f.code_mode(a.query, a.diff)
        elif a.list:
            rc = f.list_mode(q)
        else:
            if not q:
                raise InputError("нужен ключ, шаг, связь или режим — шапка find.py")
            key = f.normalize(" ".join(a.query))
            if a.chain:
                rc = f.chain_mode(key)
            elif a.process:
                proc = f.find_process(key)
                rc = f.process_mode(proc) if proc else f.not_found(key)
            elif a.service:
                rc = f.service_mode(key)
            else:
                rc = f.key_mode(key)
    except InputError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2
    print("\n".join(f.out))
    return rc


if __name__ == "__main__":
    sys.exit(main())
