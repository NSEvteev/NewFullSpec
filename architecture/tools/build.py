"""Генератор страниц карты: собирает из md, фактов и yaml страницы html для человека и обзор системы для Claude.

Зачем. Карту пишут и читают в md; человеку её показывают страницы — у всех один каркас и одно оформление
(_shared/page.css, _shared/page.js). Всё производное — кто вызывает метод, как он работает, кто пишет и читает таблицу,
стрелки к шагу, номера стрелок, проблемы на месте — генератор считает сам из модели карты (mapmodel.py).
Руками страницы не правятся.

Кто зовёт и когда.
    python tools/build.py                     полная сборка всех страниц и обзора системы ASIS/README.md
    python tools/build.py --root <карта>      собрать другую карту: проверочную (tools/samples/good/architecture), пробную
    python tools/build.py --check             ничего не пишет: каждая страница совпадает со свежей сборкой (штамп не
                                              сравнивается), html без md нет; для проверки при коммите и CI
Пути — от корня репо; корень карты по умолчанию — папка над tools/.

Что читает. Модель карты (md, .facts.json, project/*.yaml) и git — только для даты текста в штампе.
Что пишет. Три вида страниц: ASIS/01_service-map.html (доска), ASIS/<сервис>/index.html (сервис, с его своей
работой из own.md), ASIS/_processes/<процесс>.html (процесс, со срезами всех участников из
ASIS/<сервис>/processes/<процесс>.md); ASIS/keys.js (ключи для поиска в шапке) и ASIS/README.md (обзор системы
для Claude).
md разложены по папкам сервисов, а страницу генератор собирает одну: у среза и своей работы своих страниц нет.
Идёт изменение (есть TOBE/README.md) — ещё «как будет»: TOBE/index.html (обложка), TOBE/01_service-map.html и
страницы задетых сервисов и процессов в TOBE/ — те же виды по миру «как будет» (ChangeModel в mapmodel.py), правки
подсвечены: новое — зелёным, меняется — жёлтым с «было», уходит — серым и зачёркнуто, на своём месте.
Удаляет html, которого нет в сборке.

Как устроены страницы (выбрано решающим по проверочной карте). Доска — схема на белом листе с кнопками и галочками видов
связей, справа процессы. Сервис — связи, точки входа и проблемы сводными таблицами (строка раскрывается в запись),
таблица базы — сворачиваемой записью с колонками. Процесс — схема последовательности на всю ширину, под ней стрелки
по этапам, ниже участники со своими шагами.

Коды выхода: 0 — собрано (или --check чист); 1 — ошибки разбора карты или --check нашёл расхождения; 2 — ошибка ввода.

Чего не делает: не вынимает факты (extract.py), не проверяет строки кода по запомненному тексту (live.py, .anchors.json),
не проверяет «как будет» между файлами (проверка №25 — отдельным слоем проверок).
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import markdown

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchors  # noqa: E402
import checks  # noqa: E402
import tobe_checks  # noqa: E402
from mapmodel import (  # noqa: E402
    HEAD_RE,
    KIND_RU,
    LINK_RE,
    Block,
    ChangeModel,
    Entity,
    MapModel,
    facts_settings,
    first_phrase,
    keys_in,
    split_key,
)

SEV_CLS = {"высокая": "high", "средняя": "mid", "низкая": "low"}
ARROW_CLASS = {
    "человек": "human",
    "запрос": "request",
    "переход браузера": "browser",
    "внешний провайдер": "external",
    "Redis": "redis",
    "файл": "file",
    "база": "db",
    "внутри сервиса": "inner",
}
LINK_ORDER = ("обрабатывает", "зовёт", "пишет", "читает")
IMP_CLASS = {"высокая": "high", "средняя": "mid", "низкая": "low"}
IMP_ORDER = {"высокая": 0, "средняя": 1, "низкая": 2}
STORE_KINDS = (
    "таблица",
    "колонка",
    "файл данных",
    "папка",
    "ключ Redis",
    "память браузера",
)
ENTRY_KINDS = ("метод", "функция", "страница", "команда")
NAMED_KINDS = (
    "проблема",
    "фоновая работа",
    "ограничитель",
    "другая настройка",
    "шаг",
    "этап",
    "процесс",
)
CALL_KINDS = ("запрос", "внешний провайдер")
ST_RU = {"changes": "меняется", "new": "новое", "gone": "уходит", "open": "открыто"}  # судьба узла доски «как будет»
STORE_ARROWS = ("база", "файл", "Redis")
FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wdth,wght@85..100,400..700"
    "&family=IBM+Plex+Mono:wght@400;500;600&display=swap"
)
STAMP_RE = re.compile(r"<!--stamp-->.*?<!--/stamp-->", re.S)
MD = markdown.Markdown(extensions=[])


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def shorten(text: str, limit: int = 160) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:—– ") + "…"


ANCHOR_PREFIX = {
    "метод": "m",
    "функция": "f",
    "страница": "pg",
    "команда": "cmd",
    "таблица": "t",
    "колонка": "c",
    "файл данных": "df",
    "папка": "dir",
    "ключ Redis": "rk",
    "память браузера": "bm",
    "настройка": "s",
    "другая настройка": "os",
    "постоянная": "k",
    "набор тестов": "ts",
    "связь": "l",
    "связь-метод": "lm",
    "правила прокси": "proxy",
}


@dataclass
class Sec:
    """Раздел страницы: якорь, заголовок, html; subs — пункты меню вида Б, cls — вид, в котором раздел есть."""

    sid: str
    title: str
    html: str
    count: int | None = None
    subs: list[tuple[str, str]] = field(default_factory=list)
    cls: str = ""


class Site:
    """Сборка: модель, пути страниц, ссылки между страницами, отрисовка текста."""

    def __init__(self, model: MapModel, change: ChangeModel | None = None, root: Path | None = None):
        """model — модель, по которой собираются страницы; change — идущее изменение: тогда model — мир «как будет»,
        страницы задетых сервисов и процессов — в TOBE/, с подсветкой правок; root — корень карты (у мира «как будет»
        своя временная папка, поэтому корень передаётся)."""
        self.m = model
        self.chg = change
        self.asis_m = change.asis if change else model
        self.root = (root or model.root).resolve()
        self.pages: dict[str, str] = {}  # путь от корня карты → html
        self.sources: dict[str, set[str]] = {}  # путь страницы → md-источники
        self.map_rel = self.root.relative_to(model.repo).as_posix()
        self._git_dates: dict[str, str] = {}
        self.svcset = set(model.services)
        self.tobe_svcs = set(change.services()) if change else set()
        self.tobe_procs = set(change.processes()) if change else set()
        if change:
            self._chg_index()

    # пути -----------------------------------------------------------------------------------------

    def service_page(self, svc: str) -> str:
        return f"{'TOBE' if svc in self.tobe_svcs else 'ASIS'}/{svc}/index.html"

    def board_page(self) -> str:
        return f"{'TOBE' if self.chg else 'ASIS'}/01_service-map.html"

    @staticmethod
    def step_anchor(st: Entity) -> str:
        """Якорь шага: срезы всех участников — на странице процесса (s-<сервис>-<якорь>), своя работа — на странице
        сервиса (own-<якорь>). Отдельных страниц у срезов и своей работы нет: md разложены по папкам сервисов,
        а страницу генератор собирает одну."""
        if st.extra.get("process") == "own":
            return f"own-{st.anchor}"
        return f"s-{st.service}-{st.anchor}"

    def step_page(self, st: Entity) -> str:
        proc = st.extra.get("process")
        return self.service_page(st.service) if proc == "own" else self.process_page(proc)

    def process_page(self, proc: str) -> str:
        return f"{'TOBE' if proc in self.tobe_procs else 'ASIS'}/_processes/{proc}.html"

    def rel_url(self, frm: str, to: str, anchor: str | None = None) -> str:
        url = os.path.relpath(to, os.path.dirname(frm) or ".").replace("\\", "/")
        if frm == to:
            url = ""
        return url + (f"#{anchor}" if anchor else "")

    def anchor(self, e: Entity) -> str:
        if e.kind in ("шаг", "этап"):
            return e.anchor
        if e.kind in ("проблема", "фоновая работа", "ограничитель") or (
            e.anchor and e.kind == "другая настройка"
        ):
            return e.anchor
        if e.kind == "связь":
            return "l-" + slug(e.extra.get("to", e.addr))
        if e.kind == "связь-метод":
            return "l-" + slug(e.extra.get("to", e.addr))
        return f"{ANCHOR_PREFIX.get(e.kind, 'x')}-{slug(e.addr)}"

    def url_entity(self, frm: str, e: Entity) -> str:
        if e.kind == "шаг":
            return self.rel_url(frm, self.step_page(e), self.step_anchor(e))
        if e.kind == "срез":
            return self.rel_url(
                frm, self.process_page(e.addr.split("/", 1)[1]), f"u-{e.service}"
            )
        if e.kind == "своя работа":
            return self.rel_url(frm, self.service_page(e.service), "own")
        if e.kind == "процесс":
            return self.rel_url(frm, self.process_page(e.addr))
        if e.kind == "этап":
            return self.rel_url(frm, self.process_page(e.parent), e.anchor)
        if e.kind == "колонка" and e.extra.get("facts_only"):
            return self.rel_url(frm, self.service_page(e.service), f"c-{slug(e.addr)}")
        return self.rel_url(frm, self.service_page(e.service), self.anchor(e))

    def ext_connection(self, ext: str, own: str | None = None) -> Entity | None:
        """Связь с внешним провайдером у того, кто его зовёт: своя — если есть, иначе первая."""
        cands = [
            c
            for s in self.m.services
            for c in self.m.connections(s)
            if c.extra.get("to") == ext
        ]
        for c in cands:
            if c.service == own:
                return c
        return cands[0] if cands else None

    def url_key(
        self, frm: str, service: str | None, key: str, own: str | None = None
    ) -> str | None:
        if service and service.startswith("external:"):
            c = self.ext_connection(service, own)
            return (
                self.rel_url(frm, self.service_page(c.service), self.anchor(c))
                if c
                else None
            )
        e = self.m.get(service, key) or (self.asis_m.get(service, key) if self.chg else None)
        return self.url_entity(frm, e) if e else None

    # имена ----------------------------------------------------------------------------------------

    def participant_name(self, p: str) -> str:
        if p == "human":
            return "человек"
        if p == "schedule":
            return "расписание"
        if p == "redis":
            return "Redis"
        if p.startswith("external:"):
            return self.m.external.get(p[9:], {}).get("name", p)
        if p.startswith("folder:"):
            return p[7:]
        return p

    def participant_class(self, p: str) -> str:
        if p in self.m.registry:
            return (
                "p-frontend"
                if self.m.registry[p].get("kind") == "frontend"
                else "p-service"
            )
        if p.startswith("external:"):
            return "p-external"
        if p in ("human", "schedule"):
            return "p-human"
        return "p-store"

    @staticmethod
    def short_title(e: Entity) -> str:
        if e.kind == "проблема" and ": " in e.title:
            return e.title.split(": ", 1)[0]
        return e.title

    @staticmethod
    def importance(e: Entity) -> str:
        return e.fields["Важность"].value if "Важность" in e.fields else ""

    def process_title(self, proc: str) -> str:
        if proc == "own":
            return "своя работа"
        return self.m.processes[proc].title if proc in self.m.processes else proc

    # текст ----------------------------------------------------------------------------------------

    def key_tag(self, frm: str, raw: str, own: str | None = None) -> str:
        """Ссылка [[ключ]]: человеческое имя вместо ключа там, где оно есть; цвет — по виду цели.
        В «как будет» [[c-…]] ведёт на место правки, [[d-…]], [[k-…]], [[t-…]], [[bN]] — на обложку."""
        if self.chg and re.fullmatch(r"(?:[cdkt]-[a-z0-9-]+|b\d+)", raw.strip()):
            return self.change_ref(frm, raw.strip())
        svc, k = split_key(raw, self.svcset)
        svc = svc or own
        url = self.url_key(frm, svc, k, own)
        title, tail = "", ""
        if svc and svc.startswith("external:"):
            label = f'<span class="ks">{esc(self.participant_name(svc))}</span>{esc(k)}'
            cls = "kt-ext"
        else:
            e = self.m.get(svc, k)
            prefix = f'<span class="ks">{esc(svc)}</span>' if svc and svc != own else ""
            if e and e.kind in NAMED_KINDS:
                label, cls = prefix + esc(self.short_title(e)), "kt-name"
                if e.kind == "проблема":
                    cls += " kt-prob"
                    title = f"{self.importance(e)}: {e.title}"
            else:
                label = prefix + esc(k)
                cls = (
                    "kt-store"
                    if e and e.kind in STORE_KINDS
                    else "kt-method"
                    if e and e.kind in ENTRY_KINDS
                    else ""
                )
                if e and e.kind == "постоянная" and "Значение" in e.fields:
                    tail = f'<span class="kv"> = {esc(e.fields["Значение"].value)}</span>'
        t = f' title="{esc(title)}"' if title else ""
        if url:
            return f'<a class="key {cls}" href="{esc(url)}"{t}>{label}{tail}</a>'
        return f'<span class="key ext {cls}"{t}>{label}{tail}</span>'

    def inline(
        self,
        frm: str,
        text: str,
        own: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> str:
        """Строка md → html: [[ключ]] — ссылка на раздел, ссылки md → html, `код`, жирный."""
        keys: list[str] = []

        def key_sub(m: re.Match) -> str:
            keys.append(self.key_tag(frm, m.group(1), own))
            return f"KEYPH{len(keys) - 1}ZZ"

        text = LINK_RE.sub(key_sub, text)
        text = re.sub(
            r"\]\(([^)\s#]+?\.md)(?:#([a-z0-9-]+))?\)",
            lambda m: f"]({self.md_url(frm, own, m.group(1), m.group(2))})",
            text,
        )
        out = MD.reset().convert(text)
        out = re.sub(r"^<p>(.*)</p>$", r"\1", out, flags=re.S)
        for i, tag in enumerate(keys):
            out = out.replace(f"KEYPH{i}ZZ", tag)
        for ph, tag in (extra or {}).items():
            out = out.replace(ph, tag)
        return out

    def md_url(self, frm: str, own: str | None, target: str, anchor: str | None) -> str:
        """Ссылка md → место на странице. Путь md — от папки файла: у сервиса ASIS/<сервис>/, у процесса ASIS/_processes/.
        own.md#x → страница сервиса, шаг own-x; processes/<п>.md#x (срез) → страница процесса, шаг s-<сервис>-x;
        другой md сервиса → страница сервиса; md процесса → страница процесса."""
        base = f"ASIS/{own}" if own else "ASIS/_processes"
        p = os.path.normpath(os.path.join(base, target)).replace("\\", "/")
        parts = p.split("/")
        if len(parts) == 3 and parts[0] == "ASIS" and parts[1] == "_processes":
            return self.rel_url(frm, p[:-3] + ".html", anchor)
        if len(parts) >= 3 and parts[0] == "ASIS":
            svc = parts[1]
            if parts[2] == "own.md":
                return self.rel_url(frm, self.service_page(svc), f"own-{anchor}" if anchor else "own")
            if parts[2] == "processes" and len(parts) == 4:
                proc = parts[3][:-3]
                return self.rel_url(
                    frm, self.process_page(proc), f"s-{svc}-{anchor}" if anchor else f"u-{svc}"
                )
            return self.rel_url(frm, self.service_page(svc), anchor)
        return self.rel_url(frm, p[:-3] + ".html", anchor)

    def plain_text(self, text: str) -> str:
        """Текст без разметки — для подсказок: [[ключ]] — именем, обратные кавычки убраны."""

        def sub(m: re.Match) -> str:
            svc, k = split_key(m.group(1), self.svcset)
            if svc and svc.startswith("external:"):
                return f"{self.participant_name(svc)}: {k}"
            e = self.m.get(svc, k) if svc else None
            return self.short_title(e) if e and e.kind in NAMED_KINDS else k

        return LINK_RE.sub(sub, text).replace("`", "")

    def plain(self, text: str) -> str:
        """Подпись внутри ссылки: без вложенных ссылок — [[ключ]] становится именем, `код` — кодом."""

        def sub(m: re.Match) -> str:
            svc, k = split_key(m.group(1), self.svcset)
            if svc and svc.startswith("external:"):
                return f"{self.participant_name(svc)}: {k}"
            return k

        s = esc(LINK_RE.sub(sub, text))
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", s)

    def blocks(
        self, frm: str, lines: list[str], own: str | None = None, cls: str = ""
    ) -> str:
        """Абзацы и пункты списков текста раздела."""
        out, items = [], []
        for t in lines:
            if t.startswith("- "):
                items.append(f"<li>{self.inline(frm, t[2:], own)}</li>")
                continue
            if items:
                out.append(f"<ul>{''.join(items)}</ul>")
                items = []
            out.append(
                f"<p{f' class={cls!r}' if cls else ''}>{self.inline(frm, t, own)}</p>"
            )
        if items:
            out.append(f"<ul>{''.join(items)}</ul>")
        return "".join(out)

    def field_html(
        self, frm: str, e: Entity, name: str, label: str | None = None
    ) -> str:
        f = e.fields.get(name)
        if not f:
            return ""
        val = self.inline(frm, f.value, e.service) if f.value else ""
        lst = "".join(f"<li>{self.inline(frm, x, e.service)}</li>" for x in f.items)
        body = val + (f"<ul>{lst}</ul>" if lst else "")
        fb = self.field_block(e, name) if self.chg else None
        cls, was = "", ""
        if fb:
            cls = f" chg {self.KIND_CLS[fb.kind]}"
            old = self.asis_field(frm, e, name) if fb.kind == "меняется" else None
            if old is not None:
                was = f'<div class="was"><span class="lbl">было</span>{old}</div>'
        return f'<div class="fld{cls}"><dt>{esc(label or name)}</dt><dd>{body}{was}</dd></div>'

    def code_list(self, e: Entity, limit: int = 3) -> str:
        refs = [
            f'<a class="cref" href="#" data-p="{esc(r.path)}" data-l="{r.line}" title="{esc(r.path)}:{r.line}">'
            f"{esc(Path(r.path).name)}:{r.line}</a>"
            for r in e.code
        ]
        refs += [
            f'<span class="live" title="живой источник">{esc(x)}</span>' for x in e.live
        ]
        if not refs:
            return ""
        head, tail = refs[:limit], refs[limit:]
        more = (
            f'<details class="more"><summary>ещё {len(tail)}</summary>{" ".join(tail)}</details>'
            if tail
            else ""
        )
        return " ".join(head) + more

    def code_refs(self, e: Entity, limit: int = 3) -> str:
        lst = self.code_list(e, limit)
        return (
            f'<div class="code-refs"><span class="lbl">код</span> {lst}</div>'
            if lst
            else ""
        )

    def md_link(self, e: Entity) -> str:
        if not e.line:
            return ""
        file, line = e.file, e.line
        if self.chg and file in self.chg.copies and self.m is self.chg.world:
            # md «как будет» — копия в TOBE/: строка мира → строка копии
            lm = self.chg.line_map.get(file, [])
            file, line = self.chg.copies[file], lm[line - 1] if 0 < line <= len(lm) else line
        return (
            f'<a class="md-src" href="#" data-p="{esc(self.map_rel)}/{esc(file)}" data-l="{line}" '
            f'title="{esc(file)}:{line}">md</a>'
        )

    def tools(self, e: Entity, probs: list[Entity] | None = None, frm: str = "") -> str:
        """Правый край заголовка записи: отметки проблем, код, md."""
        pm = self.pm_html(frm, probs or []) if frm else ""
        lst = self.code_list(e, 2)
        return f'<span class="e-tools">{pm}{lst}{self.md_link(e)}</span>'

    # ссылки и отметки -----------------------------------------------------------------------------

    def touch_html(self, frm: str, links: list, tag: str = "div") -> str:
        """Ссылки с видом, по глаголу: «пишет orders, orders.status · читает MAX_ITEMS»."""
        groups: dict[str, list[str]] = {}
        for ln in links:
            t = self.key_tag(frm, ln.raw, self.m._service_of_file(ln.src_file))
            lst = groups.setdefault(ln.kind, [])
            if t not in lst:
                lst.append(t)
        parts = [
            f'<span><span class="tv">{esc(k)}</span>{", ".join(groups[k])}</span>'
            for k in LINK_ORDER
            if groups.get(k)
        ]
        return f'<{tag} class="touch">{"".join(parts)}</{tag}>' if parts else ""

    def own_links(self, e: Entity) -> list:
        return [
            ln
            for ln in self.m.links
            if ln.src == e.addr
            and ln.kind in LINK_ORDER
            and self.m._service_of_file(ln.src_file) == e.service
        ]

    def refs_of(self, frm: str, e: Entity) -> str:
        return self.touch_html(frm, self.own_links(e))

    def step_ref(self, frm: str, st: Entity, with_proc: bool = True) -> str:
        """Ссылка на шаг коротким именем; процесс — серым перед ним, первая фраза — подсказкой."""
        pr = (
            f'<span class="pr">{esc(self.process_title(st.extra.get("process", "")))}</span>'
            if with_proc
            else ""
        )
        return (
            f'<span class="stepref">{pr}<a href="{esc(self.url_entity(frm, st))}" '
            f'title="{esc(self.plain_text(st.first_phrase()))}">{esc(st.title)}</a></span>'
        )

    def ent_ref(self, frm: str, e: Entity, with_proc: bool = True) -> str:
        if e.kind == "шаг":
            return self.step_ref(frm, e, with_proc)
        if e.kind in ("связь", "связь-метод"):
            label = f"связь → {esc(self.participant_name(e.extra.get('to', '')))}"
        elif e.kind in NAMED_KINDS:
            label = esc(self.short_title(e))
        else:
            label = f"<code>{esc(e.addr)}</code>"
        return f'<a href="{esc(self.url_entity(frm, e))}">{label}</a>'

    def arrow_link(self, frm: str, a) -> str:
        tip = f"{self.participant_name(a.sender)} → {self.participant_name(a.receiver)}: {self.plain_text(a.what)}"
        return (
            f'<a class="an" href="{esc(self.rel_url(frm, self.process_page(a.process), "a-" + a.id))}" '
            f'title="{esc(tip)}">{esc(a.number)}</a>'
        )

    def step_arrows(
        self,
        st: Entity,
        key_svc: str | None = None,
        key: str | None = None,
        kinds: tuple[str, ...] | None = None,
        store: bool = False,
    ) -> list:
        """Стрелки процесса, в чьём «внутри» стоит шаг; с ключом — те, у кого он в «как» (у хранилища — та же таблица)."""
        if st.kind != "шаг":
            return []
        out = []
        for a in self.m.arrows_to_step(st):
            if kinds and a.kind not in kinds:
                continue
            if key is not None:
                refs = [split_key(r, self.svcset) for r in LINK_RE.findall(a.how)]
                if not any(
                    s == key_svc
                    and (
                        k == key
                        or (store and k.split(".", 1)[0] == key.split(".", 1)[0])
                    )
                    for s, k in refs
                ):
                    continue
            out.append(a)
        return out

    def problems_in(self, e: Entity) -> list[Entity]:
        """Проблемы, на которые ссылается раздел: поля («Проблемы:», «При отказе:»…) и текст."""
        out: list[Entity] = []
        texts = (
            [f.value for f in e.fields.values()]
            + [x for f in e.fields.values() for x in f.items]
            + e.text
        )
        for t in texts:
            for raw in LINK_RE.findall(t):
                svc, k = split_key(raw, self.svcset)
                p = self.m.get(svc or e.service, k)
                if p and p.kind == "проблема" and p not in out:
                    out.append(p)
        return out

    def entry_problems(self, svc: str, e: Entity) -> list[Entity]:
        out = self.problems_in(e)
        for st in self.m.steps_handling(svc, e.addr):
            for p in self.problems_in(st):
                if p not in out:
                    out.append(p)
        return out

    def pm_html(self, frm: str, probs: list[Entity], label: bool = False) -> str:
        """Красные отметки проблем: высокая — залитый кружок, средняя — кольцо, низкая — серое кольцо."""
        out = []
        for p in sorted(probs, key=lambda p: IMP_ORDER.get(self.importance(p), 3)):
            imp = self.importance(p)
            out.append(
                f'<a class="pm imp-{IMP_CLASS.get(imp, "low")}" href="{esc(self.url_entity(frm, p))}" '
                f'title="{esc(imp)}: {esc(p.title)}" aria-label="проблема {esc(imp)}">{esc(imp) if label else ""}</a>'
            )
        return "".join(out)

    def legend(self, kinds: list[str], extra: str = "") -> str:
        items = "".join(
            f'<span class="lg-i k-{ARROW_CLASS.get(k, "inner")}"><svg width="36" height="10" aria-hidden="true">'
            f'<line class="s-line" x1="1" y1="5" x2="35" y2="5"/></svg>{esc(k)}</span>'
            for k in kinds
        )
        return f'<div class="legend">{items}{extra}</div>'

    # правки «как будет» -------------------------------------------------------------------

    KIND_CLS = {"новое": "chg-new", "меняется": "chg-mod", "уходит": "chg-gone"}

    @staticmethod
    def _ek(e: Entity) -> tuple:
        return (e.service, e.addr)

    @staticmethod
    def _find(model: MapModel, file: str, lv: int, title: str, anchor: str | None) -> Entity | None:
        """Раздел файла по заголовку: якорь, если есть, иначе текст заголовка; уровень 1 — сам процесс."""
        for e in model.entities.values():
            if e.file != file:
                continue
            if lv == 1 and e.kind == "процесс":
                return e
            if e.level == lv and ((anchor and e.anchor == anchor) or (not anchor and e.title == title)):
                return e
        return None

    def _chg_index(self) -> None:
        """Где на страницах какая правка: раздел целиком, поля раздела, строки стрелок, этап."""
        self.chg_sec: dict[tuple, Block] = {}
        self.chg_fields: dict[tuple, list[Block]] = {}
        self.chg_rows: dict[tuple, Block] = {}
        self.gone: list[tuple[Entity, Block]] = []  # разделы «как есть», которые уходят целиком
        for b in self.chg.blocks:
            if b.what in ("раздел", "этап"):
                model = self.asis_m if b.kind == "уходит" else self.m
                # раздел блока и все разделы внутри него: новая группа настроек — вместе с её постоянными
                for line in b.body:
                    hm = HEAD_RE.match(line)
                    if not hm:
                        continue
                    e = self._find(model, b.asis_file, len(hm.group(1)), hm.group(2).strip(), hm.group(3))
                    if e:
                        self.chg_sec[self._ek(e)] = b
                        if b.kind == "уходит":
                            self.gone.append((e, b))
                if b.what == "этап":
                    proc = Path(b.asis_file).stem
                    for line in b.body:
                        cells = [c.strip() for c in line.strip().strip("|").split("|")]
                        if line.lstrip().startswith("|") and cells and cells[0] not in ("id",) and not re.match(r"^:?-{3,}", cells[0]):
                            self.chg_rows[(proc, cells[0])] = b
            elif b.what in ("поля", "текст"):
                e = self.block_owner(b)
                if e:
                    self.chg_fields.setdefault(self._ek(e), []).append(b)
            elif b.what == "строки":
                proc = Path(b.asis_file).stem
                for rid in b.rows:
                    self.chg_rows[(proc, rid)] = b

    def block_owner(self, b: Block) -> Entity | None:
        """Раздел, чьи поля или текст обёрнуты правкой; правка до первого заголовка — сам документ."""
        if b.owner:
            return self._find(self.m, b.asis_file, *b.owner[-1]) or self._find(self.asis_m, b.asis_file, *b.owner[-1])
        for model in (self.m, self.asis_m):
            for e in model.entities.values():
                if e.file == b.asis_file and e.line == 1 and e.kind in ("документ", "своя работа", "срез", "процесс"):
                    return e
        return None

    def cb(self, e: Entity | None) -> Block | None:
        """Правка раздела целиком — новое, меняется, уходит."""
        return self.chg_sec.get(self._ek(e)) if self.chg and e is not None else None

    def cfb(self, e: Entity | None) -> list[Block]:
        """Правки полей раздела."""
        return self.chg_fields.get(self._ek(e), []) if self.chg and e is not None else []

    def cc(self, e: Entity | None) -> str:
        """Класс контейнера: подложка правки раздела; правки только в полях — полоса слева."""
        b = self.cb(e)
        if b:
            return f" chg {self.KIND_CLS[b.kind]}"
        return " chg-part" if self.cfb(e) else ""

    def ctag(self, b: Block) -> str:
        """Метка правки: вид, номер, статус; «почему» — подсказкой."""
        return (
            f'<span class="ctag {self.KIND_CLS[b.kind]}" title="{esc(self.plain_text(b.why))}">'
            f"{esc(b.kind)} · {esc(b.number)} · {esc(b.status)}</span>"
        )

    def ct(self, e: Entity | None) -> str:
        """Метки всех правок раздела: его собственная и правки его полей."""
        out = []
        b = self.cb(e)
        if b:
            out.append(self.ctag(b))
        for fb in self.cfb(e):
            if fb.number not in {x.number for x in ([b] if b else [])}:
                out.append(self.ctag(fb))
        return "".join(out)

    def field_block(self, e: Entity, name: str) -> Block | None:
        for b in self.cfb(e):
            if name in b.fields:
                return b
        return None

    def asis_field(self, frm: str, e: Entity, name: str) -> str | None:
        """Значение поля «как есть» — для «было»."""
        ae = self.asis_m.get(e.service, e.addr)
        f = ae.fields.get(name) if ae else None
        if not f:
            return None
        val = self.inline(frm, f.value, e.service) if f.value else ""
        lst = "".join(f"<li>{self.inline(frm, x, e.service)}</li>" for x in f.items)
        return val + (f"<ul>{lst}</ul>" if lst else "")

    def gone_fields(self, frm: str, e: Entity) -> str:
        """Поля, которые уходят: из «как есть», серым и зачёркнуто."""
        out = []
        for b in self.cfb(e):
            if b.kind != "уходит":
                continue
            for name in b.fields:
                old = self.asis_field(frm, e, name)
                if old is not None:
                    out.append(
                        f'<div class="fld chg chg-gone" title="{esc(b.number)}"><dt>{esc(name)}</dt><dd>{old}</dd></div>'
                    )
        return "".join(out)

    def chg_box(self, frm: str, e: Entity) -> str:
        """Под заголовком раздела: «почему» его правок; у «меняется» раздела целиком — «было» его текстом."""
        if not self.chg:
            return ""
        items = []
        b = self.cb(e)
        blocks = ([b] if b else []) + [x for x in self.cfb(e) if not b or x.number != b.number]
        for x in blocks:
            was = ""
            if x.kind == "меняется" and (x is b or x.what == "текст"):
                ae = self.asis_m.get(e.service, e.addr)
                if ae and ae.text:
                    was = f'<div class="was"><span class="lbl">было</span>{self.blocks(frm, ae.text, e.service)}</div>'
            items.append(
                f'<div class="cbox {self.KIND_CLS[x.kind]}">{self.ctag(x)}'
                f'<span class="why"><span class="lbl">почему</span>{self.inline(frm, x.why, e.service)}</span>{was}</div>'
            )
        return "".join(items)

    def gone_of(self, svc: str | None, kinds: tuple[str, ...]) -> list[tuple[Entity, Block]]:
        """Разделы «как есть» этих видов, которые уходят целиком."""
        return [(e, b) for e, b in self.gone if e.service == svc and e.kind in kinds] if self.chg else []

    def block_url(self, frm: str, b: Block) -> str | None:
        """Где на страницах «как будет» стоит правка: раздел, раздел с правкой полей, строка стрелки, этап."""
        if b.what in ("раздел", "этап"):
            model = self.asis_m if b.kind == "уходит" else self.m
            e = self._find(model, b.asis_file, *b.head)
            return self.url_entity(frm, e) if e else None
        if b.what in ("поля", "текст"):
            e = self.block_owner(b)
            return self.url_entity(frm, e) if e else None
        if b.what == "строки" and b.rows:
            return self.rel_url(frm, self.process_page(Path(b.asis_file).stem), f"a-{b.rows[0]}")
        return None

    def change_ref(self, frm: str, ref: str) -> str:
        """[[c-…]] — на место правки; [[d-…]], [[k-…]], [[t-…]], [[bN]] — на обложку изменения."""
        cover = "TOBE/index.html"
        if ref.startswith("c-"):
            b = next((x for x in self.chg.blocks if x.number == ref), None)
            url = self.block_url(frm, b) if b else None
            label = f"{b.kind} · {ref}" if b else ref
            cls = self.KIND_CLS.get(b.kind, "") if b else ""
        elif ref.startswith("d-"):
            d = self.chg.decisions.get(ref)
            url, label, cls = self.rel_url(frm, cover, ref), (d["title"] if d else ref), ""
        elif ref.startswith("k-"):
            t = self.chg.tasks.get(ref)
            url, label, cls = self.rel_url(frm, cover, ref), (t["title"] if t else ref), ""
        elif ref.startswith("t-"):
            t = self.chg.tests.get(ref)
            url, label, cls = self.rel_url(frm, cover, ref), (t["title"] if t else ref), ""
        else:
            w = next((x for x in self.chg.work if x.get("anchor") == ref), None)
            url, label, cls = self.rel_url(frm, cover, ref), (f"Б{ref[1:]}" + (f" {w['title']}" if w else "")), ""
        kind = "cref-chg" if ref.startswith("c-") else "cref-name"
        if url:
            return f'<a class="{kind} {cls}" href="{esc(url)}">{esc(label)}</a>'
        return f'<span class="{kind} {cls}">{esc(label)}</span>'

    def tobe_bar(self, path: str, sources: set[str]) -> str:
        """Полоса страницы «как будет»: чьё изменение, сколько правок здесь, где та же страница «как есть»."""
        if not self.chg or path == "TOBE/index.html":
            return ""
        n = sum(1 for b in self.chg.blocks if b.asis_file in sources)
        asis = path.replace("TOBE/", "ASIS/", 1)
        asis_link = (
            f' · <a href="{esc(self.rel_url(path, asis))}">эта страница как есть</a>'
            if (self.root / asis).with_suffix(".html").exists() or asis.endswith(".html")
            else ""
        )
        return (
            f'<div class="tobe-bar page"><span class="tb-k">как будет</span>'
            f'<a href="{esc(self.rel_url(path, "TOBE/index.html"))}">{esc(self.chg.title)}</a>'
            f' · правок на странице: <b>{n}</b>{asis_link}'
            '<span class="tb-l"><span class="ctag chg-new">новое</span><span class="ctag chg-mod">меняется</span>'
            '<span class="ctag chg-gone">уходит</span></span></div>'
        )

    # страницы «как будет» -------------------------------------------------------------------------

    def build_change(self) -> None:
        """«Как будет»: страницы задетых сервисов и процессов, доска, обложка — в TOBE/."""
        for svc in [s for s in self.m.services if s in self.tobe_svcs]:
            self.build_service(svc)
        for proc in sorted(self.tobe_procs):
            if proc in self.m.processes:
                self.build_process(proc)
        self.build_board()
        self.build_cover()

    def build_cover(self) -> None:
        """Обложка изменения TOBE/index.html: что и зачем, вопросы решающему, решения, что меняется, блоки, судьбы."""
        c, path = self.chg, "TOBE/index.html"
        weak = ("открыто", "предложено")
        by_kind: dict[str, int] = {}
        for b in c.blocks:
            by_kind[b.kind] = by_kind.get(b.kind, 0) + 1
        questions = []
        for w in c.req_weak:  # пункты требований «открыто» и «предложено» — с якорем и без
            d = c.decisions.get(w["anchor"] or "")
            name = f'<a href="#{esc(w["anchor"])}">{esc(d["title"])}</a>' if d else esc(w["title"])
            questions.append(
                f'<tr><td>{name}<span class="kind-l">{esc(w["file"])}:{w["line"]}</span></td>'
                f'<td>{esc(w["status"])}</td><td>{self.blocks(path, d.get("text", [])) if d else ""}</td></tr>'
            )
        for b in c.blocks:
            if b.status in weak:
                url = self.block_url(path, b)
                where = f'<a href="{esc(url)}">{esc(b.number)}</a>' if url else esc(b.number)
                questions.append(
                    f'<tr><td>{where} {self.ctag(b)}<span class="kind-l">'
                    f'{esc(b.file)}</span></td><td>{esc(b.status)}</td><td>{self.inline(path, b.why)}</td></tr>'
                )
        for nid, n in (c.board or {}).items():
            if (n or {}).get("status") == "open":
                questions.append(
                    f'<tr><td>{esc(nid)}<span class="kind-l">узел доски</span></td><td>открыто</td>'
                    f'<td>{esc((n or {}).get("why", ""))}</td></tr>'
                )
        approved = c.cover.get("Описание утверждено")
        rows = [
            ("Ветка", f"<code>{esc(c.cover['Ветка'])}</code>" if c.cover.get("Ветка") else ""),
            ("PR", esc(c.cover.get("PR", "")) if c.cover.get("PR") else ""),
            ("Описание утверждено", esc(approved) if approved else '<span class="muted">ждёт «да»</span>'),
        ]
        facts = "".join(f"<div><dt>{esc(k)}</dt><dd>{v}</dd></div>" for k, v in rows if v)
        nums = (
            '<ul class="nums">'
            + "".join(
                f'<li><span class="ctag {self.KIND_CLS[k]}">{esc(k)}</span><b>{by_kind[k]}</b></li>'
                for k in ("новое", "меняется", "уходит")
                if by_kind.get(k)
            )
            + (
                f'<li><a href="#questions"><b>{len(questions)}</b> {plural(len(questions), "вопрос", "вопроса", "вопросов")} к {esc(self.decider_to())}</a></li>'
                if questions
                else f'<li class="muted">вопросов к {esc(self.decider_to())} нет</li>'
            )
            + f'<li><a href="#work"><b>{len(c.work)}</b> {plural(len(c.work), "блок", "блока", "блоков")} работ</a></li></ul>'
        )
        head = self.head(
            esc(c.title),
            "изменение · как будет",
            f'<div class="h-sum">{self.blocks(path, c.intro)}</div><dl class="hfacts">{facts}</dl>{nums}',
        )
        # решения
        dec = []
        for anchor, d in c.decisions.items():
            refs = [b for b in c.blocks if f"[[{anchor}]]" in b.why]
            # слова решающего стоят в тексте пункта требований; ярлык — статус, дата и где пункт
            tag = " · ".join(x for x in (d.get("Статус"), d.get("Когда"), f"{d['file']}:{d['line']}") if x)
            dec.append(
                f'<article class="entry" id="{esc(anchor)}"><header class="e-head"><h3>{esc(d["title"])}</h3>'
                f'<span class="tag">{esc(tag)}</span></header>'
                f'<div class="e-text">{self.blocks(path, d.get("text", []))}</div>'
                + (
                    '<p class="refs-chg"><span class="lbl">правки</span>'
                    + " ".join(self.change_ref(path, b.number) for b in refs)
                    + "</p>"
                    if refs
                    else ""
                )
                + "</article>"
            )
        # что меняется — по страницам
        pages: dict[str, list[Block]] = {}
        for b in c.blocks:
            parts = b.asis_file.split("/")
            page = (
                self.process_page(parts[2][:-3]) if parts[1] == "_processes"
                else self.process_page(parts[3][:-3]) if len(parts) == 4 and parts[2] == "processes"
                else self.service_page(parts[1])
            )
            pages.setdefault(page, []).append(b)
        what = []
        for page, bs in pages.items():
            name = page.split("/")[1] if "/_processes/" not in page else (
                self.m.processes[Path(page).stem].title if Path(page).stem in self.m.processes else Path(page).stem
            )
            what.append(
                f'<h3 class="sub"><a href="{esc(self.rel_url(path, page))}">{esc(name)}</a> '
                f'<span class="cnt">{len(bs)} {plural(len(bs), "правка", "правки", "правок")}</span></h3>'
                '<table class="grid"><thead><tr><th style="width:24%">правка</th><th style="width:22%">где</th>'
                "<th>почему</th></tr></thead><tbody>"
                + "".join(
                    f"<tr><td>{self.ctag(b)}</td>"
                    f"<td>{self.change_ref(path, b.number)}<span class=\"kind-l\">{esc(b.file)}</span></td>"
                    f"<td>{self.inline(path, b.why)}</td></tr>"
                    for b in bs
                )
                + "</tbody></table>"
            )
        # блоки работ, задачи, тесты
        work = []
        for w in c.work:
            tasks = []
            for k in keys_in(w.get("Задачи", "")):
                t = c.tasks.get(k)
                if not t:
                    tasks.append(f"<li>{esc(k)} — задачи нет</li>")
                    continue
                tests = [
                    f'<li id="{esc(x)}">{esc(c.tests[x]["title"])} <span class="muted">{esc(c.tests[x].get("Набор", ""))} · '
                    f'{esc(c.tests[x].get("Вид", ""))}</span></li>'
                    for x in keys_in(t.get("Тесты", ""))
                    if x in c.tests
                ]
                tasks.append(
                    f'<li id="{esc(k)}"><b>{esc(t["title"])}</b> <span class="muted">{esc(t["service"])}</span>'
                    f'<div class="e-text">{self.blocks(path, t.get("text", []), t["service"])}</div>'
                    f'<p class="refs-chg"><span class="lbl">правки</span>{" ".join(self.change_ref(path, x) for x in keys_in(t.get("Правки", "")))}</p>'
                    + (f'<ul class="plain tests">{"".join(tests)}</ul>' if tests else "")
                    + "</li>"
                )
            done = w.get("Сделано")
            work.append(
                f'<article class="entry" id="{esc(w.get("anchor") or "")}"><header class="e-head">'
                f'<h3>Б{esc((w.get("anchor") or "b?")[1:])}. {esc(w["title"])}</h3>'
                f'<span class="tag">{esc(w.get("Где", ""))}'
                + (f" · после {' '.join(esc('Б' + x[1:]) for x in keys_in(w.get('После', '')))}" if w.get("После") else "")
                + "</span>"
                + (f'<span class="tag done">сделано: {esc(done)}</span>' if done else "")
                + "</header>"
                f'<div class="e-text">{self.blocks(path, w.get("text", []))}</div>'
                f'<dl class="flds"><div class="fld"><dt>Готово, когда</dt><dd>{self.inline(path, w.get("Готово, когда", ""))}</dd></div></dl>'
                f'<ol class="plain tasks">{"".join(tasks)}</ol></article>'
            )
        fates = "".join(f"<li>{self.inline(path, x)}</li>" for x in c.fates)
        # остальные высокие проблемы задетых сервисов — «остаются, не задеты»
        fated = {k for x in c.fates for k in LINK_RE.findall(x)}
        rest = [  # сервисы — по имени: множество без порядка давало страницу, разную от запуска к запуску
            e
            for s in sorted(self.tobe_svcs)
            for e in self.asis_m.entries(s, "проблема")
            if self.importance(e) == "высокая" and f"{s}: {e.addr}" not in fated and e.addr not in fated
        ]
        secs = [
            self.section(
                "questions",
                f"Вопросы к {self.decider_to()}",
                '<table class="grid"><thead><tr><th style="width:26%">что</th><th style="width:12%">статус</th>'
                f'<th>вопрос или предложение</th></tr></thead><tbody>{"".join(questions)}</tbody></table>'
                if questions
                else "",
                len(questions) or None,
            ),
            self.section("decisions", "Решения", "".join(dec), len(dec)),
            self.section("changes", "Что меняется", "".join(what), len(c.blocks)),
            self.section("work", "Блоки работ", "".join(work), len(work)),
            self.section(
                "fates",
                "Судьбы проблем",
                (f'<ul class="plain">{fates}</ul>' if fates else "")
                + (
                    '<h3 class="sub">Остаются, не задеты</h3><ul class="plain">'
                    + "".join(
                        f'<li><a href="{esc(self.url_entity(path, e))}">{esc(e.service)}: {esc(self.short_title(e))}</a></li>'
                        for e in rest
                    )
                    + "</ul>"
                    if rest
                    else ""
                ),
            ),
            self.section(
                "untouched",
                "Не задеты",
                f'<ul class="plain">{"".join(f"<li>{self.inline(path, x)}</li>" for x in c.untouched)}</ul>'
                if c.untouched
                else "",
            ),
            self.section(
                "consequences",
                "Последствия для процессов",
                f'<ul class="plain">{"".join(f"<li>{self.inline(path, x)}</li>" for x in c.consequences)}</ul>'
                if c.consequences
                else "",
            ),
        ]
        files = ["TOBE/README.md", "TOBE/blocks.md"] + sorted(
            f"TOBE/{p.relative_to(self.chg.dir).as_posix()}" for p in self.chg.dir.glob("*/tasks.md")
        )
        self.pages[path] = self.frame(
            path,
            title=f"Изменение: {c.title}",
            here=("cover", None),
            stamp=[f"текст {dt.date.today().isoformat()}"],
            head=head,
            sections=secs,
            sources=set(files),
        )

    # каркас ---------------------------------------------------------------------------------------

    def git_date(self, files: list[str]) -> str:
        """Дата текста — последняя правка md по git; незакоммиченный md — сегодня."""
        dates = []
        for f in files:
            if f in self._git_dates:
                dates.append(self._git_dates[f])
                continue
            path = self.root / f
            d = ""
            try:
                dirty = subprocess.run(
                    ["git", "status", "--porcelain", "--", str(path)],
                    capture_output=True,
                    text=True,
                    cwd=self.m.repo,
                    timeout=10,
                ).stdout.strip()
                if not dirty:
                    d = subprocess.run(
                        ["git", "log", "-1", "--format=%cs", "--", str(path)],
                        capture_output=True,
                        text=True,
                        cwd=self.m.repo,
                        timeout=10,
                    ).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                d = ""
            d = d or dt.date.today().isoformat()
            self._git_dates[f] = d
            dates.append(d)
        return max(dates) if dates else dt.date.today().isoformat()

    def frame(
        self,
        path: str,
        *,
        title: str,
        here: tuple[str, str | None],
        stamp: list[str],
        head: str,
        sections: list[Sec],
        sources: set[str],
        wide: str = "",
        side: bool = True,
    ) -> str:
        """Один каркас для всех страниц: общее меню и поиск в шапке, шапка страницы, полоса, меню сбоку,
        разделы, подвал. here — где мы: ("board", None), ("svc", <сервис>), ("proc", <процесс>)."""
        shared = self.rel_url(path, "_shared/page.css")
        js = self.rel_url(path, "_shared/page.js")
        keys_js = self.rel_url(path, "ASIS/keys.js")
        asis = self.rel_url(path, "ASIS/x")[:-1]  # путь от страницы к папке ASIS/ — к нему page.js приставляет адреса ключей
        repo_up = (
            os.path.relpath(self.m.repo, (self.root / path).parent).replace("\\", "/")
            + "/"
        )
        gnav = self.global_nav(path, here)
        stamp_html = " · ".join(esc(s) for s in stamp)
        menu = []
        for s in sections:
            if not s.html:
                continue
            sub = (
                '<ol class="sub">' + "".join(self.toc_item(x) for x in s.subs) + "</ol>"
                if s.subs
                else ""
            )
            menu.append(
                f'<li{f" class={s.cls!r}" if s.cls else ""}><a href="#{esc(s.sid)}"><span class="mt">{esc(s.title)}</span>'
                f"{f'<span class=mc>{s.count}</span>' if s.count is not None else ''}</a>{sub}</li>"
            )
        secs = "".join(s.html for s in sections if s.html)
        src_list = ", ".join(f"<code>{esc(s)}</code>" for s in sorted(sources))
        self.sources[path] = sources
        nav = (
            f'<nav class="side" aria-label="Разделы"><ol class="toc">{"".join(menu)}</ol></nav>'
            if menu and side
            else ""
        )
        doc = (
            f'<div class="doc page{"" if nav else " no-side"}">{nav}<main class="secs">{secs}</main></div>'
            if secs
            else ""
        )
        return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — {esc(self.m.settings.get("title", "карта"))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{esc(FONTS_URL)}">
<link rel="stylesheet" href="{esc(shared)}">
<script defer src="{esc(keys_js)}"></script>
<script defer src="{esc(js)}"></script>
</head>
<body data-editor="{esc(self.m.settings.get("editor_url", ""))}" data-repo="{esc(repo_up)}" data-asis="{esc(asis)}">
<header class="top"><div class="page top-in">
{gnav}
<div class="find" role="search"><input type="search" placeholder="Найти ключ, шаг, процесс" aria-label="Поиск по карте" autocomplete="off"><kbd>Ctrl K</kbd><div class="find-res" hidden></div></div></div></header>
{self.tobe_bar(path, sources)}
{head}
{wide}
{doc}
<footer class="foot page"><span class="stamp"><!--stamp-->{stamp_html}<!--/stamp--></span> · собрано генератором из {src_list} — руками не править: правится md.</footer>
</body>
</html>
"""

    def global_nav(self, path: str, here: tuple[str, str | None]) -> str:
        """Общее меню всех страниц: «Карта» — доска, «Сервисы» и «Процессы» — выпадающие списки; где мы — выделено,
        имя текущего сервиса или процесса — рядом с названием списка."""
        m = self.m
        where, name = here
        board = self.rel_url(path, self.board_page())
        # сервисы — по видам; у каждого — первая фраза его README («что это за сервис»), пока её нет — вид
        kinds = (("Сервисы", ("service",)), ("Интерфейс", ("frontend",)),
                 ("Пакеты, программы, библиотеки", ("package", "cli", "library", "ci")))
        cols = []
        for label, ks in kinds:
            items = []
            for s in m.services:
                if m.registry[s].get("kind") not in ks:
                    continue
                rd = m.get(s, "README.md")
                what = first_phrase(rd.text[0]).rstrip(".") if rd and rd.text and "???" not in rd.text[0] else ""
                items.append(
                    f'<a class="{"on" if where == "svc" and s == name else ""}" href="{esc(self.rel_url(path, self.service_page(s)))}">'
                    f'<b>{esc(s)}</b><span class="gm-d">{esc(what or KIND_RU.get(m.registry[s].get("kind"), ""))}</span></a>'
                )
            if items:
                cols.append(f'<p class="gm-g">{esc(label)}</p>{"".join(items)}')
        # две колонки: слева сервисы, справа интерфейс и пакеты — короткие группы не стоят пустыми колонками
        svcs = (f'<div class="gm-col">{cols[0]}</div><div class="gm-col">{"".join(cols[1:])}</div>'
                if len(cols) > 1 else "".join(f'<div class="gm-col">{c}</div>' for c in cols))
        # процессы — колонкой на группу (поле «Группа:», порядок — process_groups настроек проекта)
        order = list(m.settings.get("process_groups") or [])
        groups: dict[str, list[tuple[str, str]]] = {g: [] for g in order}
        for proc, pe in m.processes.items():
            g = pe.fields["Группа"].value if "Группа" in pe.fields else ""
            groups.setdefault(g if g in order else "Прочие", []).append((pe.title, proc))
        pcols = []
        for g, items in groups.items():
            if not items:
                continue
            links = "".join(
                f'<a class="{"on" if where == "proc" and proc == name else ""}" href="{esc(self.rel_url(path, self.process_page(proc)))}">'
                f"<b>{esc(title)}</b><span>{len(m.arrows.get(proc, []))}</span></a>"
                for title, proc in sorted(items)
            )
            pcols.append(f'<div class="gm-col"><p class="gm-g">{esc(g)}</p>{links}</div>')
        procs = "".join(pcols) or '<p class="gm-g">процессов нет</p>'
        cur_s = f'<span class="cur">{esc(name)}</span>' if where == "svc" else ""
        cur_p = (
            f'<span class="cur">{esc(m.processes[name].title)}</span>'
            if where == "proc" and name in m.processes
            else ""
        )
        cover = (
            f'<a class="gi tobe{" on" if where == "cover" else ""}" href="{esc(self.rel_url(path, "TOBE/index.html"))}">'
            f"Изменение<span class=\"cur\">{esc(self.chg.title)}</span></a>"
            if self.chg
            else ""
        )
        return (
            '<nav class="gnav" aria-label="Карта">'
            f'<a class="gi{" on" if where == "board" else ""}" href="{esc(board)}">Карта</a>'
            f'<details class="gm{" on" if where == "svc" else ""}"><summary>Сервисы{cur_s}</summary>'
            f'<div class="gm-list gm-wide gm-svc">{svcs}</div></details>'
            f'<details class="gm{" on" if where == "proc" else ""}"><summary>Процессы{cur_p}</summary>'
            f'<div class="gm-list gm-wide">{procs}<p class="gm-note">число — стрелок в процессе</p></div></details>{cover}</nav>'
        )

    def section(
        self,
        sid: str,
        title: str,
        body: str,
        count: int | None = None,
        collapsed: bool = False,
        subs: list[tuple[str, str]] | None = None,
        cls: str = "",
    ) -> Sec:
        if not body:
            return Sec(sid, title, "", count)
        head = f"<h2>{esc(title)}{f' <span class=cnt>{count}</span>' if count is not None else ''}</h2>"
        c = f"sec {cls}".strip()
        if collapsed:
            html_ = (
                f'<section class="{c}" id="{esc(sid)}"><details class="fold"><summary>{head}</summary>'
                f'<div class="fold-in">{body}</div></details></section>'
            )
        else:
            html_ = f'<section class="{c}" id="{esc(sid)}">{head}{body}</section>'
        return Sec(sid, title, html_, count, subs or [], cls)

    @staticmethod
    def toc_item(x: tuple) -> str:
        """Пункт меню сбоку: (якорь, подпись[, полный текст для подсказки]) или (None, подзаголовок группы).
        Пункт — в одну строку: длинное обрезается многоточием, целиком — в подсказке."""
        if x[0] is None:
            return f'<li class="sg">{x[1]}</li>'
        full = f' title="{esc(x[2])}"' if len(x) > 2 and x[2] else ""
        return f'<li><a href="#{esc(x[0])}"{full}>{x[1]}</a></li>'

    @staticmethod
    def head(title_html: str, kind: str, body: str = "", side: str = "") -> str:
        left = (
            f'<div class="h-line"><h1>{title_html}</h1><span class="h-kind">{esc(kind)}</span></div>{body}'
        )
        inner = (
            f'<div class="head-in"><div>{left}</div><div>{side}</div></div>'
            if side
            else left
        )
        return f'<section class="head page"><div class="panel">{inner}</div></section>'

    # страница сервиса ----------------------------------------------------------------------------

    def build_service(self, svc: str) -> None:
        m, path = self.m, self.service_page(svc)
        reg = m.registry[svc]
        facts = m.facts.get(svc, {})
        readme = m.get(svc, "README.md")
        files = sorted({e.file for e in m.by_service[svc] if e.line})
        sources = set(files) | ({f"ASIS/{svc}/.facts.json"} if facts else set())
        summary = self.blocks(path, readme.text, svc) if readme else ""
        how = m.get(svc, "Как устроен")
        how_html = (
            f'<div class="h-how"><span class="lbl">как устроен</span><div class="h-how-in">'
            f'{self.blocks(path, how.text, svc)}<span class="code-refs h-code">{self.code_list(how)}</span></div></div>'
            if how
            else ""
        )
        head = self.head(
            esc(svc),
            KIND_RU.get(reg.get("kind"), reg.get("kind", "")),
            f'<div class="h-sum">{summary}</div>{how_html}{self.svc_nums(path, svc)}',
        )
        n = {k: len(m.entries(svc, k)) for k in ENTRY_KINDS}
        settings_n = sum(
            len(m.entries(svc, k))
            for k in ("настройка", "постоянная", "ограничитель", "другая настройка")
        )
        secs = [
            self.section("processes", "Процессы", self.svc_processes(path, svc)),
            self.section(
                "links",
                "Связи",
                self.svc_links(path, svc),
                len(m.connections(svc)) + len(m.incoming(svc)) or None,
            ),
            self.section(
                "methods",
                "Методы",
                self.entries_block(path, svc, "метод"),
                n["метод"],
                subs=self.entry_subs(svc, "метод"),
            ),
            self.section(
                "exports",
                "Функции для подключения",
                self.entries_block(path, svc, "функция"),
                n["функция"],
                subs=self.entry_subs(svc, "функция"),
            ),
            self.section(
                "pages",
                "Страницы интерфейса",
                self.entries_block(path, svc, "страница") + self.proxy_html(path, svc),
                n["страница"],
                subs=self.entry_subs(svc, "страница"),
            ),
            self.section(
                "commands",
                "Команды",
                self.entries_block(path, svc, "команда"),
                n["команда"],
                subs=self.entry_subs(svc, "команда"),
            ),
            self.section(
                "storage",
                "Хранилища",
                self.svc_storage(path, svc),
                subs=[
                    (self.anchor(e), f"<code>{esc(e.addr)}</code>")
                    for k in STORE_KINDS
                    if k != "колонка"
                    for e in m.entries(svc, k)
                ],
            ),
            self.section(
                "settings",
                "Настройки и пределы",
                self.svc_settings(path, svc),
                settings_n or None,
            ),
            self.section("own", "Своя работа", self.svc_own(path, svc)),
            self.section(
                "problems",
                "Проблемы",
                self.svc_problems(path, svc),
                len(m.entries(svc, "проблема")),
                subs=[
                    (e.anchor, f'<span class="sev s-{SEV_CLS.get(self.importance(e), "low")}"></span>'
                     f"{esc(self.short_title(e).replace('`', ''))}", e.title.replace("`", ""))
                    for e in m.entries(svc, "проблема")
                ],
            ),
            self.section("tests", "Тесты", self.svc_tests(path, svc)),
        ]
        stamp = []
        if facts:
            stamp.append(
                f"факты {facts.get('commit', '')} · {str(facts.get('extracted_at', ''))[:10]}"
            )
        stamp.append(f"текст {self.git_date(files)}")
        self.pages[path] = self.frame(
            path,
            title=svc,
            here=("svc", svc),
            stamp=stamp,
            head=head,
            sections=secs,
            sources=sources,
        )

    def svc_nums(self, path: str, svc: str) -> str:
        """Строка чисел под сводкой: каждое — ссылка на свой раздел; проблемы — красным."""
        m = self.m
        items = []
        procs = {p for (s, p) in m.slices if s == svc}
        for proc, arrows in m.arrows.items():
            for a in arrows:
                if any(
                    split_key(r, self.svcset)[0] == svc
                    for ins in a.inside
                    for r in LINK_RE.findall(ins)
                ):
                    procs.add(proc)
        if procs:
            items.append(
                f'<li><a href="#processes"><b>{len(procs)}</b> {plural(len(procs), "процесс", "процесса", "процессов")}</a></li>'
            )
        for kind, anc, forms in (
            ("метод", "methods", ("метод", "метода", "методов")),
            ("функция", "exports", ("функция", "функции", "функций")),
            ("страница", "pages", ("страница", "страницы", "страниц")),
            ("команда", "commands", ("команда", "команды", "команд")),
        ):
            k = len(m.entries(svc, kind))
            if k:
                items.append(
                    f'<li><a href="#{anc}"><b>{k}</b> {plural(k, *forms)}</a></li>'
                )
        tables = len(m.entries(svc, "таблица"))
        other = sum(
            len(m.entries(svc, k))
            for k in ("файл данных", "папка", "ключ Redis", "память браузера")
        )
        if tables:
            items.append(
                f'<li><a href="#storage"><b>{tables}</b> {plural(tables, "таблица", "таблицы", "таблиц")}</a></li>'
            )
        if other:
            items.append(
                f'<li><a href="#storage"><b>{other}</b> {plural(other, "хранилище", "хранилища", "хранилищ")} вне базы</a></li>'
            )
        inc = sorted({c.service for c in m.incoming(svc)})
        out = [
            self.participant_name(c.extra.get("to", "")) for c in m.connections(svc)
        ]
        if inc:
            items.append(
                f'<li><span class="lbl">зовут его</span><a href="#links">{esc(", ".join(inc))}</a></li>'
            )
        if out:
            items.append(
                f'<li><span class="lbl">зовёт он</span><a href="#links">{esc(", ".join(out))}</a></li>'
            )
        t = m.facts.get(svc, {}).get("pytest") or {}
        if t:
            col = sum((t.get("collected") or {}).values())
            res = (t.get("run") or {}).get("results", {})
            passed = sum(r.get("passed", 0) for r in res.values())
            items.append(
                f'<li><a href="#tests"><span class="lbl">тесты</span><b>{passed}</b> из {col}</a></li>'
            )
        probs = m.entries(svc, "проблема")
        if probs:
            by: dict[str, int] = {}
            for p in probs:
                by[self.importance(p)] = by.get(self.importance(p), 0) + 1
            forms = {
                "высокая": ("высокая", "высокие", "высоких"),
                "средняя": ("средняя", "средние", "средних"),
                "низкая": ("низкая", "низкие", "низких"),
            }
            marks = "".join(
                f'<a class="pm imp-{IMP_CLASS[k]}" href="#problems">{by[k]} {plural(by[k], *forms[k])}</a>'
                for k in ("высокая", "средняя", "низкая")
                if by.get(k)
            )
            items.append(f'<li><span class="lbl">проблемы</span>{marks}</li>')
        else:
            items.append('<li class="muted">известных проблем нет</li>')
        return f'<ul class="nums">{"".join(items)}</ul>'

    def svc_processes(self, path: str, svc: str) -> str:
        m = self.m
        rows = []
        for (s, proc), sl in sorted(m.slices.items(), key=lambda x: x[0][1]):
            if s != svc:
                continue
            pe = m.processes.get(proc)
            steps = " › ".join(
                f'<a href="{esc(self.url_entity(path, m.get(svc, a)))}" title="{esc(self.plain_text(m.get(svc, a).first_phrase()))}">'
                f"{esc(m.get(svc, a).title)}</a>"
                for a in sl.extra.get("steps", [])
            )
            rows.append(
                f'<tr><td><a href="{esc(self.rel_url(path, self.process_page(proc)))}">{esc(pe.title if pe else proc)}</a></td>'
                f"<td>{self.inline(path, sl.text[0] if sl.text else '', svc)}</td>"
                f"<td>{steps}</td></tr>"
            )
        for proc, arrows in m.arrows.items():
            if (svc, proc) in m.slices:
                continue
            keys = {
                k
                for a in arrows
                for ins in a.inside
                for r in LINK_RE.findall(ins)
                for s2, k in [split_key(r, self.svcset)]
                if s2 == svc
            }
            if keys:
                rows.append(
                    f'<tr><td><a href="{esc(self.rel_url(path, self.process_page(proc)))}">{esc(m.processes[proc].title)}</a></td>'
                    '<td class="muted">шагов нет — только отвечает методом</td><td>'
                    + ", ".join(
                        self.key_tag(path, k, svc) for k in sorted(keys)
                    )
                    + "</td></tr>"
                )
        if not rows:
            return ""
        return (
            '<table class="grid"><thead><tr><th style="width:18%">процесс</th><th>что сервис в нём делает</th>'
            f'<th style="width:34%">шаги среза</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
        )

    # связи

    def conn_methods(self, path: str, svc: str, c: Entity) -> list[dict]:
        """Методы связи: ключ у них, шаги, которые зовут, где принимают, своё ожидание и отказ."""
        m = self.m
        to = c.extra.get("to", "")
        out = []
        for me in [
            e
            for e in m.by_service[svc]
            if e.kind == "связь-метод" and e.parent == c.addr
        ]:
            key = me.title
            steps = []
            for ln in m.links:
                if (
                    ln.kind == "зовёт"
                    and ln.key == key
                    and ln.service == to
                    and m._service_of_file(ln.src_file) == svc
                ):
                    st = m.get(svc, ln.src)
                    if st and st not in steps:
                        steps.append(st)
            handler = ""
            if to in m.facts:
                for fm in (m.facts[to].get("fastapi-openapi") or {}).get("methods", []):
                    if f"{fm['method']} {fm['path']}" == key:
                        handler = (
                            f'<a class="cref" href="#" data-p="{esc(fm["ref"].rsplit(":", 1)[0])}" '
                            f'data-l="{fm["ref"].rsplit(":", 1)[1]}">{esc(fm["function"])}</a>'
                        )
            out.append({"e": me, "key": key, "steps": steps, "handler": handler})
        return out

    def conn_key(self, path: str, to: str, key: str) -> str:
        url = self.url_key(path, to, key) if not to.startswith("external:") else None
        return (
            f'<a class="key kt-method" href="{esc(url)}">{esc(key)}</a>'
            if url
            else f'<span class="key {"kt-ext" if to.startswith("external:") else ""}">{esc(key)}</span>'
        )

    def conn_target(self, path: str, to: str) -> str:
        name = esc(self.participant_name(to))
        if to in self.m.registry:
            return f'<a href="{esc(self.rel_url(path, self.service_page(to)))}">{name}</a>'
        return name

    def conn_detail(self, path: str, svc: str, c: Entity, mets: list[dict]) -> str:
        to = c.extra.get("to", "")
        flds = "".join(
            self.field_html(path, c, f)
            for f in ("Адрес", "Вход", "Ожидание", "При отказе", "Не доходит")
        ) + self.gone_fields(path, c)
        rows = []
        for d in mets:
            me = d["e"]
            own = "".join(
                self.field_html(path, me, f)
                for f in ("Ожидание", "При отказе", "Не доходит")
            )
            rows.append(
                f"<tr class=\"{self.cc(me).strip()}\"><td>{self.conn_key(path, to, d['key'])}{self.ct(me)}"
                f"{f'<dl class=flds>{own}</dl>' if own else ''}</td>"
                f"<td>{'<br>'.join(self.step_ref(path, s) for s in d['steps']) or '<span class=muted>шаги не зовут</span>'}</td>"
                f"<td>{d['handler'] or '<span class=muted>—</span>'}</td><td>{self.code_list(me, 1)}</td></tr>"
            )
        table = (
            '<table class="grid"><thead><tr><th>метод у них</th><th>зачем зовёт — шаги</th><th>где принимают</th>'
            f"<th>код</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
            if rows
            else ""
        )
        return (
            self.chg_box(path, c)
            + f'<dl class="flds">{flds}</dl>'
            + (f'<div class="e-text">{self.blocks(path, c.text, svc)}</div>' if c.text else "")
            + table
        )

    def conn_problems(self, c: Entity, mets: list[dict]) -> list[Entity]:
        out = self.problems_in(c)
        for d in mets:
            for p in self.problems_in(d["e"]):
                if p not in out:
                    out.append(p)
        return out

    def svc_links(self, path: str, svc: str) -> str:
        m = self.m
        out = m.connections(svc)
        inc = m.incoming(svc)
        if not out and not inc:
            return ""
        diagram = self.links_diagram(path, svc, inc, out)
        body = diagram
        if out:
            cols = "minmax(170px,.7fr) minmax(200px,1fr) minmax(240px,1.1fr) minmax(220px,1fr) minmax(260px,1.2fr) 60px"
            rows = []
            for c in out:
                to = c.extra.get("to", "")
                mets = self.conn_methods(path, svc, c)
                probs = self.conn_problems(c, mets)
                steps = []
                for d in mets:
                    for s in d["steps"]:
                        if s not in steps:
                            steps.append(s)
                fv = lambda f: self.inline(path, c.fields[f].value, svc) if f in c.fields else ""  # noqa: E731
                detail = self.conn_detail(path, svc, c, mets)
                part = self.cc(c) or (" chg-part" if any(self.cb(d["e"]) for d in mets) else "")
                tags = self.ct(c) + "".join(self.ct(d["e"]) for d in mets)
                rows.append(
                    f'<details class="ix-r{" has-pm" if probs else ""}{part}" id="{esc(self.anchor(c))}"><summary class="ix-s">'
                    f'<span class="nm">→ {self.conn_target(path, to)}{tags}</span>'
                    f"<span>{', '.join(self.conn_key(path, to, d['key']) for d in mets)}</span>"
                    f"<span>{', '.join(self.step_ref(path, s) for s in steps)}</span>"
                    f"<span>{fv('Ожидание')}</span><span>{fv('При отказе')}</span>"
                    f"<span>{self.pm_html(path, probs)}</span></summary>"
                    f'<div class="ix-b">{detail}{self.code_refs(c)}</div></details>'
                )
            head = "".join(
                f"<span>{h}</span>"
                for h in ("кому", "методы у них", "зачем — шаги", "сколько ждёт", "при отказе", "")
            )
            body += (
                f'<h3 class="sub">Кого зовёт</h3>{self.ix_tools(len(out), False)}<div class="ix" style="--cols:{cols}">'
                f'<div class="ix-h">{head}</div>{"".join(rows)}</div>'
            )
        if inc:
            rows = []
            for c in inc:
                src = c.service
                keys = [
                    e.title
                    for e in m.by_service[src]
                    if e.kind == "связь-метод" and e.parent == c.addr
                ]
                arrows = [
                    a
                    for proc, arrs in m.arrows.items()
                    for a in arrs
                    if a.sender == src and a.receiver == svc
                ]
                by: dict[str, list] = {}
                for a in arrows:
                    by.setdefault(a.process, []).append(a)
                procs = "; ".join(
                    f'<span class="muted">{esc(self.process_title(p))}</span> '
                    + "".join(self.arrow_link(path, a) for a in arrs)
                    for p, arrs in by.items()
                )
                fail = " ".join(
                    f'<span class="lbl">{esc(f.lower())}</span>{self.inline(path, c.fields[f].value, src)}'
                    for f in ("Ожидание", "При отказе")
                    if f in c.fields
                )
                rows.append(
                    f'<tr id="in-{esc(slug(src))}"><td><a href="{esc(self.rel_url(path, self.service_page(src), self.anchor(c)))}">{esc(src)}</a></td>'
                    f"<td>{', '.join(self.key_tag(path, k, svc) for k in keys)}</td><td>{procs}</td><td>{fail}</td></tr>"
                )
            body += (
                '<h3 class="sub">Кто зовёт</h3><table class="grid"><thead><tr><th style="width:12%">кто</th>'
                '<th style="width:22%">какие методы</th><th style="width:20%">в каких процессах</th>'
                "<th>что он делает, если сервис не ответил</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table>"
            )
        return body

    def links_diagram(
        self, path: str, svc: str, inc: list[Entity], out: list[Entity]
    ) -> str:
        """Схема «кто зовёт — слева, кого зовёт — справа»; узлы ведут на строки ниже, ⚠ — проблема связи."""
        left = [
            (
                c.service,
                c.fields["Подпись"].value if "Подпись" in c.fields else "",
                "request",
                f"#in-{slug(c.service)}",
                self.problems_in(c),
            )
            for c in inc
        ]
        right = []
        for c in out:
            to = c.extra.get("to", "")
            mets = self.conn_methods(path, svc, c)
            right.append(
                (
                    self.participant_name(to),
                    c.fields["Подпись"].value if "Подпись" in c.fields else "",
                    "external" if to.startswith("external:") else "request",
                    f"#{self.anchor(c)}",
                    self.conn_problems(c, mets),
                )
            )
        n = max(len(left), len(right), 1)
        bw, bh, gap, w = 240, 54, 18, 1100
        h = n * (bh + gap) + gap
        cy = h / 2
        cx0, cx1 = w / 2 - 130, w / 2 + 130
        parts = [
            f'<rect class="d-center" x="{cx0}" y="{cy - 30}" width="260" height="60" rx="3"/>'
            f'<text class="d-ct" x="{w / 2}" y="{cy + 7}" text-anchor="middle">{esc(svc)}</text>'
        ]

        def pm(x, y, probs):
            if not probs:
                return ""
            return (
                f'<circle class="d-pm" cx="{x}" cy="{y}" r="9"/><text class="d-pmt" x="{x}" y="{y + 4}" '
                f'text-anchor="middle">{len(probs)}</text>'
            )

        for i, (name, label, k, href, probs) in enumerate(left):
            y = gap + i * (bh + gap)
            mx, my = (10 + bw + cx0) / 2, (y + bh / 2 + cy) / 2
            parts.append(
                f'<a class="d-node" href="{esc(href)}"><rect class="d-box" x="10" y="{y}" width="{bw}" height="{bh}" rx="3"/>'
                f'<text class="d-t" x="26" y="{y + bh / 2 + 6}">{esc(name)}</text></a>'
                f'<path class="d-line k-{k}" d="M{10 + bw},{y + bh / 2} C{cx0 - 70},{y + bh / 2} {cx0 - 70},{cy} {cx0},{cy}" marker-end="url(#ah)"/>'
                f'<text class="d-l" x="{mx}" y="{my - 8}" text-anchor="middle">{esc(label)}</text>{pm(mx, my + 10, probs)}'
            )
        for i, (name, label, k, href, probs) in enumerate(right):
            y = gap + i * (bh + gap)
            x = w - 10 - bw
            mx, my = (cx1 + x) / 2, (y + bh / 2 + cy) / 2
            parts.append(
                f'<a class="d-node" href="{esc(href)}"><rect class="d-box{" ext" if k == "external" else ""}" x="{x}" y="{y}" width="{bw}" height="{bh}" rx="3"/>'
                f'<text class="d-t" x="{x + 16}" y="{y + bh / 2 + 6}">{esc(name)}</text></a>'
                f'<path class="d-line k-{k}" d="M{cx1},{cy} C{cx1 + 70},{cy} {x - 70},{y + bh / 2} {x},{y + bh / 2}" marker-end="url(#ah)"/>'
                f'<text class="d-l" x="{mx}" y="{my - 8}" text-anchor="middle">{esc(label)}</text>{pm(mx, my + 10, probs)}'
            )
        return (
            f'<figure class="diagram"><svg viewBox="0 0 {w} {h}" role="img" aria-label="Связи {esc(svc)}">'
            f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" class="d-ah"/></marker></defs>{"".join(parts)}</svg></figure>'
        )

    # точки входа: методы, функции, страницы, команды

    LEFT_FIELDS = (
        "Вид",
        "Что делает",
        "Что на странице",
        "Кому видна",
        "Аргументы",
        "Ошибки",
        "Доступ",
        "События",
        "Поля",
        "Кто запускает",
        "Вручную",
        "Проблемы",
    )

    def callers_items(
        self, path: str, svc: str, key: str, short: bool = False
    ) -> list[str]:
        items = []
        for c in self.m.callers(svc, key):
            if c["via"] == "шаг" and c.get("entity"):
                st = c["entity"]
                nums = "".join(
                    self.arrow_link(path, a) for a in self.step_arrows(st, svc, key)
                )
                if short:
                    items.append(
                        f'<span title="{esc(self.plain_text(st.title))}">{esc(c["who"])}</span> {nums}'
                    )
                else:
                    items.append(
                        f'<li><b>{esc(c["who"])}</b> {self.ent_ref(path, st)} {nums}</li>'
                    )
            elif c["via"] == "вручную":
                if short:
                    items.append(
                        f'<span title="{esc(self.plain_text(c["text"]))}">вручную</span>'
                    )
                else:
                    items.append(
                        f"<li><b>вручную</b> — {self.inline(path, c['text'], svc)}</li>"
                    )
            elif c["via"] == "стрелка":
                a = c["arrow"]
                who = esc(self.participant_name(a.sender))
                if short:
                    items.append(f"{who} {self.arrow_link(path, a)}")
                else:
                    items.append(
                        f'<li><b>{who}</b> <span class="muted">{esc(self.process_title(a.process))}</span> '
                        f"{self.arrow_link(path, a)}</li>"
                    )
        return items

    def entry_body(
        self, path: str, svc: str, e: Entity, code: bool = True
    ) -> str:
        """Запись точки входа: слева написанное в md, справа собранное по карте и фактам."""
        m = self.m
        left = "".join(self.field_html(path, e, f) for f in self.LEFT_FIELDS) + self.gone_fields(path, e)
        parts = []
        callers = self.callers_items(path, svc, e.addr)
        if callers:
            parts.append(
                f'<div class="fld"><dt>Кто вызывает</dt><dd><ul class="plain">{"".join(callers)}</ul></dd></div>'
            )
        steps = m.steps_handling(svc, e.addr)
        if steps:
            how = "".join(f"<li>{self.step_ref(path, s)}</li>" for s in steps)
            parts.append(
                f'<div class="fld"><dt>Как работает</dt><dd><ol class="plain">{how}</ol></dd></div>'
            )
        touch = self.touch_html(path, m.touches(svc, e.addr))
        if touch:
            parts.append(f'<div class="fld"><dt>Что трогает</dt><dd>{touch}</dd></div>')
        own_probs = self.problems_in(e)
        step_probs = [p for p in self.entry_problems(svc, e) if p not in own_probs]
        if step_probs:
            parts.append(
                '<div class="fld"><dt>Проблемы шагов</dt><dd>'
                + "<br>".join(
                    f'{self.pm_html(path, [p], True)} <a href="{esc(self.url_entity(path, p))}">{esc(self.short_title(p))}</a>'
                    for p in step_probs
                )
                + "</dd></div>"
            )
        fm = {
            f"{x['method']} {x['path']}": x
            for x in (m.facts.get(svc, {}).get("fastapi-openapi") or {}).get(
                "methods", []
            )
        }.get(e.addr)
        fact = ""
        if fm:
            req = ", ".join(
                f"<code>{esc(x['name'])}</code> {esc(x['type'])}"
                for x in fm.get("request", [])
            )
            resp = ", ".join(
                f"<code>{esc(x['name'])}</code> {esc(x['type'])}"
                for x in fm.get("response", [])
            )
            notes = []
            if "Доступ" not in e.fields:
                notes.append("вход " + ("нужен" if fm.get("auth") else "не нужен"))
            if fm.get("in_schema") is False:
                notes.append("нет в живой схеме")
            fact = (
                f'<div class="fld"><dt>Запрос</dt><dd>{req or "—"}</dd></div>'
                f'<div class="fld"><dt>Ответ</dt><dd>{resp or "—"}</dd></div>'
                f'<div class="fld"><dt>Обработчик</dt><dd><a class="cref" href="#" data-p="{esc(fm["ref"].rsplit(":", 1)[0])}" '
                f'data-l="{fm["ref"].rsplit(":", 1)[1]}">{esc(fm["function"])}</a>'
                f"{' · ' + ' · '.join(notes) if notes else ''}</dd></div>"
            )
        right = (
            (f'<dl class="flds">{"".join(parts)}</dl>' if parts else "")
            + (f'<dl class="flds">{fact}</dl>' if fact else "")
        )
        if right:
            right = f'<span class="lbl">собрано по карте и коду</span>{right}'
        body = (
            f'<div class="e-grid"><dl class="flds">{left}</dl><div class="e-side">{right}</div></div>'
            if left and right
            else (f'<dl class="flds">{left}</dl>' if left else f'<div class="e-side">{right}</div>')
        )
        return body + (self.code_refs(e) if code else "")

    def entry_label(self, e: Entity, kind: str) -> str:
        if kind == "метод":
            verb, _, p = e.addr.partition(" ")
            return f'<span class="verb">{esc(verb)}</span><code>{esc(p)}</code>'
        return f"<code>{esc(e.addr)}</code>"

    def entry_subs(self, svc: str, kind: str) -> list[tuple]:
        ents = self.m.entries(svc, kind)
        if kind != "метод":
            return [(self.anchor(e), f"<code>{esc(e.addr)}</code>", e.addr) for e in ents]
        out: list[tuple] = []
        groups = self.groups(ents)
        for g, es in groups.items():
            if len(groups) > 1 and g:
                out.append((None, esc(g)))
            for e in es:
                verb, _, path = e.addr.partition(" ")
                short = re.sub(r"^/api(/v\d+)?(?=/)", "", path)
                # различаются хвостом после параметра: «…/archive»; параметр в конце — «{…}»
                if re.search(r"\}/", short):
                    short = "…/" + short.rsplit("}/", 1)[1]
                short = re.sub(r"\{[^}]*\}", "{…}", short)
                out.append((self.anchor(e), f'<span class="verb v-{esc(verb.lower())}">{esc(verb)}</span>'
                            f"<code>{esc(short)}</code>", e.addr))
        return out

    def entries_block(self, path: str, svc: str, kind: str) -> str:
        ents = self.m.entries(svc, kind)
        if not ents:
            return ""
        return self.entry_index(path, svc, kind, ents)

    @staticmethod
    def groups(ents: list[Entity]) -> dict[str, list[Entity]]:
        out: dict[str, list[Entity]] = {}
        for e in ents:
            out.setdefault(
                e.fields["Группа"].value if "Группа" in e.fields else "", []
            ).append(e)
        return out

    def ix_tools(self, n: int, with_pm: bool) -> str:
        if n < 2:
            return ""
        pm = (
            '<button data-ix="pm" aria-pressed="false">только с проблемами</button>'
            if with_pm
            else ""
        )
        return f'<div class="ix-tools"><button data-ix="open">раскрыть все</button>{pm}</div>'

    def entry_index(
        self, path: str, svc: str, kind: str, ents: list[Entity]
    ) -> str:
        """Точки входа — сводная таблица по строке на пункт; строка раскрывается в запись: слева написанное в md,
        справа собранное по карте и коду."""
        if kind == "метод":
            heads = ("метод", "что делает", "кто вызывает", "что трогает", "ошибки", "")
            cols = "minmax(250px,1.1fr) minmax(250px,1.3fr) minmax(150px,.7fr) minmax(280px,1.4fr) minmax(90px,.4fr) 60px"
        elif kind == "страница":
            heads = ("адрес", "что на странице", "кому видна", "что трогает", "")
            cols = "minmax(200px,.8fr) minmax(300px,1.5fr) minmax(170px,.8fr) minmax(280px,1.4fr) 60px"
        else:
            heads = ("имя", "что делает", "кто вызывает", "что трогает", "")
            cols = "minmax(240px,1fr) minmax(280px,1.4fr) minmax(150px,.7fr) minmax(280px,1.4fr) 60px"
        rows, any_pm = [], False
        for g, es in self.groups(ents).items():
            if g:
                rows.append(f'<div class="ix-g">{esc(g)}</div>')
            for e in es:
                probs = self.entry_problems(svc, e)
                any_pm = any_pm or bool(probs)
                fv = lambda f: self.inline(path, e.fields[f].value, svc) if f in e.fields and e.fields[f].value else ""  # noqa: E731
                touch = self.touch_html(path, self.m.touches(svc, e.addr), "span")
                if kind == "страница":
                    cells = [fv("Что на странице"), fv("Кому видна"), touch]
                else:
                    who = ", ".join(self.callers_items(path, svc, e.addr, short=True))
                    cells = [fv("Что делает"), who or '<span class="muted">—</span>', touch]
                if kind == "метод":
                    codes = [
                        mm.group(1)
                        for it in (e.fields["Ошибки"].items if "Ошибки" in e.fields else [])
                        if (mm := re.match(r"\s*(\d{3})", it))
                    ]
                    cells.append(f'<span class="muted">{" ".join(codes)}</span>' if codes else "")
                cells.append(self.pm_html(path, probs))
                rows.append(
                    f'<details class="ix-r{" has-pm" if probs else ""}{self.cc(e)}" id="{esc(self.anchor(e))}"><summary class="ix-s">'
                    f'<span class="nm">{self.entry_label(e, kind)}{self.ct(e)}</span>'
                    + "".join(f"<span>{c}</span>" for c in cells)
                    + f'</summary><div class="ix-b">{self.chg_box(path, e)}{self.entry_body(path, svc, e)}'
                    f'<div class="code-refs">{self.md_link(e)}</div></div></details>'
                )
        for e, b in self.gone_of(svc, (kind,)):
            fv = lambda f: self.inline(path, e.fields[f].value, svc) if f in e.fields and e.fields[f].value else ""  # noqa: E731
            rows.append(
                f'<div class="ix-r chg chg-gone" id="{esc(self.anchor(e))}"><div class="ix-s">'
                f'<span class="nm">{self.entry_label(e, kind)}{self.ctag(b)}</span>'
                f'<span>{fv("Что делает") or fv("Что на странице")}</span></div></div>'
            )
        head = "".join(f"<span>{h}</span>" for h in heads)
        return (
            f'{self.ix_tools(len(ents), any_pm)}<div class="ix" style="--cols:{cols}"><div class="ix-h">{head}</div>'
            f'{"".join(rows)}</div>'
        )

    def proxy_html(self, path: str, svc: str) -> str:
        out = ""
        for p in self.m.entries(svc, "правила прокси"):
            head = list(p.table[0].keys())[:-1] if p.table else []
            rows = "".join(
                "<tr>"
                + "".join(f"<td>{self.inline(path, r[h], svc)}</td>" for h in head)
                + "</tr>"
                for r in p.table
            )
            out += (
                f'<h3 class="sub" id="{esc(self.anchor(p))}">Куда уходят запросы {self.tools(p)}</h3>'
                f'<table class="grid"><thead><tr>{"".join(f"<th>{esc(h)}</th>" for h in head)}</tr></thead><tbody>{rows}</tbody></table>'
                f'{self.blocks(path, p.text, svc)}<dl class="flds">{self.field_html(path, p, "Адрес")}</dl>'
            )
        return out

    # хранилища

    def actor_order(self, e: Entity) -> tuple:
        """Порядок столбцов матрицы: шаги процессов по порядку процесса и шага, своя работа, точки входа."""
        m = self.m
        if e.kind == "шаг":
            proc = e.extra.get("process")
            doc = m.own.get(e.service) if proc == "own" else m.slices.get((e.service, proc))
            idx = doc.extra["steps"].index(e.addr) if doc and e.addr in doc.extra["steps"] else 0
            if proc == "own":
                return (1, "", e.service, idx)
            return (0, proc, e.service, idx)
        return (2, "", e.service or "", e.addr)

    def wr_cells(self, path: str, svc: str, key: str) -> tuple[str, str]:
        """Кто пишет и кто читает: шаги коротким именем; записанное про таблицу целиком — у колонки серым."""
        res = self.m.writers_readers(svc, key)
        out = []
        for kind in ("пишет", "читает"):
            items = []
            for ln in res[kind]:
                e = self.m.get(self.m._service_of_file(ln.src_file), ln.src)
                if e and (r := self.ent_ref(path, e)) not in items:
                    items.append(r)
            for ln in res["через таблицу"]:
                if ln.kind != kind:
                    continue
                e = self.m.get(self.m._service_of_file(ln.src_file), ln.src)
                if e:
                    r = f'<span class="muted" title="через таблицу целиком">{self.ent_ref(path, e)}</span>'
                    if r not in items:
                        items.append(r)
            out.append("<br>".join(items))
        return out[0], out[1]

    def svc_storage(self, path: str, svc: str) -> str:
        m = self.m
        intro = ""
        doc = m.get(svc, "storage.md")
        if doc and doc.text and not doc.extra.get("empty"):
            intro = f'<div class="sec-intro">{self.blocks(path, doc.text, svc)}</div>'
        return intro + self.storage_cards(path, svc) + self.other_stores(path, svc)

    def table_info(self, svc: str, e: Entity) -> tuple[dict, list[str], dict, str]:
        m = self.m
        ft = {
            t["name"]: t
            for t in (m.facts.get(svc, {}).get("postgres") or {}).get("tables", [])
        }.get(e.addr, {})
        cols = [c["name"] for c in ft.get("columns", [])] or [
            x.addr.split(".", 1)[1]
            for x in m.by_service[svc]
            if x.kind == "колонка" and x.parent == e.addr
        ]
        units = {}
        if "Единицы" in e.fields:
            for it in e.fields["Единицы"].items:
                mm = re.match(r"`([^`]+)` — (.+)", it)
                if mm:
                    units[mm.group(1)] = mm.group(2)
        meta = (
            f"таблица · {ft.get('rows', '?')} строк на {esc(m.facts[svc]['postgres'].get('rows_at', ''))}"
            if ft
            else "таблица"
        )
        return ft, cols, units, meta

    @staticmethod
    def col_comment(c: dict) -> str:
        """Описание колонки: из самой базы; если в базе его нет — из модели в коде, с пометкой."""
        if c.get("db_comment"):
            return esc(c["db_comment"])
        if c.get("comment"):
            return f'{esc(c["comment"])} <span class="muted">· в коде, в базе нет</span>'
        return ""

    def storage_cards(self, path: str, svc: str) -> str:
        """Таблица базы — запись, которая сворачивается (на большой карте таблиц много, а колонок в каждой — десятки):
        заголовок с числом строк, смысл, кто пишет и читает строку целиком, колонки — таблицей с «пишет» и «читает»."""
        m = self.m
        out = []
        for e in m.entries(svc, "таблица"):
            ft, cols, units, meta = self.table_info(svc, e)
            rows = []
            for c in ft.get("columns", []) or [{"name": x} for x in cols]:
                ck = f"{e.addr}.{c['name']}"
                ce = m.get(svc, ck)
                note = ""
                if ce and not ce.extra.get("facts_only"):
                    fl = "".join(
                        self.field_html(path, ce, f)
                        for f in ("Хранится", "Означает", "Пример")
                    )
                    note = (
                        self.blocks(path, ce.text, svc)
                        + (f'<dl class="flds tight">{fl}</dl>' if fl else "")
                        + self.code_refs(ce, 2)
                    )
                w, r = self.wr_cells(path, svc, ck)
                typ = esc(c.get("type", ""))
                if c.get("type") and not c.get("nullable", True):
                    typ += ' <span class="muted">обяз.</span>'
                rows.append(
                    f'<tr id="c-{esc(slug(ck))}"><td><code>{esc(c["name"])}</code></td><td class="nw">{typ}</td>'
                    f"<td>{esc(units.get(c['name'], ''))}</td>"
                    f"<td>{self.col_comment(c)}{note}</td><td>{w}</td><td>{r}</td></tr>"
                )
            w, r = self.wr_cells(path, svc, e.addr)
            whole = (
                f'<dl class="flds"><div class="fld"><dt>Пишет строку</dt><dd>{w or "—"}</dd></div>'
                f'<div class="fld"><dt>Читает строку</dt><dd>{r or "—"}</dd></div></dl>'
            )
            out.append(
                # что в таблице — в заголовке записи: видно и у свёрнутой
                f'<details class="entry tbl" id="{esc(self.anchor(e))}" open><summary><div class="e-head">'
                f'<h3><code>{esc(e.addr)}</code></h3><span class="tag">{meta} · {len(rows)} '
                f'{plural(len(rows), "колонка", "колонки", "колонок")}</span>{self.tools(e)}</div>'
                + (f'<div class="e-text">{self.blocks(path, e.text, svc)}</div>' if e.text else "")
                + "</summary>"
                + whole
                + (
                    '<table class="grid"><thead><tr><th>колонка</th><th>тип</th><th>единица</th><th>что значит</th>'
                    f"<th>пишет</th><th>читает</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
                    if rows
                    else ""
                )
                + "</details>"
            )
        return "".join(out)

    def other_stores(self, path: str, svc: str) -> str:
        m = self.m
        rows = []
        for kind in ("файл данных", "папка", "ключ Redis", "память браузера"):
            for e in m.entries(svc, kind):
                fl = "; ".join(
                    f'<span class="lbl">{esc(f.lower())}</span>{self.inline(path, e.fields[f].value, svc)}'
                    for f in (
                        "Где",
                        "Тип",
                        "Живёт",
                        "Формат",
                        "Сколько",
                        "Путь у сервиса",
                        "События",
                    )
                    if f in e.fields and e.fields[f].value
                )
                w, r = self.wr_cells(path, svc, e.addr)
                rows.append(
                    f'<tr id="{esc(self.anchor(e))}"><td><code>{esc(e.addr)}</code><span class="kind-l">{esc(kind)}</span></td>'
                    f"<td>{self.blocks(path, e.text, svc)}</td><td>{fl}</td><td>{w}</td><td>{r}</td>"
                    f"<td>{self.code_list(e, 2)} {self.md_link(e)}</td></tr>"
                )
        if not rows:
            return ""
        title = (
            '<h3 class="sub">Вне базы</h3>' if m.entries(svc, "таблица") else ""
        )
        return (
            f'{title}<table class="grid"><thead><tr><th style="width:14%">имя</th><th>что это</th><th style="width:16%">где</th>'
            f'<th style="width:14%">пишет</th><th style="width:14%">читает</th><th style="width:12%">код</th></tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    # настройки и пределы, своя работа

    def used_in(self, path: str, svc: str, key: str) -> str:
        items = []
        for ln in self.m.links:
            if ln.service != svc or ln.key != key:
                continue
            e = self.m.get(self.m._service_of_file(ln.src_file), ln.src)
            if e and e.addr != key:
                r = self.ent_ref(path, e)
                if r not in items:
                    items.append(r)
        return "<br>".join(items)

    def svc_settings(self, path: str, svc: str) -> str:
        """Одна таблица: настройки, зашитое в коде, ограничители, другие настройки."""
        m = self.m
        facts = {s["name"]: s for s in facts_settings(m.facts.get(svc, {}))}
        rows = []
        for e in m.entries(svc, "настройка"):
            f = facts.get(e.addr)
            if f and f.get("secret"):
                val = '<span class="muted">секрет</span>'
            elif f and f.get("default"):
                val = f"<code>{esc(f['default'])}</code>"
            else:
                val = '<span class="muted">—</span>'
            src = esc(f.get("source", "")) if f else '<span class="muted">фактов нет</span>'
            rows.append(
                (e, f"<code>{esc(e.addr)}</code>", "настройка", val, src, self.blocks(path, e.text, svc), self.used_in(path, svc, e.addr))
            )
        for e in m.entries(svc, "постоянная"):
            val = esc(e.fields["Значение"].value) if "Значение" in e.fields else ""
            rows.append(
                (e, f"<code>{esc(e.title)}</code>", "в коде", val, "код", self.blocks(path, e.text, svc), self.used_in(path, svc, e.addr))
            )
        for e in m.entries(svc, "ограничитель"):
            fv = lambda n: self.inline(path, e.fields[n].value, svc) if n in e.fields else ""  # noqa: E731
            what = self.blocks(path, e.text, svc) + (
                f'<p><span class="lbl">при превышении</span>{fv("При превышении")}</p>'
                if "При превышении" in e.fields
                else ""
            )
            rows.append(
                (e, esc(e.title), "предел", fv("Сколько"), fv("Где хранится"), what, fv("Где действует"))
            )
        for e in m.entries(svc, "другая настройка"):
            fl = "".join(self.field_html(path, e, n) for n in e.fields)
            rows.append(
                (e, esc(e.title), "другое", "", "", self.blocks(path, e.text, svc) + (f'<dl class="flds tight">{fl}</dl>' if fl else ""), "")
            )
        gone = self.gone_of(svc, ("настройка", "постоянная", "ограничитель", "другая настройка"))
        if not rows and not gone:
            return ""
        body = "".join(
            f'<tr class="{self.cc(e).strip()}" id="{esc(self.anchor(e))}"><td>{name}<span class="kind-l">{esc(kind)}</span>{self.ct(e)}</td>'
            f"<td>{val}</td><td>{src}</td><td>{self.chg_box(path, e) if self.cb(e) and self.cb(e).kind != 'новое' else ''}{what}</td>"
            f"<td>{where}</td><td>{self.code_list(e, 1)} {self.md_link(e)}</td></tr>"
            for e, name, kind, val, src, what, where in rows
        ) + "".join(
            f'<tr class="chg chg-gone" id="{esc(self.anchor(e))}"><td><code>{esc(e.title)}</code>{self.ctag(b)}</td><td></td><td></td>'
            f"<td>{self.blocks(path, e.text, svc)}</td><td></td><td></td></tr>"
            for e, b in gone
        )
        return (
            '<table class="grid"><thead><tr><th style="width:15%">имя</th><th style="width:12%">значение</th>'
            '<th style="width:9%">откуда</th><th>что значит</th><th style="width:20%">где действует</th>'
            f'<th style="width:11%">код</th></tr></thead><tbody>{body}</tbody></table>'
        )

    def svc_own(self, path: str, svc: str) -> str:
        """Своя работа — шагами целиком (из own.md), у шага — «когда» из его фоновой работы; фоновая работа без шага —
        строкой таблицы. Отдельной страницы своей работы нет."""
        m = self.m
        own = m.own.get(svc)
        bgs = m.entries(svc, "фоновая работа")
        blocks, used = [], set()
        for i, a in enumerate(own.extra["steps"] if own else [], 1):
            st = m.get(svc, a)
            bg = next(
                (
                    b
                    for b in bgs
                    if "Описание" in b.fields
                    and f"own.md#{st.anchor}" in b.fields["Описание"].value
                ),
                None,
            )
            when = ""
            if bg:
                used.add(bg.addr)
                if "Когда" in bg.fields:
                    when = f'<span class="tag">когда: {self.inline(path, bg.fields["Когда"].value, svc)}</span>'
            marker = f'<span id="{esc(bg.anchor)}"></span>' if bg else ""
            blocks.append(marker + self.step_block(path, st, i, when))
        rows = []
        for b in bgs:
            if b.addr in used:
                continue
            fv = lambda n: self.inline(path, b.fields[n].value, svc) if n in b.fields else ""  # noqa: E731
            rows.append(
                f'<tr id="{esc(b.anchor)}"><td>{esc(b.title)}</td><td>{fv("Когда")}</td><td>{fv("Описание")}</td>'
                f"<td>{self.pm_html(path, self.problems_in(b))}</td></tr>"
            )
        if not blocks and not rows:
            return ""
        intro = (
            f'{self.chg_box(path, own)}<div class="sec-intro{self.cc(own) if self.cfb(own) else ""}">'
            f"{self.blocks(path, own.text, svc)} {self.md_link(own)}</div>"
            if own and own.text
            else ""
        )
        table = (
            '<table class="grid"><thead><tr><th style="width:18%">фоновая работа</th><th style="width:12%">когда</th>'
            f'<th>описание</th><th style="width:60px"></th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
            if rows
            else ""
        )
        return intro + "".join(blocks) + table

    # проблемы, тесты

    def problem_places(self, path: str, svc: str, e: Entity) -> str:
        """Где проявляется проблема: стрелки процессов (номерами), своя работа, точки входа, связи."""
        by_proc: dict[str, list] = {}
        other = []
        for ln in self.m.links:
            if ln.kind != "указатель" or ln.service != svc or ln.key != e.addr:
                continue
            src = self.m.get(self.m._service_of_file(ln.src_file), ln.src)
            if not src:
                continue
            if src.kind == "шаг" and src.extra.get("process") != "own":
                for a in self.m.arrows_to_step(src):
                    lst = by_proc.setdefault(a.process, [])
                    if a not in lst:
                        lst.append(a)
            elif src.kind in ("шаг", "метод", "страница", "функция", "команда", "связь", "связь-метод"):
                r = self.ent_ref(path, src)
                if r not in other:
                    other.append(r)
        parts = [
            f'<span class="muted">{esc(self.process_title(p))}</span> '
            + "".join(self.arrow_link(path, a) for a in arrs)
            for p, arrs in by_proc.items()
        ] + other
        return "; ".join(parts)

    def svc_problems(self, path: str, svc: str) -> str:
        ents = sorted(
            self.m.entries(svc, "проблема"),
            key=lambda e: IMP_ORDER.get(self.importance(e), 3),
        )
        if not ents and not self.gone_of(svc, ("проблема",)):
            return ""
        rows = []
        cols = "130px minmax(360px,2fr) minmax(260px,1.2fr) 150px"
        for e in ents:
            chk = e.fields["Проверено"].value if "Проверено" in e.fields else ""
            places = self.problem_places(path, svc, e)
            body = f'<div class="e-text">{self.blocks(path, e.text, svc)}</div>'
            rows.append(
                f'<details class="ix-r{self.cc(e)}" id="{esc(e.anchor)}"><summary class="ix-s">'
                f"<span>{self.pm_html(path, [e], True)}</span><span class=\"nm\">{self.inline(path, e.title, svc)}{self.ct(e)}</span>"
                f'<span>{places}</span><span class="muted">{esc(chk)}</span></summary>'
                f'<div class="ix-b">{self.chg_box(path, e)}{body}{self.code_refs(e)}</div></details>'
            )
        for e, b in self.gone_of(svc, ("проблема",)):
            rows.append(
                f'<details class="ix-r chg chg-gone" id="{esc(e.anchor)}"><summary class="ix-s">'
                f'<span><span class="pm imp-{IMP_CLASS.get(self.importance(e), "low")}">{esc(self.importance(e))}</span></span>'
                f'<span class="nm">{esc(e.title)}{self.ctag(b)}</span><span></span><span></span></summary>'
                f'<div class="ix-b"><div class="cbox chg-gone">{self.ctag(b)}<span class="why"><span class="lbl">почему</span>'
                f'{self.inline(path, b.why, svc)}</span></div><div class="e-text">{self.blocks(path, e.text, svc)}</div></div></details>'
            )
        head = "".join(f"<span>{h}</span>" for h in ("важность", "проблема", "где проявляется", "проверено"))
        return (
            f'{self.ix_tools(len(ents), False)}<div class="ix" style="--cols:{cols}"><div class="ix-h">{head}</div>'
            f'{"".join(rows)}</div>'
        )

    def svc_tests(self, path: str, svc: str) -> str:
        m = self.m
        t = m.facts.get(svc, {}).get("pytest") or {}
        ents = m.entries(svc, "набор тестов")
        if not t and not ents:
            return ""
        rows = []
        for e in ents:
            col = (t.get("collected") or {}).get(e.addr)
            res = ((t.get("run") or {}).get("results") or {}).get(e.addr, {})
            nums = (
                f"<td>{col}</td><td>{res.get('passed', 0)}</td><td>{res.get('failed', 0)}</td>"
                f"<td>{res.get('skipped', 0)}</td><td>{esc((t.get('run') or {}).get('date', ''))}</td>"
                if col is not None
                else '<td colspan="5" class="muted">фактов нет</td>'
            )
            rows.append(
                f'<tr id="{esc(self.anchor(e))}"><td><code>{esc(e.addr)}</code></td>{nums}'
                f"<td>{self.blocks(path, e.text, svc)}</td></tr>"
            )
        return (
            '<table class="grid"><thead><tr><th style="width:12%">папка</th><th class="nw">собрано</th><th class="nw">прошло</th>'
            '<th class="nw">упало</th><th class="nw">пропущено</th><th class="nw">когда</th><th>почему тесты такие</th></tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    # шаги: срезы участников на странице процесса, своя работа на странице сервиса ---------------------

    def step_block(self, path: str, st: Entity, n: int, extra_head: str = "") -> str:
        """Шаг целиком: номер, имя, стрелки процесса к нему, текст, на что опирается, как ведёт себя вызов, код.

        Шаг пишется в md среза (ASIS/<сервис>/processes/<процесс>.md) или своей работы (own.md); показывается —
        на странице процесса под стрелками или на странице сервиса в «Своей работе»."""
        m, svc = self.m, st.service
        arr = " ".join(
            f'<a class="arr k-{ARROW_CLASS.get(a.kind, "inner")}" href="{esc(self.rel_url(path, self.process_page(a.process), "a-" + a.id))}">'
            f"<b>{esc(a.number)}</b> {esc(self.participant_name(a.sender))} → {esc(self.participant_name(a.receiver))} · {self.plain(a.what)}</a>"
            for a in m.arrows_to_step(st)
        )
        calls = []
        for ln in self.own_links(st):
            if ln.kind != "зовёт":
                continue
            c = m.get(svc, f"{svc} → {ln.service}") if ln.service else None
            if c:
                fl = " · ".join(
                    f'<span class="lbl">{esc(f.lower())}</span>{self.inline(path, c.fields[f].value, svc)}'
                    for f in ("Ожидание", "При отказе")
                    if f in c.fields
                )
                calls.append(
                    f'<li><a href="{esc(self.rel_url(path, self.service_page(svc), self.anchor(c)))}">'
                    f"{esc(self.participant_name(ln.service))}: {esc(ln.key)}</a> — {fl}</li>"
                )
        probs = self.problems_in(st)
        gf = self.gone_fields(path, st)
        return (
            f'<article class="step{self.cc(st)}" id="{esc(self.step_anchor(st))}"><header class="step-head"><span class="step-num">{n}</span>'
            f"<h3>{esc(st.title)}</h3>{extra_head}{self.ct(st)}{self.tools(st, probs, path)}</header>"
            f"{self.chg_box(path, st)}"
            f"{'<div class=arrows-in><span class=lbl>стрелки</span> ' + arr + '</div>' if arr else ''}"
            f'<div class="step-text">{self.blocks(path, st.text, svc)}</div>'
            f"{self.refs_of(path, st)}"
            f"{'<dl class=flds>' + gf + '</dl>' if gf else ''}"
            f"{'<div class=calls><span class=lbl>как ведёт себя вызов</span><ul class=plain>' + ''.join(calls) + '</ul></div>' if calls else ''}"
            "</article>"
        )

    def participants_secs(self, path: str, proc: str) -> list[Sec]:
        """Под стрелками процесса — по листу на участника со срезом: первая фраза среза и его шаги целиком."""
        m = self.m
        out = []
        for p in m.processes[proc].extra["participants"]:
            sl = m.slices.get((p, proc))
            if not sl:
                continue
            steps = [m.get(p, a) for a in sl.extra["steps"]]
            # шаги, которые уходят, — на своём месте среди шагов «как будет», серым и зачёркнуто
            asl = self.asis_m.slices.get((p, proc)) if self.chg else None
            gone = {e.addr for e, _ in self.gone_of(p, ("шаг",))}
            if asl:
                for i, a in enumerate(asl.extra["steps"]):
                    if a not in gone:
                        continue
                    prev = [x for x in asl.extra["steps"][:i] if any(s.addr == x for s in steps)]
                    at = next((k + 1 for k, s in enumerate(steps) if prev and s.addr == prev[-1]), 0)
                    steps.insert(at, self.asis_m.get(p, a))
            body = "".join(self.step_block(path, st, i) for i, st in enumerate(steps, 1))
            html_ = (
                f'<section class="sec" id="u-{esc(p)}"><h2><a href="{esc(self.rel_url(path, self.service_page(p)))}">{esc(p)}</a>'
                f' в этом процессе <span class="cnt">{len(steps)} {plural(len(steps), "шаг", "шага", "шагов")}</span>'
                f'<span class="e-tools">{self.md_link(sl)}</span></h2>'
                f'<div class="sec-intro">{self.blocks(path, sl.text, p)}</div>{body}</section>'
            )
            out.append(Sec(f"u-{p}", p, html_, len(steps)))
        return out

    # процесс -------------------------------------------------------------------------------------

    def stages(self, proc: str) -> list[Entity]:
        return [
            e for e in self.m.entities.values() if e.kind == "этап" and e.parent == proc
        ]

    def arrow_problems(self, proc: str, a) -> list[Entity]:
        out = []
        for ins in a.inside:
            if "#" in ins and not ins.startswith("[["):
                svc, anc = ins.split("#", 1)
                st = self.m.get(svc, f"{svc}/{proc}#{anc}")
                for p in self.problems_in(st) if st else []:
                    if p not in out:
                        out.append(p)
        return out

    def fail_html(self, path: str, a) -> str:
        """«Если не ответили» — у запроса и у внешнего провайдера: ожидание и отказ из «Связей» отправителя."""
        if a.kind not in CALL_KINDS:
            return ""
        c = self.m.get(a.sender, f"{a.sender} → {a.receiver}")
        if not c:
            return ""
        return "".join(
            f'<p><span class="lbl">{lbl}</span>{self.inline(path, c.fields[f].value, a.sender)}</p>'
            for f, lbl in (("Ожидание", "ждёт"), ("При отказе", "при отказе"))
            if f in c.fields
        )

    def inside_html(self, path: str, proc: str, a, seen: dict) -> str:
        """Шаги внутри стрелки: короткое имя, полная фраза — подсказкой; повтор шага — ссылкой «↑ номер»."""
        m = self.m
        items = []
        for ins in a.inside:
            mm = LINK_RE.fullmatch(ins)
            if mm:
                svc, _ = split_key(mm.group(1), self.svcset)
                items.append(
                    f'<li><span class="who">{esc(self.participant_name(svc or ""))}</span>{self.key_tag(path, mm.group(1))}</li>'
                )
                continue
            svc, anc = ins.split("#", 1)
            st = m.get(svc, f"{svc}/{proc}#{anc}")
            if not st:
                continue
            who = f'<span class="who">{esc(svc)}</span>'
            if st.addr in seen:
                prev = seen[st.addr]
                items.append(
                    f'<li>{who}<a class="rep" href="#a-{esc(prev.id)}" title="{esc(self.plain_text(st.first_phrase()))}">'
                    f"↑ {esc(prev.number)} {esc(st.title)}</a></li>"
                )
                continue
            seen[st.addr] = a
            items.append(
                f'<li>{who}<a href="{esc(self.url_entity(path, st))}" title="{esc(self.plain_text(st.first_phrase()))}">{esc(st.title)}</a></li>'
            )
        return f'<ul class="inside">{"".join(items)}</ul>'

    def live_ids(self, pe: Entity) -> set[str]:
        f = pe.fields.get("Работает ли сейчас")
        return set(re.findall(r"`([^`]+)`", f.value)) if f else set()

    def live_html(self, path: str, proc: str, text: str) -> str:
        """«Работает ли сейчас»: id стрелок → номера со схемы."""
        ids = {a.id: a for a in self.m.arrows[proc]}
        extra: dict[str, str] = {}

        def sub(mm: re.Match) -> str:
            a = ids.get(mm.group(1))
            if not a:
                return mm.group(0)
            ph = f"ARRPH{len(extra)}ZZ"
            extra[ph] = self.arrow_link(path, a)
            return ph

        return self.inline(path, re.sub(r"`([^`]+)`", sub, text), extra=extra)

    def participant_link(self, path: str, proc: str, p: str) -> str:
        name = esc(self.participant_name(p))
        url = None
        if p in self.m.registry:
            url = (
                self.rel_url(path, self.process_page(proc), f"u-{p}")
                if (p, proc) in self.m.slices
                else self.rel_url(path, self.service_page(p))
            )
        elif p.startswith("external:"):
            c = self.ext_connection(p)
            url = (
                self.rel_url(path, self.service_page(c.service), self.anchor(c))
                if c
                else None
            )
        if url:
            return f'<a class="pchip" href="{esc(url)}">{name}</a>'
        return f'<span class="pchip">{name}</span>'

    def build_process(self, proc: str) -> None:
        m, path = self.m, self.process_page(proc)
        pe = m.processes[proc]
        arrows = m.arrows[proc]
        parts = pe.extra["participants"]
        sources = {pe.file} | {
            sl.file for (s, p), sl in m.slices.items() if p == proc
        }
        aprobs = {a.id: self.arrow_problems(proc, a) for a in arrows}
        live = self.live_ids(pe)

        def fv(n):
            return self.inline(path, pe.fields[n].value) if n in pe.fields else ""

        allp: dict[str, tuple] = {}
        for a in arrows:
            for p in aprobs[a.id]:
                allp.setdefault(f"{p.service}::{p.addr}", (p, []))[1].append(a)
        probs_html = "<br>".join(
            f"{self.pm_html(path, [p], True)} "
            + "".join(self.arrow_link(path, a) for a in arrs)
            + f' — <a href="{esc(self.url_entity(path, p))}">{esc(self.short_title(p))}</a>'
            for p, arrs in sorted(
                allp.values(), key=lambda x: IMP_ORDER.get(self.importance(x[0]), 3)
            )
        )
        rows = (
            ("Кто запускает", fv("Кто запускает")),
            ("Чем кончается", fv("Чем кончается")),
            (
                "Работает ли сейчас",
                self.live_html(path, proc, pe.fields["Работает ли сейчас"].value)
                if "Работает ли сейчас" in pe.fields
                else "",
            ),
            ("Не происходит", fv("Не происходит")),
            (
                "Участники",
                "".join(self.participant_link(path, proc, p) for p in parts),
            ),
            ("Проблемы на стрелках", probs_html),
        )
        def fact(k: str, v: str) -> str:
            fb = self.field_block(pe, k) if self.chg else None
            if not fb:
                return f"<div><dt>{esc(k)}</dt><dd>{v}</dd></div>"
            old = self.asis_field(path, pe, k) if fb.kind == "меняется" else None
            was = f'<div class="was"><span class="lbl">было</span>{old}</div>' if old is not None else ""
            return f'<div class="chg {self.KIND_CLS[fb.kind]}"><dt>{esc(k)} {self.ctag(fb)}</dt><dd>{v}{was}</dd></div>'

        facts = "".join(fact(k, v) for k, v in rows if v)
        users = self.participants_secs(path, proc)
        # меню страницы — строкой в шапке: схема процесса занимает всю ширину листа, бокового меню здесь нет
        nav = (
            '<nav class="pnav" aria-label="На странице"><a href="#scheme">схема</a><span class="lbl">этапы</span>'
            + " ".join(
                f'<a href="#{esc(st.anchor)}">{st.extra["number"]} {esc(st.title)}</a>'
                for st in self.stages(proc)
            )
            + (
                '<span class="lbl">участники</span>'
                + " ".join(f'<a href="#{esc(u.sid)}">{esc(u.title)}</a>' for u in users)
                if users
                else ""
            )
            + '<span class="lbl">ещё</span><a href="#breaks">где ломается</a> <a href="#data">данные</a></nav>'
        )
        head = self.head(
            esc(pe.title),
            f"процесс · {len(arrows)} {plural(len(arrows), 'стрелка', 'стрелки', 'стрелок')}",
            f'<div class="h-sum">{self.blocks(path, pe.text)}</div><dl class="hfacts">{facts}</dl>{nav}',
        )
        # схема — своим листом на всю ширину; под ней стрелки по этапам; ниже — участники со своими шагами
        kinds = list(dict.fromkeys(a.kind for a in arrows))
        wide = (
            '<section class="page wide-sec"><div class="panel seq" id="scheme">'
            f'<h2>Схема <span class="cnt">{len(parts)} {plural(len(parts), "участник", "участника", "участников")} · '
            f'{len(arrows)} {plural(len(arrows), "стрелка", "стрелки", "стрелок")}</span></h2>'
            f'<div class="seq-scroll">{self.swimlanes(path, proc, aprobs)}</div>'
            + self.legend(
                kinds,
                '<span class="lg-i muted">щелчок по стрелке — её строка ниже; наведение на стрелку или строку — пара</span>',
            )
            + "</div></section>"
        )
        secs = [
            Sec(
                "arrows",
                "Стрелки",
                f'<section class="sec" id="arrows"><h2>Стрелки по этапам <span class="cnt">{len(arrows)}</span></h2>'
                f"{self.arrow_tables(path, proc, aprobs, live)}</section>",
            )
        ] + users + [
            self.section("breaks", "Где ломается", self.process_breaks(path, proc, aprobs)),
            self.section("data", "Данные процесса", self.process_data(path, proc)),
        ]
        if pe.extra.get("related"):
            secs.append(
                self.section(
                    "related",
                    "Связанные процессы",
                    self.blocks(path, pe.extra["related"]),
                )
            )
        self.pages[path] = self.frame(
            path,
            title=pe.title,
            here=("proc", proc),
            stamp=[f"текст {self.git_date(sorted(sources))}"],
            head=head,
            sections=secs,
            sources=sources,
            wide=wide,
            side=False,
        )

    def store_label(self, a) -> str:
        """Подпись хранилища у петли: таблица или файл из «как»."""
        for r in LINK_RE.findall(a.how):
            _, k = split_key(r, self.svcset)
            return k.split(".", 1)[0]
        return ""

    @staticmethod
    def markers(prefix: str, size: int = 8) -> str:
        return "".join(
            f'<marker id="{prefix}-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="{size}" markerHeight="{size}" '
            f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="m-{k}"/></marker>'
            for k in sorted(set(ARROW_CLASS.values()))
        )

    SCHEME_W = 1880  # ширина схемы процесса в px до масштаба: колонка страницы без полей листа

    def arrow_tables(self, path: str, proc: str, aprobs: dict, live: set) -> str:
        """Стрелки по этапам — под схемой: этап — заголовок и абзац, стрелки — таблицей; наведение на строку
        подсвечивает её стрелку на схеме, и наоборот (data-a)."""
        seen: dict = {}
        blocks = []
        for st in self.stages(proc):
            rows = []
            for a, gone in self.stage_arrows(proc, st.anchor):
                k = ARROW_CLASS.get(a.kind, "inner")
                b = self.chg_rows.get((proc, a.id)) if self.chg else None
                cls = f" chg {self.KIND_CLS[b.kind]}" if b else ""
                tag = self.ctag(b) if b else ""
                old = self.asis_arrow(proc, a.id)
                was = (
                    f'<span class="was-n">было {esc(old.number)}</span>'
                    if old and not gone and old.number != a.number
                    else ""
                )
                rows.append(
                    f'<tr class="k-{k}{cls}" id="a-{esc(a.id)}" data-a="{esc(a.id)}"><td class="num">{esc(a.number)}{was}'
                    f"{'' if gone else self.pm_html(path, aprobs.get(a.id, []))}"
                    + ('<span class="live-mark" title="проверено вживую"> вживую</span>' if a.id in live and not gone else "")
                    + f'</td><td class="who-col">{esc(self.participant_name(a.sender))} → {esc(self.participant_name(a.receiver))}'
                    f'<span class="kind-l">{esc(a.kind)}</span></td><td>{self.plain(a.what)}{tag}{self.arrow_was(path, proc, a, b)}</td>'
                    f"<td>{self.inline(path, a.how) if a.how else ''}</td>"
                    f"<td>{'' if gone else self.inside_html(path, proc, a, seen)}</td>"
                    f'<td class="fail">{"" if gone else self.fail_html(path, a)}</td></tr>'
                )
            blocks.append(
                f'<div class="stage-b{self.cc(st)}" id="{esc(st.anchor)}"><h3><span class="stage-n">{st.extra["number"]}</span>'
                f"{esc(st.title)} {self.ct(st)}{self.tools(st)}</h3>{self.blocks(path, st.text)}"
                '<table class="grid arrows"><thead><tr><th style="width:5%">№</th><th style="width:15%">кто → кому</th>'
                '<th style="width:16%">что передаётся</th><th style="width:17%">как</th><th style="width:20%">шаги внутри</th>'
                f"<th>если не ответили</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
            )
        return "".join(blocks)

    def asis_arrow(self, proc: str, aid: str):
        if not self.chg:
            return None
        return next((a for a in self.asis_m.arrows.get(proc, []) if a.id == aid), None)

    def stage_arrows(self, proc: str, stage: str) -> list[tuple]:
        """Стрелки этапа по порядку; в «как будет» — и уходящие из «как есть», на своём месте: (стрелка, уходит ли)."""
        out = [(a, False) for a in self.m.arrows[proc] if a.stage == stage]
        if not self.chg:
            return out
        asis = [a for a in self.asis_m.arrows.get(proc, []) if a.stage == stage]
        for i, a in enumerate(asis):
            b = self.chg_rows.get((proc, a.id))
            if not b or b.kind != "уходит":
                continue
            prev = [x.id for x in asis[:i]]
            at = max((k + 1 for k, (x, _) in enumerate(out) if x.id in prev), default=0)
            out.insert(at, (a, True))
        return out

    def arrow_cls(self, proc: str, a) -> str:
        b = self.chg_rows.get((proc, a.id)) if self.chg else None
        return f" chg {self.KIND_CLS[b.kind]}" if b else ""

    def arrow_was(self, frm: str, proc: str, a, b) -> str:
        """У стрелки «меняется» — что было в столбцах, которые поменялись."""
        if not b or b.kind != "меняется":
            return ""
        old = self.asis_arrow(proc, a.id)
        if not old:
            return ""
        diffs = [
            (name, self.plain(getattr(old, attr)))
            for name, attr in (("что", "what"), ("как", "how"), ("кто → кому", "sender"), ("вид", "kind"))
            if getattr(old, attr) != getattr(a, attr)
        ]
        return "".join(
            f'<div class="was"><span class="lbl">было{"" if n == "что" else " (" + n + ")"}</span>{v}</div>' for n, v in diffs
        )

    def swimlanes(self, path: str, proc: str, aprobs: dict) -> str:
        """Схема последовательности на всю ширину листа: участники — колонки, этапы — полосы, стрелки — по времени
        сверху вниз. Дорожка — ширина листа на число участников, не уже 150 и не шире 340 px: у 9 участников — около
        210 px; у 13 и больше схема шире листа и листается вбок внутри него. Имя участника, которое не влезает
        в дорожку, — мельче."""
        m = self.m
        parts = m.processes[proc].extra["participants"]
        lane = max(150, min(340, self.SCHEME_W // max(len(parts), 1)))
        top, rowh = 64, 50
        w = lane * len(parts)
        x = {p: lane * i + lane / 2 for i, p in enumerate(parts)}
        y, svg = top, []
        for p in parts:
            cls = self.participant_class(p)
            name = self.participant_name(p)
            fs = min(15.5, (lane - 30) / (0.55 * max(len(name), 1)))
            svg.append(
                f'<rect class="s-head-box {cls}" x="{x[p] - lane / 2 + 10}" y="8" width="{lane - 20}" height="34" rx="3"/>'
                f'<text class="s-head" x="{x[p]}" y="31" text-anchor="middle" style="font-size:{fs:.1f}px">{esc(name)}</text>'
                f'<line class="s-lane" x1="{x[p]}" y1="42" x2="{x[p]}" y2="__H__"/>'
            )
        for st in self.stages(proc):
            svg.append(
                f'<line class="s-stage" x1="0" y1="{y}" x2="{w}" y2="{y}"/>'
                f'<text class="s-st" x="4" y="{y + 20}">{st.extra["number"]}. {esc(st.title)}</text>'
            )
            y += 30
            for a, gone in self.stage_arrows(proc, st.anchor):
                cy = y + rowh / 2 + 6
                k = ARROW_CLASS.get(a.kind, "inner")
                x1, x2 = x.get(a.sender, 0), x.get(a.receiver, 0)
                if a.sender == a.receiver:
                    # петля рисуется справа от линии дорожки; у правой дорожки, где до края схемы не хватает
                    # места (подпись — около 7 px на знак), — слева: и хранилище, и подпись
                    left = x1 + 18 + 7 * len(a.what) > w - 4
                    if a.kind in ("база", "файл"):
                        label = self.store_label(a)
                        bw = min(lane - 30, 12 + 7 * len(label))
                        left = left or x1 + 22 + bw > w - 4
                        bx = x1 - 22 - bw if left else x1 + 22
                        tip = bx + bw + 2 if left else bx - 2
                        shape = (
                            f'<path class="s-line" d="M{x1},{cy} L{tip},{cy}" marker-end="url(#sa-{k})"/>'
                            f'<rect class="ln-store" x="{bx}" y="{cy - 12}" width="{bw}" height="24" rx="2"/>'
                            f'<text class="ln-st" x="{bx + 6}" y="{cy + 4}">{esc(label)}</text>'
                        )
                    else:
                        shape = f'<path class="s-line" d="M{x1},{cy - 8} C{x1 + 44},{cy - 26} {x1 + 44},{cy + 26} {x1 + 6},{cy + 10}" marker-end="url(#sa-{k})"/>'
                    lx, anchor = (x1 - 18, "end") if left else (x1 + 18, "start")
                else:
                    d = 8 if x2 > x1 else -8
                    shape = f'<path class="s-line" d="M{x1},{cy} L{x2 - d},{cy}" marker-end="url(#sa-{k})"/>'
                    lx, anchor = (x1 + x2) / 2, "middle"
                pm = (
                    f'<circle class="s-pm" cx="{x1 + 14}" cy="{cy - 12}" r="5"/>'
                    if aprobs.get(a.id) and not gone
                    else ""
                )
                what = esc(a.what.replace("`", ""))
                svg.append(
                    f'<a href="#a-{esc(a.id)}" class="s-arrow k-{k}{self.arrow_cls(proc, a)}" data-a="{esc(a.id)}">{shape}'
                    f'<text class="s-what" x="{lx}" y="{cy - 11 if a.sender != a.receiver else cy - 18}" text-anchor="{anchor}">{what}</text>'
                    f'<circle cx="{x1}" cy="{cy}" r="12"/><text class="s-n" x="{x1}" y="{cy + 4}" text-anchor="middle">{esc(a.number)}</text>{pm}</a>'
                )
                y += rowh
            y += 10
        total = y + 8
        body = "".join(svg).replace("__H__", str(total - 6))
        return (
            f'<svg width="{w}" height="{total}" viewBox="0 0 {w} {total}" role="img" aria-label="Схема процесса">'
            f'<defs>{self.markers("sa")}</defs>{body}</svg>'
        )

    def process_data(self, path: str, proc: str) -> str:
        """Что процесс пишет и читает: хранилище — номерами стрелок; шаг без стрелки — коротким именем."""
        m = self.m
        rows: dict[tuple, dict] = {}
        for ln in m.links:
            target = m.get(ln.service, ln.key)
            if target is None or target.kind not in STORE_KINDS or ln.kind not in ("пишет", "читает"):
                continue
            st = m.get(m._service_of_file(ln.src_file), ln.src)
            if not st or st.kind != "шаг" or st.extra.get("process") != proc:
                continue
            d = rows.setdefault((ln.service, ln.key), {"пишет": [], "читает": []})
            arrs = self.step_arrows(st, ln.service, ln.key, STORE_ARROWS, store=True)
            items = (
                [self.arrow_link(path, a) for a in arrs]
                if arrs
                else [f'<span class="who muted">{esc(st.service)}</span> {self.step_ref(path, st, False)}']
            )
            for it in items:
                if it not in d[ln.kind]:
                    d[ln.kind].append(it)
        if not rows:
            return ""
        out = "".join(
            f"<tr><td>{self.key_tag(path, f'{svc}: {key}')}</td><td>{' '.join(d['пишет'])}</td><td>{' '.join(d['читает'])}</td></tr>"
            for (svc, key), d in rows.items()
        )
        return (
            '<table class="grid"><thead><tr><th style="width:30%">хранилище</th><th>пишет</th><th>читает</th></tr></thead>'
            f"<tbody>{out}</tbody></table>"
        )

    def process_breaks(self, path: str, proc: str, aprobs: dict) -> str:
        by: dict[str, tuple] = {}
        for a in self.m.arrows[proc]:
            for p in aprobs[a.id]:
                lst = by.setdefault(f"{p.service}::{p.addr}", (p, []))[1]
                if a not in lst:
                    lst.append(a)
        if not by:
            return '<p class="muted">На стрелках процесса известных проблем нет.</p>'
        out = []
        for p, arrs in sorted(by.values(), key=lambda x: IMP_ORDER.get(self.importance(x[0]), 3)):
            out.append(
                f"<li><span>{self.pm_html(path, [p], True)}</span><span>"
                f'<a href="{esc(self.url_entity(path, p))}">{esc(p.title)}</a> — '
                f"{'стрелки' if len(arrs) > 1 else 'стрелка'} "
                + "".join(self.arrow_link(path, a) for a in arrs)
                + "</span></li>"
            )
        return f'<ul class="breaks">{"".join(out)}</ul>'

    # доска, указатель, обзор ---------------------------------------------------------------------

    def board_data(self, path: str) -> dict:
        m = self.m
        nodes, edges = [], []
        default = 0

        def place(nid):
            nonlocal default
            if nid in m.board:
                return m.board[nid], False
            default += 1
            return [0, 10 + default], True

        for svc in m.services:
            pos, unplaced = place(svc)
            tables = len(
                (m.facts.get(svc, {}).get("postgres") or {}).get("tables", [])
            ) or len(m.entries(svc, "таблица"))
            readme = m.get(svc, "README.md")
            counts = [
                f"{k} {plural(k, *forms)}"
                for kind, forms in (
                    ("метод", ("метод", "метода", "методов")),
                    ("страница", ("страница", "страницы", "страниц")),
                    ("функция", ("функция", "функции", "функций")),
                    ("команда", ("команда", "команды", "команд")),
                )
                if (k := len(m.entries(svc, kind)))
            ]
            procs = {p for (s, p) in m.slices if s == svc}
            if procs:
                counts.append(f"{len(procs)} {plural(len(procs), 'процесс', 'процесса', 'процессов')}")
            nodes.append(
                {
                    "id": svc,
                    "title": svc,
                    "sub": KIND_RU.get(m.registry[svc].get("kind"), ""),
                    "counts": " · ".join(counts[:3]),
                    "db": f"своя база · {tables} табл." if tables else "",
                    "pm": sum(
                        1
                        for e in m.entries(svc, "проблема")
                        if self.importance(e) == "высокая"
                    ),
                    "x": pos[0],
                    "y": pos[1],
                    "kind": "service",
                    "href": self.rel_url(path, self.service_page(svc)),
                    "unplaced": unplaced,
                    "what": shorten(self.plain_text(readme.text[0]))
                    if readme and readme.text
                    else "",
                }
            )
        for ext, info in m.external.items():
            nid = f"external:{ext}"
            c = self.ext_connection(nid)
            if c or nid in m.board:
                pos, unplaced = place(nid)
                nodes.append(
                    {
                        "id": nid,
                        "title": info.get("name", ext),
                        "sub": "внешний провайдер",
                        "counts": "",
                        "db": "",
                        "pm": 0,
                        "x": pos[0],
                        "y": pos[1],
                        "kind": "external",
                        "href": self.rel_url(path, self.service_page(c.service), self.anchor(c)) if c else "",
                        "unplaced": unplaced,
                        "what": info.get("what", ""),
                    }
                )
        humans = sorted(
            {a.receiver for arrows in m.arrows.values() for a in arrows if a.sender == "human"}
        )
        if humans or "human" in m.board:
            pos, unplaced = place("human")
            nodes.append(
                {
                    "id": "human",
                    "title": "человек",
                    "sub": f"открывает {', '.join(humans)}" if humans else "",
                    "counts": "",
                    "db": "",
                    "pm": 0,
                    "x": pos[0],
                    "y": pos[1],
                    "kind": "human",
                    "href": "",
                    "unplaced": unplaced,
                    "what": "",
                }
            )
            for h in humans:
                has_pages = h in m.registry and m.entries(h, "страница")
                edges.append(
                    {
                        "from": "human",
                        "to": h,
                        "kind": "human",
                        "label": "",
                        "w": 1,
                        "title": "человек на страницах интерфейса",
                        "href": self.rel_url(path, self.service_page(h), "pages" if has_pages else None)
                        if h in m.registry
                        else "",
                    }
                )
        for st in m.settings.get("stores") or []:
            pos, unplaced = place(st)
            nodes.append(
                {
                    "id": st,
                    "title": st,
                    "sub": "общее хранилище",
                    "counts": "",
                    "db": "",
                    "pm": 0,
                    "x": pos[0],
                    "y": pos[1],
                    "kind": "store",
                    "href": "",
                    "unplaced": unplaced,
                    "what": "",
                }
            )
        pairs: dict[tuple, list[str]] = {}
        for proc, arrows in m.arrows.items():
            for a in arrows:
                if a.sender != a.receiver:
                    pairs.setdefault(tuple(sorted((a.sender, a.receiver))), []).append(
                        m.processes[proc].title
                    )
        for svc in m.services:
            for c in m.connections(svc):
                to = c.extra.get("to", "")
                keys = [
                    e.title
                    for e in m.by_service[svc]
                    if e.kind == "связь-метод" and e.parent == c.addr
                ]
                procs = sorted(set(pairs.get(tuple(sorted((svc, to))), [])))
                edges.append(
                    {
                        "from": svc,
                        "to": to,
                        "kind": "external" if to.startswith("external:") else "request",
                        "label": c.fields["Подпись"].value if "Подпись" in c.fields else "",
                        "broken": "Не доходит" in c.fields,
                        "w": len(keys) or 1,
                        "title": "; ".join(keys) + (f" — в процессах: {', '.join(procs)}" if procs else ""),
                        "href": self.rel_url(path, self.service_page(svc), self.anchor(c)),
                    }
                )
        routes = {}
        for proc, arrows in sorted(m.arrows.items()):
            routes[proc] = [
                [a.sender, a.receiver, a.number] for a in arrows if a.sender != a.receiver
            ]
        return {"nodes": nodes, "edges": edges, "routes": routes}

    def build_board(self) -> None:
        """Доска: вся система одной схемой на белом листе, справа процессы — наведение проводит путь процесса;
        ниже — главные проблемы, сервисы, все связи."""
        m, path = self.m, self.board_page()
        data = self.board_data(path)
        if self.chg:  # «как будет»: судьба узла из TOBE/board.yaml — changes, new, gone, open
            for n in data["nodes"]:
                st = (self.chg.board.get(n["id"]) or {}) if isinstance(self.chg.board.get(n["id"]), dict) else {}
                n["st"] = st.get("status", "")
                n["stw"] = st.get("why", "")
        nodes, edges = data["nodes"], data["edges"]
        js = json.dumps(data, ensure_ascii=False, sort_keys=True)
        probs = [
            e
            for e in m.entities.values()
            if e.kind == "проблема" and self.importance(e) == "высокая"
        ]
        prob_items = "".join(
            f'<li><span>{self.pm_html(path, [e], True)}</span><span><b>{esc(e.service)}</b> — '
            f'<a href="{esc(self.url_entity(path, e))}">{esc(self.short_title(e))}</a>'
            + (f" · {pl}" if (pl := self.problem_places(path, e.service, e)) else "")
            + "</span></li>"
            for e in probs
        )
        prob_html = (
            f'<ul class="breaks">{prob_items}</ul>'
            if prob_items
            else '<p class="muted">Высоких проблем нет.</p>'
        )
        groups: dict[str, list[tuple[str, Entity]]] = {}
        for proc, pe in sorted(m.processes.items()):
            first = m.arrows[proc][0].sender if m.arrows.get(proc) else ""
            g = (
                "Запускает человек"
                if first == "human"
                else ("По расписанию" if first == "schedule" else "По событию")
            )
            groups.setdefault(g, []).append((proc, pe))
        route_html = "".join(
            f'<h3 class="sub">{esc(g)}</h3><ul class="routes">'
            + "".join(
                f'<li data-proc="{esc(proc)}"><a href="{esc(self.rel_url(path, self.process_page(proc)))}">{esc(pe.title)}</a>'
                f'<span class="rw">{esc(", ".join(self.participant_name(p) for p in pe.extra["participants"]))}'
                f" · {len(m.arrows.get(proc, []))} {plural(len(m.arrows.get(proc, [])), 'стрелка', 'стрелки', 'стрелок')}</span></li>"
                for proc, pe in v
            )
            + "</ul>"
            for g, v in groups.items()
        )
        kind_ru = {"request": "запрос", "external": "внешний провайдер", "human": "человек"}
        toggles = "".join(
            f'<label class="lk k-{k}"><input type="checkbox" checked autocomplete="off" data-kind="{k}">'
            f'<svg width="36" height="10" aria-hidden="true"><line class="s-line" x1="1" y1="5" x2="35" y2="5"/></svg>'
            f"{esc(kind_ru[k])}</label>"
            for k in dict.fromkeys(e["kind"] for e in edges)
        )
        if any(e.get("broken") for e in edges):
            toggles += (
                '<label class="lk"><input type="checkbox" checked autocomplete="off" data-kind="broken">'
                '<svg width="36" height="10" aria-hidden="true"><line x1="1" y1="5" x2="35" y2="5" stroke="var(--ink-2)" '
                'stroke-width="2.5" stroke-dasharray="5 5"/></svg>не доходит</label>'
            )
        unplaced = [n["title"] for n in nodes if n["unplaced"]]
        legend = (
            f'<div class="legend bp-legend">{toggles}'
            '<span class="lg-i"><span class="pm imp-high"></span>высокие проблемы сервиса</span>'
            '<span class="lg-i"><svg width="36" height="12" aria-hidden="true"><rect x="1" y="1" width="34" height="10" fill="none" '
            'stroke="var(--k-db)" stroke-width="1.5"/></svg>своя база</span>'
            + (
                f'<span class="lg-i muted">не размещены в project/board.yaml: {esc(", ".join(unplaced))}</span>'
                if unplaced
                else ""
            )
            + "</div>"
        )
        tools = (
            '<div class="board-tools"><button data-b="fit" title="Показать всю доску">Вписать</button>'
            '<button data-b="out" title="Отдалить">−</button><span class="pct" data-b="pct">100 %</span>'
            '<button data-b="in" title="Приблизить">+</button>'
            '<button data-b="full" title="Во весь экран (Esc — выйти)">Во весь экран</button>'
            '<button data-b="copy" title="Скопировать раскладку для project/board.yaml">Скопировать раскладку</button>'
            '<button data-b="reset" title="Вернуть раскладку из project/board.yaml">Сбросить</button></div>'
        )
        title = esc(m.settings.get("title", "Карта"))
        n_high = len(probs)
        nums = (
            '<ul class="nums">'
            f'<li><a href="#services"><b>{len(m.services)}</b> {plural(len(m.services), "сервис", "сервиса", "сервисов")}</a></li>'
            f'<li><b>{len(m.processes)}</b> {plural(len(m.processes), "процесс", "процесса", "процессов")}</li>'
            f'<li><a href="#all-links"><b>{len(edges)}</b> {plural(len(edges), "связь", "связи", "связей")} на доске</a></li>'
            + (
                f'<li><span class="lbl">проблемы</span><a class="pm imp-high" href="#problems">{n_high} '
                f"{plural(n_high, 'высокая', 'высокие', 'высоких')}</a></li>"
                if n_high
                else '<li class="muted">высоких проблем нет</li>'
            )
            + "</ul>"
        )
        head = self.head(
            title,
            "доска",
            '<p class="h-sum">Вся система одной схемой. Колесо мыши — масштаб, перетащить фон — сдвиг, перетащить '
            "прямоугольник — переставить, браузер это помнит. Щелчок по прямоугольнику — страница сервиса, по линии — "
            "связь у того, кто зовёт. Наведите на процесс справа — его путь пройдёт по доске с номерами стрелок.</p>"
            + nums,
        )
        wide = (
            '<section class="page wide-sec"><div class="panel board-panel" data-board-panel>'
            f'<div class="bp-main"><div class="board" data-board><script type="application/json" class="board-data">{js}</script>'
            f'{tools}<svg class="board-svg" role="img" aria-label="Доска сервисов"></svg></div>{legend}</div>'
            f'<aside class="bp-side"><h2>Процессы <span class="cnt">{len(m.processes)}</span></h2>{route_html}</aside>'
            "</div></section>"
        )
        svc_rows = []
        for n in nodes:
            if n["kind"] != "service":
                continue
            svc = n["id"]
            by: dict[str, list[Entity]] = {}
            for p in m.entries(svc, "проблема"):
                by.setdefault(self.importance(p), []).append(p)
            pm = " ".join(
                f'<a class="pm imp-{IMP_CLASS[k]}" href="{esc(self.rel_url(path, self.service_page(svc), "problems"))}" '
                f'title="{esc(k)}">{len(by[k])}</a>'
                for k in ("высокая", "средняя", "низкая")
                if by.get(k)
            )
            t = m.facts.get(svc, {}).get("pytest") or {}
            if t:
                col = sum((t.get("collected") or {}).values())
                passed = sum(
                    r.get("passed", 0) for r in ((t.get("run") or {}).get("results") or {}).values()
                )
                tests = f"{passed} из {col}"
            else:
                tests = '<span class="muted">фактов нет</span>'
            svc_rows.append(
                f'<tr class="row-link" data-href="{esc(n["href"])}"><td><a href="{esc(n["href"])}">{esc(n["title"])}</a>'
                + (
                    f'<span class="ctag {self.KIND_CLS.get(ST_RU.get(n.get("st", "")), "")}" title="{esc(n.get("stw", ""))}">'
                    f'{esc(ST_RU.get(n.get("st", ""), n.get("st", "")))}</span>'
                    if n.get("st")
                    else ""
                )
                + f'<span class="kind-l">{esc(n["sub"])}</span></td>'
                f"<td>{esc(n['counts'])}</td><td>{esc(n['db']) or '<span class=muted>—</span>'}</td><td class=\"nw\">{tests}</td>"
                f"<td class=\"nw\">{pm or '<span class=muted>нет</span>'}</td><td>{esc(n['what'])}</td></tr>"
            )
        names = {n["id"]: n for n in nodes}

        def node_link(nid):
            n = names.get(nid)
            if not n:
                return esc(nid)
            return f'<a href="{esc(n["href"])}">{esc(n["title"])}</a>' if n["href"] else esc(n["title"])

        all_links = "".join(
            f"<tr><td>{node_link(e['from'])}</td><td>{node_link(e['to'])}</td><td>{esc(kind_ru.get(e['kind'], e['kind']))}</td>"
            f"<td>{esc(e.get('label', ''))}</td><td>{esc(e.get('title', ''))}</td></tr>"
            for e in edges
        )
        secs = [
            self.section("problems", "Главные проблемы", prob_html),
            self.section(
                "services",
                "Сервисы",
                '<table class="grid"><thead><tr><th style="width:11%">сервис</th><th style="width:15%">точки входа</th>'
                '<th style="width:12%">хранит</th><th class="nw" style="width:7%">тесты</th><th class="nw" style="width:9%">'
                "проблемы</th><th>что делает</th></tr></thead>"
                f'<tbody>{"".join(svc_rows)}</tbody></table>'
                if svc_rows
                else "",
                len(m.services),
            ),
            self.section(
                "all-links",
                "Все связи",
                '<table class="grid"><thead><tr><th>откуда</th><th>куда</th><th>вид</th><th>подпись</th><th>методы и процессы</th></tr></thead>'
                f"<tbody>{all_links}</tbody></table>"
                if all_links
                else "",
                len(edges),
                collapsed=True,
            ),
        ]
        files = sorted(m.files)
        self.pages[path] = self.frame(
            path,
            title="Доска",
            here=("board", None),
            stamp=[f"текст {self.git_date(files)}"],
            head=head,
            sections=secs,
            sources=set(files) | {"project/board.yaml", "project/services.yaml"},
            wide=wide,
            side=False,
        )

    def decider_to(self) -> str:
        """К кому вопросы изменения — decider.to из настроек проекта."""
        return (self.m.settings.get("decider") or {}).get("to") or "человеку"

    def build_keys(self) -> None:
        """Список ключей для поиска в шапке — ASIS/keys.js. Отдельной страницы указателя нет:
        строка поиска любой страницы показывает найденное выпадающим списком. Запись — имя, сервис, вид, что
        (первая фраза), адрес от корня карты; порядок — по реестру сервисов и месту в md."""
        m, path = self.m, "ASIS/keys.js"
        skip = {"документ", "раздел", "связь-метод", "срез", "своя работа"}
        keys = []
        for e in sorted(
            m.entities.values(),
            key=lambda e: (
                m.services.index(e.service) if e.service in m.services else 99,
                e.file,
                e.line,
                e.addr,
            ),
        ):
            if e.kind in skip:
                continue
            what = m.what(e)
            tc = m.column_facts(e.service or "", e.addr) if e.kind == "колонка" else None
            comment = (tc[1].get("db_comment") or tc[1].get("comment")) if tc else ""
            if comment and comment != what:  # описание колонки — первым: по нему ищут по-русски («статус»)
                what = comment + (f" — {what}" if what else "")
            if e.kind == "связь":
                label = f"→ {self.participant_name(e.extra.get('to', ''))}"
            elif e.kind in NAMED_KINDS:
                label = self.short_title(e)
            else:
                label = e.addr
            keys.append(
                {
                    "n": label,
                    "s": e.service or "",
                    "k": e.kind,
                    "w": shorten(self.plain_text(what or ""), 140),
                    "u": self.url_entity(path, e),
                }
            )
        body = json.dumps(keys, ensure_ascii=False, sort_keys=True, indent=0)
        self.pages[path] = (
            "/* Ключи карты для поиска в шапке страниц. Собирает tools/build.py — руками не править.\n"
            "   n — имя, s — сервис, k — вид, w — что (первая фраза), u — адрес от папки ASIS/. */\n"
            f"window.MAP_KEYS = {body};\n"
        )

    def build_overview(self) -> None:
        """Обзор системы для Claude — ASIS/README.md."""
        m = self.m
        out = [
            f"# {m.settings.get('title', 'Карта')} — сервисы и процессы",
            "",
            "## Сервисы",
            "",
        ]
        if not m.services:
            out.append("сервисов нет")
        for svc in m.services:
            r = m.get(svc, "README.md")
            phrase = first_phrase(r.text[0]) if r and r.text else ""
            phrase = phrase[:1].lower() + phrase[1:].rstrip(".")
            out.append(f"- {svc} — {phrase} · `ASIS/{svc}/README.md`")
        out += ["", "## Процессы", ""]
        if not m.processes:
            out.append("процессов нет")
        groups: dict[str, list[str]] = {}
        for proc, pe in sorted(m.processes.items()):
            first = m.arrows[proc][0].sender if m.arrows.get(proc) else ""
            g = (
                "Запускает человек"
                if first == "human"
                else ("По расписанию" if first == "schedule" else "По событию")
            )
            ph = first_phrase(pe.text[0]) if pe.text else ""
            ph = ph[:1].lower() + ph[1:].rstrip(".")
            groups.setdefault(g, []).append(
                f"- {proc} — {pe.title}: {ph} · `ASIS/_processes/{proc}.md`"
            )
        for g in ("Запускает человек", "По расписанию", "По событию"):
            if g in groups:
                out += [f"### {g}", "", *groups[g], ""]
        self.pages["ASIS/README.md"] = "\n".join(out).rstrip("\n") + "\n"

    # всё -----------------------------------------------------------------------------------------

    def build_all(self) -> None:
        """«Как есть» — все страницы, ключи для поиска, обзор системы; идёт изменение — и страницы «как будет»."""
        for svc in self.m.services:
            if (self.root / "ASIS" / svc).is_dir():
                self.build_service(svc)
        for proc in self.m.processes:
            self.build_process(proc)
        self.build_board()
        self.build_keys()
        self.build_overview()
        change = ChangeModel(self.root, self.m)
        if change.open and change.world is not None:
            tobe = Site(change.world, change=change, root=self.root)
            tobe.build_change()
            self.pages.update(tobe.pages)
            self.sources.update(tobe.sources)
            self.change = change


def md_rel(root: Path, arg: str) -> str:
    """Путь md от корня карты: принимает и полный путь, и путь от корня репо, и от корня карты."""
    p = Path(arg)
    if p.is_absolute():
        return p.resolve().relative_to(root.resolve()).as_posix()
    rel = arg.replace("\\", "/")
    prefix = root.name + "/"
    return rel[len(prefix):] if rel.startswith(prefix) else rel


def page_of(md: str) -> tuple[str, str] | None:
    """Своя страница md: ("svc", сервис) или ("proc", процесс); у файлов «как будет» — нет."""
    parts = md.split("/")
    if len(parts) < 3 or parts[0] != "ASIS":
        return None
    if parts[1] == "_processes":
        return "proc", Path(parts[2]).stem
    if len(parts) == 4 and parts[2] == "processes":  # срез показывается на странице процесса
        return "proc", Path(parts[3]).stem
    return "svc", parts[1]


def own(root: Path, md: str) -> int:
    """Хук после правки md: четыре списка и только своя страница. Код выхода 2 — в md ошибки (так хук показывает их)."""
    m = MapModel(root)
    r = checks.run(m)
    svc = md.split("/")[1] if md.startswith("ASIS/") and md.count("/") >= 2 else None
    mine = [e for e in m.errors if e.startswith((md + ":", md + " "))]
    broken = [  # имя md ищется в тексте сообщения, а не в пути его файла: чужой settings.md — не ссылка на этот
        e for e in m.errors
        if not e.startswith(md)
        and (Path(md).name in e.partition(" — ")[2] or (svc and f"у {svc} не найден" in e))
    ]
    pairs = [x for x in r.errors + r.warnings if x.startswith((md + ":", md + " "))]
    lines = anchors.Lines(m.repo)
    new_refs = []
    for folder, key, where in anchors.missing(m):
        if any(w.startswith(md + ":") for w in where):
            path, _, n = key.rpartition(":")
            new_refs.append(f"{key} → {anchors.stored(lines.text(path, int(n)) or 'строки нет')}")
    for title, items in (("ошибки md", mine), ("сломанные ссылки на этот md", broken), ("ждёт пары", pairs),
                         ("новые ссылки на код", new_refs)):
        if items:
            print(f"{title} ({len(items)}):")
            for x in items:
                print(f"  {x}")
    page = page_of(md)
    if mine:
        print("страница не собрана: в md ошибки")
        return 2
    if (root / "TOBE" / "README.md").is_file():  # карта собирается на закрытии (PROCESS.md, 6.5)
        print("страница не собирается: идёт изменение — карту собирает закрытие")
        return 0
    if page and page[0] == "proc" and page[1] not in m.processes:
        print(f"страница не собрана: процесса {page[1]} нет — срез покажется, когда появится ASIS/_processes/{page[1]}.md")
        return 0
    if page:
        site = Site(m)
        (site.build_service if page[0] == "svc" else site.build_process)(page[1])
        for rel, text in site.pages.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(text.encode("utf-8"))
        print(f"страница собрана: {', '.join(sorted(site.pages))}")
    return 0


def staged_md(root: Path) -> list[str]:
    """md карты из коммита (git diff --cached)."""
    import subprocess

    res = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--name-only", "--", "."],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                         encoding="utf-8").stdout.strip()
    out = []
    for name in res.stdout.split():
        p = (Path(top) / name).resolve()
        try:
            rel = p.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        if rel.endswith(".md"):
            out.append(rel)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Генератор страниц карты")
    ap.add_argument("md", nargs="?", help="md карты: собрать его страницу и зависимые (с --own — только свою)")
    ap.add_argument("--root", help="корень карты (папка с project/settings.yaml)")
    ap.add_argument(
        "--check",
        action="store_true",
        help="ничего не писать: страницы совпадают со свежей сборкой",
    )
    ap.add_argument("--own", action="store_true", help="с md: проверки md и только его страница (хук)")
    ap.add_argument("--staged", action="store_true", help="с --check: только md из коммита, без сборки и сверки страниц — их собирает закрытие")
    a = ap.parse_args()
    root = Path(a.root) if a.root else Path(__file__).resolve().parent.parent
    if not (root / "project" / "settings.yaml").is_file():
        print(f"{root} — не корень карты: нет project/settings.yaml", file=sys.stderr)
        return 2
    if a.md and a.own:
        return own(root, md_rel(root, a.md))
    only = {md_rel(root, a.md)} if a.md else (set(staged_md(root)) if a.staged else None)
    if a.staged and not only:
        print("в коммите нет md карты — проверять нечего")
        return 0
    model = MapModel(root)
    report = checks.run(model)  # проверки карты поверх модели: пары между файлами, факты, язык, секреты

    def mine(msg: str) -> bool:  # с md или --staged — только сообщения об этих md
        return only is None or any(msg.startswith((x + ":", x + " ")) for x in only)

    errs = [e for e in model.errors + report.errors if mine(e)]
    for e in errs:
        print("ошибка:", e)
    for w in model.warnings + report.warnings:
        if mine(w):
            print("предупреждение:", w)
    kit = Path(__file__).resolve().parent.parent
    if (
        root.resolve() != kit and not a.check
    ):  # другая карта (проверочная, пробная) — оформление копией
        (root / "_shared").mkdir(parents=True, exist_ok=True)
        for name in ("page.css", "page.js"):
            (root / "_shared" / name).write_bytes((kit / "_shared" / name).read_bytes())
    site = Site(model)
    # карта собирается на закрытии (PROCESS.md, 6.5): проверка при коммите и --check посреди изменения — только md;
    # страницы сверяются, когда изменения нет (после очистки «как будет» на закрытии)
    no_pages = a.staged or (a.check and (root / "TOBE" / "README.md").is_file())
    if not no_pages:
        site.build_all()
    bad = 0
    common = ("ASIS/keys.js", "ASIS/README.md", "ASIS/01_service-map.html")  # зависят от всех md
    for rel, text in sorted(site.pages.items()):
        p = root / rel
        if only is not None and not (site.sources.get(rel, set()) & only) and rel not in common:
            continue  # страница не зависит от md из запроса
        if a.check:
            old = p.read_text(encoding="utf-8") if p.is_file() else None
            if old is None or STAMP_RE.sub("", old) != STAMP_RE.sub("", text):
                print(
                    f"{rel} — страница не совпадает со свежей сборкой: нужна сборка build.py"
                )
                bad += 1
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    built = set(site.pages)
    change = getattr(site, "change", None)
    tobe_errs: list[str] = []
    if only is None or any(x.startswith("TOBE/") for x in only):
        tobe_report = tobe_checks.run(model, change) if change else tobe_checks.run(model, ChangeModel(root, model))
        tobe_errs = (change.errors + change.world.errors if change else []) + tobe_report.errors
    for e in tobe_errs:
        print("ошибка «как будет»:", e)
    bad += len(tobe_errs)
    for p in sorted([*(root / "ASIS").rglob("*.html"), *(root / "TOBE").rglob("*.html")]) if only is None and not no_pages else []:
        rel = p.relative_to(root).as_posix()
        if rel not in built:
            if a.check:
                print(f"{rel} — html без md")
                bad += 1
            else:
                p.unlink()
    if a.check:  # №24: ссылка на код, которой нет в запомненных строках
        for folder, key, where in anchors.missing(model):
            if only is None or any(w.rsplit(":", 1)[0] in only for w in where):
                print(f"ошибка: {where[0]} — ссылка {key} не запомнена в {folder}/.anchors.json: нужна полная сборка build.py")
                bad += 1
    elif only is not None:  # md и зависимые страницы; строки кода запоминает только полная сборка
        print(f"собраны страницы, зависящие от: {', '.join(sorted(only))}")
    else:  # полная сборка запоминает текст новых ссылок на код и забывает ушедшие
        added = forgot = 0
        for folder, (data, n_new, n_old) in anchors.remember(model).items():
            p = root / folder / ".anchors.json"
            text = anchors.dump(data)
            if not p.is_file() or p.read_text(encoding="utf-8") != text:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(text.encode("utf-8"))
            added, forgot = added + n_new, forgot + n_old
        print(f"собрано: {len(site.pages)} файлов в {root}; строк кода запомнено новых: {added}, забыто: {forgot}")
    return 1 if errs or bad else 0


if __name__ == "__main__":
    sys.exit(main())
