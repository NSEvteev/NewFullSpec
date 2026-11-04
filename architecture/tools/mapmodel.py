"""Модель карты: разбирает md, факты и yaml карты в сущности и ссылки.

Зачем. Генератор страниц, проверки, поиск find.py, «где мы» where.py и «сделано» done.py должны видеть карту одинаково.
Поэтому разбор md — только здесь: своего разбора ни у кого из них нет. Модель знает, что где лежит (по пути файла),
какие в файле разделы, поля, ссылки [[…]], строки «Код:», таблицы стрелок процессов, — и что из этого следует:
кто вызывает метод, какие шаги его обрабатывают, кто пишет и кто читает хранилище.

Кто зовёт. build.py, find.py, where.py, done.py — через load(<корень карты>). Сам по себе модуль ничего не печатает
и не пишет. Отладочный вызов:  python tools/mapmodel.py [<корень карты>]  — сводка сущностей и ошибок разбора;
python tools/mapmodel.py --stubs ASIS/orders  — заглушки выгрузки (???, {#?}, id стрелки ?<этап>-<номер>) в файлах,
чей путь от корня карты начинается так; без пути — все. Код выхода с --stubs: 0 — заглушек нет, 1 — есть.

Что читает. <корень карты>/project/*.yaml, ASIS/**.md (кроме собранного ASIS/README.md), ASIS/*/.facts.json.
Корень карты — папка с project/settings.yaml; корень репо (для ссылок «Код:») — папка над ним.

Чего не делает. В модели нет git, чтения кода и проверок карты между файлами: это слои поверх модели. Здесь только
проверки одного файла, которые видны при разборе (формат, ссылки md → md, ключи, строки «Код:», процесс) — список errors.
Недописанный md не роняет разбор: ошибка уходит в errors, остальные файлы разбираются.

Коды выхода отладочного вызова: 0 — ошибок разбора нет; 1 — есть.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REFERENCE_FILES = (
    "methods",
    "exports",
    "pages",
    "commands",
    "storage",
    "settings",
    "problems",
    "tests",
)
LINK_KINDS = ("обрабатывает", "зовёт", "пишет", "читает")
ARROW_KINDS = (
    "человек",
    "запрос",
    "переход браузера",
    "внешний провайдер",
    "Redis",
    "файл",
    "база",
    "внутри сервиса",
)
LOOP_KINDS = ("файл", "база", "внутри сервиса")
KIND_RU = {  # вид сервиса из реестра (kind) — словами
    "service": "сервис",
    "frontend": "интерфейс",
    "package": "общий пакет",
    "cli": "программа командной строки",
    "library": "библиотека",
    "ci": "задание CI",
}
STORE_PREFIX = {
    "Файл данных: ": "файл данных",
    "Папка: ": "папка",
    "Ключ Redis: ": "ключ Redis",
    "Память браузера: ": "память браузера",
}
SETTINGS_GROUPS = ("Настройки", "Другие настройки", "Зашито в коде", "Фоновая работа", "Ограничители")


def path_order(p: Path) -> list[str]:
    """Порядок файлов один на любой системе: по частям пути, без регистра. sorted() по Path на Windows не различает
    регистр, а на Linux различает: README.md встал бы раньше methods.md, и вывод инструментов зависел бы от системы."""
    return [part.casefold() for part in p.parts]


def lane_rank(part: str) -> int:
    """Место участника процесса по виду: human, schedule, сервисы, external:…, redis, folder:… (STANDARD, раздел 6)."""
    if part in ("human", "schedule"):
        return ("human", "schedule").index(part)
    if part.startswith("external:"):
        return 3
    if part == "redis":
        return 4
    if part.startswith("folder:"):
        return 5
    return 2
FIXED_SECTIONS = {
    "Как устроен",
    "Связи",
    "Кто подключает",
    "Настройки",
    "Зашито в коде",
    "Фоновая работа",
    "Ограничители",
    "Куда уходят запросы",
    "Связанные процессы",
}
ANCHOR_KIND = {
    "p-": "проблема",
    "bg-": "фоновая работа",
    "lim-": "ограничитель",
    "other-": "другие настройки",
}

# поля по видам разделов; «обязательные» — для проверки №1
FIELDS = {
    "метод": [
        "Группа",
        "Вид",
        "Что делает",
        "Ошибки",
        "Доступ",
        "События",
        "Поля",
        "Вручную",
        "Справочник",
        "Проблемы",
        "Код",
    ],
    "функция": ["Что делает", "Аргументы", "Ошибки", "Справочник", "Проблемы", "Код"],
    "страница": ["Что на странице", "Кому видна", "Справочник", "Проблемы", "Код"],
    "команда": [
        "Аргументы",
        "Что делает",
        "Кто запускает",
        "Справочник",
        "Проблемы",
        "Код",
    ],
    "таблица": ["Единицы", "Код"],
    "колонка": ["Хранится", "Означает", "Пример", "Код"],
    "файл данных": ["Формат", "Сколько", "Колонки", "Код"],
    "папка": ["Путь у сервиса", "Код"],
    "ключ Redis": ["Тип", "Живёт", "События", "Код"],
    "память браузера": ["Где", "Код"],
    "настройка": ["Код"],
    "другая настройка": ["Значение", "Код"],
    "постоянная": ["Значение", "Код"],
    "фоновая работа": ["Когда", "Описание"],
    "ограничитель": [
        "Сколько",
        "Где действует",
        "Где хранится",
        "При превышении",
        "Код",
    ],
    "проблема": ["Важность", "Проверено", "Смотри", "Код"],
    "набор тестов": ["Код"],
    "связь": [
        "Подпись",
        "Адрес",
        "Вход",
        "Ожидание",
        "При отказе",
        "Не доходит",
        "Код",
    ],
    "раздел": ["Код"],
    "шаг": ["Справочник", "Проблемы", "Код"],
    "процесс": [
        "Кто запускает",
        "Чем кончается",
        "Работает ли сейчас",
        "Не происходит",
        "Участники",
        "Группа",
    ],
    "этап": [],
    "правила прокси": ["Адрес", "Код"],
}
REQUIRED = {
    "метод": ["Группа", "Что делает", "Доступ", "Код"],
    "функция": ["Что делает", "Код"],
    "страница": ["Что на странице", "Кому видна", "Код"],
    "команда": ["Что делает", "Кто запускает", "Код"],
    "постоянная": ["Значение", "Код"],
    "фоновая работа": ["Когда", "Описание"],
    "ограничитель": [
        "Сколько",
        "Где действует",
        "Где хранится",
        "При превышении",
        "Код",
    ],
    "проблема": ["Важность", "Проверено"],
    "шаг": ["Код"],
    "процесс": ["Кто запускает", "Чем кончается", "Работает ли сейчас", "Участники"],
}
ALL_FIELDS = sorted({f for fs in FIELDS.values() for f in fs}, key=len, reverse=True)
FIELD_RE = re.compile(
    r"^(" + "|".join(re.escape(f) for f in ALL_FIELDS) + r"):(?: (.*))?$"
)
HEAD_RE = re.compile(r"^(#{1,4}) (.+?)(?: \{#([a-z0-9-]+|\?)\})?\s*$")
STUB = "???"  # заглушка выгрузки: значение, которое пишущий ещё не заполнил
CODE_PART_RE = re.compile(r"`[^`]*`|\?\?\?|[^`\s·][^`·]*?(?=\s*(?:·|$))")
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MDLINK_RE = re.compile(r"\]\(([^)\s]+?\.md)(?:#([a-z0-9-]+))?\)")
CODE_REF_RE = re.compile(r"`([^`\s]+?):(\d+)`")
LIVE_REF_RE = re.compile(
    r"`(живая база|живой ответ|живой файл|живой диск|журнал контейнера|прогон тестов|"
    r"живой Redis|живой /openapi\.json)[^`]*·\s*\d{4}-\d{2}-\d{2}`"
)
INLINE_CODE_RE = re.compile(r"`[^`]*`")


# ─── сущности и ссылки ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CodeRef:
    path: str  # от корня репо, через /
    line: int
    md: str  # откуда ссылка: md-файл от корня карты
    md_line: int


@dataclass
class Field:
    name: str
    value: str  # одна строка; у списка — пусто
    items: list[str]  # пункты списка под полем
    line: int


@dataclass
class Entity:
    addr: str  # адрес: ключ в сервисе, «<сервис>/<процесс>#<якорь>» у шага, ключ процесса…
    kind: (
        str  # вид из таблицы видов ключей или служебный: раздел, связь, срез…
    )
    service: str | None  # сервис-хозяин; у процесса и этапа — None
    file: str  # md от корня карты
    line: int  # строка заголовка (у файла — 1)
    title: str  # заголовок как в md, без якоря
    anchor: str | None = None
    level: int = 0
    parent: str | None = (
        None  # адрес родителя (у колонки — таблица, у метода связи — связь)
    )
    fields: dict[str, Field] = field(default_factory=dict)
    text: list[str] = field(
        default_factory=list
    )  # абзацы и списки текста — строками md
    table: list[dict] = field(
        default_factory=list
    )  # строки таблицы раздела (стрелки, правила прокси, колонки файла)
    code: list[CodeRef] = field(default_factory=list)
    live: list[str] = field(default_factory=list)  # живые источники в «Код:»
    extra: dict = field(default_factory=dict)

    def first_phrase(self) -> str:
        return first_phrase(self.text[0]) if self.text else ""


@dataclass
class Link:
    kind: str  # обрабатывает | зовёт | пишет | читает | указатель | как | внутри | связь | вручную
    src_file: str
    src_line: int
    src: str  # адрес сущности, где стоит ссылка
    service: str | None  # сервис цели (external:… у провайдера)
    key: str  # ключ цели в сервисе
    raw: str  # как написано


@dataclass
class Arrow:
    process: str
    stage: str  # якорь этапа
    id: str
    number: str  # «этап.стрелка», ставит модель
    sender: str
    receiver: str
    what: str
    how: str  # как написано
    kind: str
    inside: list[str]  # как написано: «orders#charge» или «[[orders: GET …]]»
    line: int
    file: str


# ─── разбор текста ─────────────────────────────────────────────────────────────────────────────────


def facts_settings(facts: dict) -> list[dict]:
    """Настройки сервиса из фактов — из любой части, что их вынимает (pydantic-settings, vite-env)."""
    out: list[dict] = []
    for part in facts.get("parts", []):
        sec = facts.get(part)
        if isinstance(sec, dict) and isinstance(sec.get("settings"), list):
            out += sec["settings"]
    return out


def first_phrase(text: str) -> str:
    """Первая фраза: до первой точки, за которой пробел или конец; точки в `коде` и в числах не режут."""
    masked = INLINE_CODE_RE.sub(lambda m: "x" * len(m.group(0)), text)
    for m in re.finditer(r"\.(\s|$)", masked):
        i = m.start()
        if (
            i > 0
            and masked[i - 1].isdigit()
            and i + 1 < len(masked)
            and masked[i + 1].isdigit()
        ):
            continue
        return text[: i + 1].strip()
    return text.strip()


CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js")
SKIP_CODE_DIRS = {"node_modules", "__pycache__", ".venv", "venv", "dist", "build", "coverage", ".git",
                  ".pytest_cache", ".ruff_cache", ".mypy_cache"}
_code_cache: dict[Path, list[tuple[Path, str]]] = {}


def code_files(root: Path) -> list[tuple[Path, str]]:
    """Файлы кода под root и их текст — каждый читается один раз за запуск; зависимости и сборки (node_modules,
    __pycache__, dist…) не обходятся: в них десятки тысяч чужих файлов, и проверка «Удаляется:» шла минутами."""
    key = root.resolve()
    if key not in _code_cache:
        out = []
        for d, dirs, names in os.walk(root):
            dirs[:] = sorted((x for x in dirs if x not in SKIP_CODE_DIRS), key=str.casefold)
            for n in sorted(names):
                if n.endswith(CODE_SUFFIXES):
                    p = Path(d) / n
                    out.append((p, p.read_text(encoding="utf-8", errors="replace")))
        _code_cache[key] = out
    return _code_cache[key]


def read_md(path: Path) -> list[str]:
    """Строки md: без BOM, переводы строк — \\n; блоки ``` вырезаны в пустые строки (номера строк сохраняются)."""
    raw = (
        path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    )
    out, fence = [], False
    for line in raw.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
            out.append("")
            continue
        out.append("" if fence else line)
    return out


def split_key(raw: str, services: set[str]) -> tuple[str | None, str]:
    """«сервис: ключ» → (сервис, ключ); свой ключ → (None, ключ). Провайдер: «external:x: ключ»."""
    raw = raw.strip()
    m = re.match(r"^(external:[a-z0-9-]+): (.+)$", raw)
    if m:
        return m.group(1), m.group(2)
    if ": " in raw:
        head, tail = raw.split(": ", 1)
        if head in services:
            return head, tail
    return None, raw


def table_rows(lines: list[str], start: int) -> tuple[list[dict], int]:
    """Таблица md с первой строки start: [{столбец: значение, '_line': n}], индекс строки после таблицы."""
    head = [c.strip() for c in lines[start].strip().strip("|").split("|")]
    rows, i = [], start + 2
    while i < len(lines) and lines[i].strip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        row = dict(zip(head, cells))
        row["_line"] = i + 1
        rows.append(row)
        i += 1
    return rows, i


# ─── модель ────────────────────────────────────────────────────────────────────────────────────────


class MapModel:
    def __init__(self, root: Path, repo: Path | None = None, world: bool = False):
        """root — корень карты; repo — корень репо для ссылок «Код:» (по умолчанию папка над root);
        world — мир «как будет»: «Код:» не обязателен и строки кода не проверяются."""
        self.root = root.resolve()
        self.repo = (repo or self.root.parent).resolve()
        self.world = world
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.stubs: list[str] = []  # заглушки выгрузки ???, {#?}, ?<этап>-<номер> — не ошибка, но и не готово
        self.settings = self._yaml("project/settings.yaml") or {}
        self.registry: dict = self._yaml("project/services.yaml") or {}
        self.board: dict = (self._yaml("project/board.yaml") or {}).get("nodes") or {}
        self.services = list(self.registry)
        self.external = self.settings.get("external") or {}
        self.facts: dict[str, dict] = {}
        self.entities: dict[
            str, Entity
        ] = {}  # ключ: «сервис::адрес», у процессов — «::процесс…»
        self.by_service: dict[str, list[Entity]] = {s: [] for s in self.services}
        self.links: list[Link] = []
        self.processes: dict[str, Entity] = {}
        self.arrows: dict[str, list[Arrow]] = {}
        self.slices: dict[tuple[str, str], Entity] = {}  # (сервис, процесс) → срез
        self.own: dict[str, Entity] = {}
        self.files: list[str] = []
        self._lines: dict[str, int | None] = {}  # путь кода → число строк (_line_count)
        self._load()

    # загрузка ------------------------------------------------------------------------------------

    def _yaml(self, rel: str):
        p = self.root / rel
        if not p.is_file():
            return None
        try:
            return yaml.safe_load(p.read_text(encoding="utf-8-sig"))
        except yaml.YAMLError as e:
            self.errors.append(f"{rel} — yaml не читается: {e}")
            return None

    def _load(self) -> None:
        asis = self.root / "ASIS"
        for svc in self.services:
            fp = asis / svc / ".facts.json"
            if fp.is_file():
                self.facts[svc] = json.loads(fp.read_text(encoding="utf-8"))
            elif self.registry[svc].get("facts"):
                self.errors.append(
                    f"ASIS/{svc}/.facts.json — нет файла фактов, а в реестре facts не пуст"
                )
            if "facts" not in self.registry[svc]:
                self.errors.append(f"project/services.yaml — у {svc} нет поля facts")
            folder = asis / svc
            for name in ("README",) + REFERENCE_FILES:
                p = folder / f"{name}.md"
                if p.is_file():
                    self._parse_service_file(svc, p, name)
                elif name != "README" or folder.is_dir():
                    self.errors.append(
                        f"ASIS/{svc}/{name}.md — файла нет (у сервиса все восемь файлов справочника и README)"
                    )
            if (folder / "own.md").is_file():
                self._parse_steps(svc, folder / "own.md", "own")
            for p in (
                sorted((folder / "processes").glob("*.md"), key=path_order)
                if (folder / "processes").is_dir()
                else []
            ):
                self._parse_steps(svc, p, p.stem)
        for p in (
            sorted((asis / "_processes").glob("*.md"), key=path_order)
            if (asis / "_processes").is_dir()
            else []
        ):
            self._parse_process(p)
        self._facts_entities()
        self._resolve()

    def rel(self, p: Path) -> str:
        return p.resolve().relative_to(self.root).as_posix()

    def add(self, e: Entity) -> Entity:
        k = f"{e.service or ''}::{e.addr}"
        if (
            k in self.entities
            and self.entities[k].file != e.file
            or k in self.entities
            and self.entities[k].line != e.line
        ):
            if e.kind not in ("раздел",):
                self.errors.append(
                    f"{e.file}:{e.line} — ключ «{e.addr}» уже есть: {self.entities[k].file}:{self.entities[k].line}"
                )
        self.entities[k] = e
        if e.service in self.by_service:
            self.by_service[e.service].append(e)
        return e

    def get(self, service: str | None, key: str) -> Entity | None:
        return self.entities.get(f"{service or ''}::{key}")

    # разбор файлов -------------------------------------------------------------------------------

    def _sections(self, rel: str, lines: list[str]) -> tuple[list[str], list[dict]]:
        """Первый абзац-зона (строки до первого заголовка ##) и разделы: заголовок, уровень, якорь, строки тела."""
        heads = [(i, HEAD_RE.match(line)) for i, line in enumerate(lines)]
        heads = [(i, m) for i, m in heads if m and len(m.group(1)) >= 2]
        intro = lines[: heads[0][0]] if heads else lines
        secs = []
        for n, (i, m) in enumerate(heads):
            end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
            anchor = m.group(3)
            if anchor == "?":
                self.stubs.append(f"{rel}:{i + 1} — якорь {{#?}}")
                anchor = f"stub-{i + 1}"
            if STUB in m.group(2):
                self.stubs.append(f"{rel}:{i + 1} — заголовок ???")
            secs.append(
                {
                    "level": len(m.group(1)),
                    "title": m.group(2).strip(),
                    "anchor": anchor,
                    "line": i + 1,
                    "body": lines[i + 1 : end],
                    "body_start": i + 2,
                }
            )
        for i, line in enumerate(lines):
            if (
                HEAD_RE.match(line)
                and line.startswith("# ")
                and not rel.startswith("ASIS/_processes/")
            ):
                self.errors.append(
                    f"{rel}:{i + 1} — заголовок «# …» пишется только у процесса"
                )
        return intro, secs

    def _body(self, e: Entity, body: list[str], start: int) -> None:
        """Поля, текст, таблица и ссылки на код раздела."""
        allowed = set(FIELDS.get(e.kind, ALL_FIELDS))
        cur: Field | None = None
        para: list[str] = []
        i = 0

        def flush():
            if para:
                e.text.append(" ".join(para).strip())
                para.clear()

        while i < len(body):
            line, n = body[i], start + i
            s = line.strip()
            if not s:
                flush()
                cur = None
                i += 1
                continue
            if (
                s.startswith("|")
                and i + 1 < len(body)
                and re.match(r"^\|?\s*:?-{3,}", body[i + 1].strip())
            ):
                flush()
                rows, j = table_rows(body, i)
                for r in rows:
                    r["_line"] = start + (r["_line"] - 1)
                e.table.extend(rows)
                i = j
                continue
            if STUB in s and not s.startswith("Код:"):
                self.stubs.append(f"{e.file}:{n} — ???")
            m = FIELD_RE.match(s)
            if m and (m.group(1) in allowed or e.kind in ("раздел",)):
                flush()
                cur = Field(m.group(1), (m.group(2) or "").strip(), [], n)
                e.fields[cur.name] = cur
                if cur.name == "Код":
                    self._code(e, cur.value, n)
                i += 1
                continue
            if m and m.group(1) not in allowed and e.kind not in ("раздел",):
                self.errors.append(
                    f"{e.file}:{n} — поле «{m.group(1)}:» не из списка вида «{e.kind}»"
                )
            if cur and s.startswith("- ") and not cur.value:
                cur.items.append(s[2:].strip())
                i += 1
                continue
            cur = None
            if s.startswith(
                "- "
            ):  # пункт списка в тексте — отдельной строкой, генератор соберёт список
                flush()
                e.text.append(s)
                i += 1
                continue
            para.append(s)
            i += 1
        flush()

    def _code(self, e: Entity, value: str, n: int) -> None:
        # « · » бывает и внутри живого источника — делим по обратным кавычкам, а не по разделителю
        for part in [p.strip() for p in CODE_PART_RE.findall(value) if p.strip()]:
            if part == STUB:
                self.stubs.append(f"{e.file}:{n} — Код: ???")
                continue
            if LIVE_REF_RE.fullmatch(part):
                e.live.append(part.strip("`"))
                continue
            m = CODE_REF_RE.fullmatch(part)
            if not m:
                self.errors.append(
                    f"{e.file}:{n} — «Код:» — не `путь:строка` и не живой источник с датой: {part}"
                )
                continue
            ref = CodeRef(m.group(1), int(m.group(2)), e.file, n)
            e.code.append(ref)
            if self.world:
                continue
            count = self._line_count(ref.path)
            if count is None:
                self.errors.append(f"{e.file}:{n} — нет файла {ref.path}")
            elif ref.line > count:
                self.errors.append(f"{e.file}:{n} — в {ref.path} нет строки {ref.line}")

    def _line_count(self, path: str) -> int | None:
        """Число строк файла кода (None — файла нет); каждый файл читается один раз за разбор."""
        if path not in self._lines:
            f = self.repo / path
            self._lines[path] = (
                f.read_bytes().count(b"\n") + 1 if f.is_file() else None
            )
        return self._lines[path]

    def _parse_service_file(self, svc: str, p: Path, name: str) -> None:
        rel = self.rel(p)
        self.files.append(rel)
        lines = read_md(p)
        intro, secs = self._sections(rel, lines)
        doc = self.add(Entity(f"{name}.md", "документ", svc, rel, 1, name))
        self._body(doc, intro, 1)
        if not secs and len(doc.text) == 1 and doc.text[0].endswith(" нет"):
            doc.extra["empty"] = True
            return
        group = None  # раздел-группа settings.md
        last_group, prev = -1, None  # порядок settings.md: место последней группы, последний раздел в группе
        parents: dict[int, Entity] = {}
        for s in secs:
            title, level = s["title"], s["level"]
            kind, key = self._classify(
                svc, name, title, s["anchor"], level, group, parents
            )
            if level == 2:
                group = title.split(":")[0] if name == "settings" else None
            if name == "settings":
                last_group, prev = self._settings_order(rel, s, last_group, prev)
            e = Entity(
                key,
                kind,
                svc,
                rel,
                s["line"],
                title,
                s["anchor"],
                level,
                parent=parents.get(level - 1).addr if parents.get(level - 1) else None,
            )
            if name == "README" and title.startswith("→ "):
                e.extra["to"] = title[2:].strip()
            if kind == "связь-метод":
                e.extra["to"] = parents[3].extra.get("to")
            self._body(e, s["body"], s["body_start"])
            if (
                s["anchor"]
                and not kind.startswith(
                    ("шаг", "проблема", "фоновая", "ограничитель", "другие")
                )
                and kind not in ("раздел",)
            ):
                self.errors.append(
                    f"{rel}:{s['line']} — якорь у заголовка-ключа не пишется: {{#{s['anchor']}}}"
                )
            self.add(e)
            parents[level] = e
            for lv in [k for k in parents if k > level]:
                del parents[lv]
            for f in REQUIRED.get(kind, []):
                if f not in e.fields:
                    if f == "Код" and kind in ("проблема",) and "Смотри" in e.fields:
                        continue
                    if f == "Код" and self.world:
                        continue
                    self.errors.append(
                        f"{rel}:{s['line']} — у «{title}» нет обязательного поля «{f}:»"
                    )
        self._links_in(svc, rel, lines)

    def _settings_order(self, rel: str, s: dict, last_group: int, prev: tuple[str, str] | None):
        """Порядок settings.md: группы — как в SETTINGS_GROUPS, разделы группы — по алфавиту без учёта регистра
        и ведущего «_». Возвращает новое (место последней группы, последний раздел)."""
        title = s["title"]
        if s["level"] == 2:
            if (g := title.split(":")[0]) in SETTINGS_GROUPS:
                at = SETTINGS_GROUPS.index(g)
                if at < last_group:
                    self.errors.append(
                        f"{rel}:{s['line']} — группа «{title}» не на своём месте: порядок — "
                        f"{' → '.join(SETTINGS_GROUPS)}"
                    )
                last_group = max(last_group, at)
            return last_group, None
        if s["level"] != 3 or STUB in title:
            return last_group, prev
        k = title.lstrip("_").casefold()
        if prev and k < prev[0]:
            self.errors.append(
                f"{rel}:{s['line']} — «{title}» не по алфавиту: стоит после «{prev[1]}»; разделы группы — "
                f"по алфавиту без учёта регистра и ведущего «_»"
            )
        return last_group, (k, title)

    def _classify(
        self, svc, name, title, anchor, level, group, parents
    ) -> tuple[str, str]:
        """Вид раздела и его ключ."""
        if name == "README":
            if level == 2:
                return "раздел", title
            if level == 3 and title.startswith("→ "):
                return "связь", f"{svc} → {title[2:].strip()}"
            if level == 4 and parents.get(3) is not None:
                return "связь-метод", f"{parents[3].addr}: {title}"
            return "раздел", title
        if name == "methods":
            return "метод", title
        if name == "exports":
            return "функция", title
        if name == "pages":
            return (
                ("правила прокси", title)
                if title == "Куда уходят запросы"
                else ("страница", title)
            )
        if name == "commands":
            return "команда", title
        if name == "tests":
            return "набор тестов", title
        if name == "problems":
            return "проблема", anchor or title
        if name == "storage":
            for pref, kind in STORE_PREFIX.items():
                if title.startswith(pref):
                    return kind, title[len(pref) :]
            if level == 3:
                return "колонка", title
            return "таблица", title
        if name == "settings":
            if level == 2:
                return "раздел", title
            g = group or ""
            if anchor and anchor.startswith("bg-"):
                return "фоновая работа", anchor
            if anchor and anchor.startswith("lim-"):
                return "ограничитель", anchor
            if g == "Настройки":
                return "настройка", title
            if g == "Другие настройки":
                return "другая настройка", title
            if g == "Зашито в коде":
                return "постоянная", title
            return "раздел", title
        return "раздел", title

    def _parse_steps(self, svc: str, p: Path, proc: str) -> None:
        rel = self.rel(p)
        self.files.append(rel)
        lines = read_md(p)
        intro, secs = self._sections(rel, lines)
        doc = Entity(
            f"{svc}/{proc}",
            "срез" if proc != "own" else "своя работа",
            svc,
            rel,
            1,
            proc,
        )
        self._body(doc, intro, 1)
        if not doc.text:
            self.errors.append(
                f"{rel}:1 — нет первого абзаца: что сервис делает {'в процессе' if proc != 'own' else 'сам'}"
            )
        doc.extra["steps"] = []
        self.add(doc)
        if proc == "own":
            self.own[svc] = doc
        else:
            self.slices[(svc, proc)] = doc
        for s in secs:
            if not s["anchor"]:
                self.errors.append(f"{rel}:{s['line']} — у шага нет якоря {{#…}}")
                continue
            e = Entity(
                f"{svc}/{proc}#{s['anchor']}",
                "шаг",
                svc,
                rel,
                s["line"],
                s["title"],
                s["anchor"],
                2,
                parent=doc.addr,
            )
            e.extra.update(process=proc, short=f"{svc}#{s['anchor']}")
            self._body(e, s["body"], s["body_start"])
            if not e.text:
                self.errors.append(f"{rel}:{s['line']} — у шага нет текста")
            for f in REQUIRED["шаг"]:
                if f not in e.fields and not (f == "Код" and self.world):
                    self.errors.append(
                        f"{rel}:{s['line']} — у шага «{s['title']}» нет «{f}:»"
                    )
            self.add(e)
            doc.extra["steps"].append(e.addr)
        self._links_in(svc, rel, lines)

    def _parse_process(self, p: Path) -> None:
        rel = self.rel(p)
        self.files.append(rel)
        key = p.stem
        lines = read_md(p)
        intro, secs = self._sections(rel, lines)
        title = next(
            (
                m.group(2)
                for m in (HEAD_RE.match(x) for x in lines)
                if m and len(m.group(1)) == 1
            ),
            None,
        )
        if not title:
            self.errors.append(f"{rel}:1 — нет заголовка «# <название процесса>»")
        e = Entity(key, "процесс", None, rel, 1, title or key)
        self._body(e, [x for x in intro if not x.startswith("# ")], 1)
        for f in REQUIRED["процесс"]:
            if f not in e.fields:
                self.errors.append(f"{rel} — у процесса нет поля «{f}:»")
        parts = [
            x.strip()
            for x in e.fields.get("Участники", Field("", "", [], 0)).value.split(" · ")
            if x.strip()
        ]
        e.extra["participants"] = parts
        for part in parts:
            if not (
                part in self.registry
                or part in ("human", "schedule", "redis")
                or part.startswith("folder:")
                or (part.startswith("external:") and part[9:] in self.external)
            ):
                self.errors.append(
                    f"{rel} — участник «{part}» не из реестра и не из настроек проекта"
                )
        ranks = [lane_rank(p) for p in parts]
        if ranks != sorted(ranks):
            self.errors.append(
                f"{rel} — «Участники:» не в порядке дорожек: human, schedule, сервисы, external:…, redis, folder:… — "
                f"сейчас {' · '.join(parts)}"
            )
        groups = self.settings.get("process_groups") or []
        g = e.fields["Группа"].value if "Группа" in e.fields else ""
        if groups and g not in groups:
            self.warnings.append(f"{rel} — группа процесса «{g}» не из process_groups настроек проекта: в меню — «Прочие»")
        self.processes[key] = e
        self.add(e)
        arrows, ids = [], set()
        stage_n = 0
        for s in secs:
            if s["title"] == "Связанные процессы":
                se = Entity(
                    f"{key}#related", "раздел", None, rel, s["line"], s["title"]
                )
                self._body(se, s["body"], s["body_start"])
                e.extra["related"] = se.text
                continue
            if not s["anchor"]:
                self.errors.append(f"{rel}:{s['line']} — у этапа нет якоря {{#…}}")
                continue
            stage_n += 1
            st = Entity(
                f"{key}#{s['anchor']}",
                "этап",
                None,
                rel,
                s["line"],
                s["title"],
                s["anchor"],
                2,
                parent=key,
            )
            self._body(st, s["body"], s["body_start"])
            st.extra["number"] = stage_n
            if s["anchor"] in ids:
                self.errors.append(
                    f"{rel}:{s['line']} — якорь этапа «{s['anchor']}» уже есть"
                )
            ids.add(s["anchor"])
            self.add(st)
            for n, r in enumerate(st.table, 1):
                a = self._arrow(key, st, r, f"{stage_n}.{n}", rel)
                if a is None:
                    continue
                if a.id in ids:
                    self.errors.append(
                        f"{rel}:{a.line} — id «{a.id}» уже есть в процессе"
                    )
                ids.add(a.id)
                arrows.append(a)
        self.arrows[key] = arrows
        for i, line in enumerate(lines, 1):
            for raw in LINK_RE.findall(INLINE_CODE_RE.sub("", line)):
                svc, k = split_key(raw, set(self.services))
                if svc is None:
                    self.errors.append(
                        f"{rel}:{i} — в файле процесса ключ без имени сервиса: [[{raw}]]"
                    )

    def _arrow(
        self, proc: str, stage: Entity, r: dict, number: str, rel: str
    ) -> Arrow | None:
        who = r.get("кто → кому", "")
        if "→" not in who:
            self.errors.append(f"{rel}:{r['_line']} — в стрелке нет «кто → кому»")
            return None
        sender, receiver = [x.strip() for x in who.split("→", 1)]
        a = Arrow(
            proc,
            stage.anchor,
            r.get("id", "").strip(),
            number,
            sender,
            receiver,
            r.get("что", ""),
            r.get("как", ""),
            r.get("вид", "").strip(),
            [x.strip() for x in r.get("внутри", "").split(" · ") if x.strip()],
            r["_line"],
            rel,
        )
        if a.id.startswith("?"):
            self.stubs.append(f"{rel}:{a.line} — id стрелки {a.id}")
        for col, val in (("что", a.what), ("как", a.how), ("внутри", " · ".join(a.inside))):
            if STUB in val:
                self.stubs.append(f"{rel}:{a.line} — «{col}» ???")
        a.inside = [x for x in a.inside if x != STUB]
        stub_inside = STUB in r.get("внутри", "")
        parts = self.processes[proc].extra["participants"]
        for side in (sender, receiver):
            if side not in parts:
                self.errors.append(f"{rel}:{a.line} — «{side}» нет в «Участники:»")
        if a.kind not in ARROW_KINDS:
            self.errors.append(f"{rel}:{a.line} — вид стрелки «{a.kind}» не из списка")
        if sender == receiver and a.kind not in LOOP_KINDS:
            self.errors.append(
                f"{rel}:{a.line} — петля «{sender} → {receiver}» бывает только видов: {', '.join(LOOP_KINDS)}"
            )
        if not a.inside and not stub_inside:
            self.errors.append(
                f"{rel}:{a.line} — у стрелки «{a.id}» пустой столбец «внутри»"
            )
        return a

    def _links_in(self, svc: str, rel: str, lines: list[str]) -> None:
        """Ссылки [[…]] файла сервиса: с видом из «Справочник:», остальные — указатели."""
        owner = None
        ents = sorted(
            [e for e in self.by_service.get(svc, []) if e.file == rel],
            key=lambda x: x.line,
        )
        for i, line in enumerate(lines, 1):
            for e in ents:
                if e.line <= i:
                    owner = e
            src = owner.addr if owner else rel
            clean = INLINE_CODE_RE.sub("", line)
            if line.startswith("Справочник:"):
                for part in [
                    x.strip()
                    for x in line[len("Справочник:") :].split(" · ")
                    if x.strip()
                ]:
                    m = re.fullmatch(r"(\S+) \[\[([^\]]+)\]\]", part)
                    if not m or m.group(1) not in LINK_KINDS:
                        self.errors.append(
                            f"{rel}:{i} — в «Справочник:» ссылка без вида или вид не из списка: {part}"
                        )
                        continue
                    s2, k = split_key(m.group(2), set(self.services))
                    self.links.append(
                        Link(m.group(1), rel, i, src, s2 or svc, k, m.group(2))
                    )
                continue
            for raw in LINK_RE.findall(clean):
                s2, k = split_key(raw, set(self.services))
                self.links.append(Link("указатель", rel, i, src, s2 or svc, k, raw))
            for target, anchor in MDLINK_RE.findall(clean):
                t = (self.root / rel).parent / target
                if not t.is_file():
                    self.errors.append(
                        f"{rel}:{i} — ссылка на несуществующий файл {target}"
                    )
                elif anchor and f"{{#{anchor}}}" not in t.read_text(encoding="utf-8"):
                    self.errors.append(f"{rel}:{i} — в {target} нет якоря #{anchor}")

    # факты и связи -------------------------------------------------------------------------------

    def _facts_entities(self) -> None:
        """Колонки и настройки, о которых есть только факты, — тоже ключи."""
        for svc, f in self.facts.items():
            for t in (f.get("postgres") or {}).get("tables", []):
                for c in t.get("columns", []):
                    k = f"{t['name']}.{c['name']}"
                    if not self.get(svc, k):
                        self.add(
                            Entity(
                                k,
                                "колонка",
                                svc,
                                f"ASIS/{svc}/.facts.json",
                                0,
                                k,
                                extra={"facts_only": True},
                            )
                        )
            for s in facts_settings(f):
                if not self.get(svc, s["name"]):
                    self.add(
                        Entity(
                            s["name"],
                            "настройка",
                            svc,
                            f"ASIS/{svc}/.facts.json",
                            0,
                            s["name"],
                            extra={"facts_only": True},
                        )
                    )

    def _resolve(self) -> None:
        """Ключи ссылок и стрелок есть в карте; производные списки — кто вызывает, кто обрабатывает, кто пишет и читает."""
        for ln in self.links:
            if ln.service and ln.service.startswith("external:"):
                if not self.connection_method(None, ln.service, ln.key, near=ln):
                    self.errors.append(
                        f"{ln.src_file}:{ln.src_line} — у провайдера нет связи с «{ln.key}» в «Связях»"
                    )
                continue
            if not self.get(ln.service, ln.key):
                hint = self._similar(ln.service, ln.key)
                self.errors.append(
                    f"{ln.src_file}:{ln.src_line} — ключ [[{ln.raw}]] у {ln.service} не найден{hint}"
                )
        for proc, arrows in self.arrows.items():
            for a in arrows:
                for raw in LINK_RE.findall(a.how):
                    svc, k = split_key(raw, set(self.services))
                    if svc and not svc.startswith("external:") and not self.get(svc, k):
                        self.errors.append(
                            f"{a.file}:{a.line} — «как»: ключ [[{raw}]] не найден"
                        )
                    self.links.append(
                        Link("как", a.file, a.line, f"{proc}#{a.id}", svc, k, raw)
                    )
                for ins in a.inside:
                    m = LINK_RE.fullmatch(ins)
                    if m:
                        svc, k = split_key(m.group(1), set(self.services))
                        if not self.get(svc, k):
                            self.errors.append(
                                f"{a.file}:{a.line} — «внутри»: ключ [[{m.group(1)}]] не найден"
                            )
                        continue
                    if "#" not in ins:
                        self.errors.append(
                            f"{a.file}:{a.line} — «внутри»: «{ins}» — не шаг и не ключ"
                        )
                        continue
                    svc, anc = ins.split("#", 1)
                    if svc not in (a.sender, a.receiver):
                        self.errors.append(
                            f"{a.file}:{a.line} — «внутри»: шаг {ins} не отправителя и не получателя"
                        )
                    if not self.get(svc, f"{svc}/{proc}#{anc}"):
                        self.errors.append(
                            f"{a.file}:{a.line} — «внутри»: нет шага {ins} в срезе {svc}/{proc}"
                        )

    def _similar(self, svc: str | None, key: str) -> str:
        others = [s for s in self.services if s != svc and self.get(s, key)]
        if others:
            return f"; такой ключ есть у {', '.join(others)} — допиши имя сервиса"
        skip = (
            "связь",
            "связь-метод",
            "документ",
            "раздел",
            "срез",
            "своя работа",
            "шаг",
        )
        near = [
            e.addr
            for e in self.by_service.get(svc, [])
            if e.kind not in skip
            and (key.lower() in e.addr.lower() or e.addr.lower() in key.lower())
        ]
        return f"; похожие: {', '.join(near[:5])}" if near else ""

    # запросы к модели ----------------------------------------------------------------------------

    def connection_method(
        self, caller: str | None, to: str, key: str, near: Link | None = None
    ) -> Entity | None:
        """Подраздел «Связей» `#### <key>` под `### → <to>` у вызывающего (caller или сервис ссылки near)."""
        caller = caller or (
            near.service if near and not near.service.startswith("external:") else None
        )
        if near:
            caller = self._service_of_file(near.src_file)
        return self.get(caller, f"{caller} → {to}: {key}")

    def _service_of_file(self, rel: str) -> str | None:
        parts = rel.split("/")
        return (
            parts[1]
            if len(parts) > 2 and parts[0] == "ASIS" and parts[1] in self.registry
            else None
        )

    def links_to(
        self, service: str, key: str, kinds: tuple[str, ...] | None = None
    ) -> list[Link]:
        return [
            ln
            for ln in self.links
            if ln.service == service
            and ln.key == key
            and (kinds is None or ln.kind in kinds)
        ]

    def steps_handling(self, service: str, key: str) -> list[Entity]:
        """Шаги, которые обрабатывают точку входа (как она работает)."""
        out = []
        for ln in self.links_to(service, key, ("обрабатывает",)):
            e = self.get(service, ln.src)
            if e and e.kind == "шаг" and e not in out:
                out.append(e)
        return out

    def callers(self, service: str, key: str) -> list[dict]:
        """Кто вызывает точку входа: «Связи» и `зовёт` других, `Вручную:`, стрелки от человека и провайдера."""
        out = []
        for ln in self.links_to(service, key, ("зовёт",)):
            src_svc = self._service_of_file(ln.src_file)
            e = self.get(src_svc, ln.src)
            out.append({"who": src_svc, "via": "шаг", "entity": e, "link": ln})
        m = self.get(service, key)
        if m and "Вручную" in m.fields:
            out.append(
                {
                    "who": "вручную",
                    "via": "вручную",
                    "text": m.fields["Вручную"].value,
                    "entity": m,
                }
            )
        for proc, arrows in self.arrows.items():
            for a in arrows:
                if a.receiver == service and (
                    a.sender in ("human", "schedule") or a.sender.startswith("external:")
                ):
                    if any(
                        split_key(r, set(self.services)) == (service, key)
                        for r in LINK_RE.findall(a.how)
                    ):
                        out.append({"who": a.sender, "via": "стрелка", "arrow": a})
        return out

    def touches(self, service: str, key: str) -> list[Link]:
        """Что трогает точка входа: ссылки с видом её шагов или её собственной строки «Справочник:»."""
        steps = self.steps_handling(service, key)
        srcs = {s.addr for s in steps} or {key}
        return [
            ln
            for ln in self.links
            if ln.kind in ("зовёт", "пишет", "читает")
            and ln.src in srcs
            and self._service_of_file(ln.src_file) == service
        ]

    def writers_readers(self, service: str, key: str) -> dict[str, list[Link]]:
        """Кто пишет и кто читает хранилище; у колонки — и ссылки на её таблицу целиком."""
        res = {"пишет": [], "читает": [], "через таблицу": []}
        for ln in self.links_to(service, key, ("пишет", "читает")):
            res[ln.kind].append(ln)
        if "." in key:
            table = key.split(".", 1)[0]
            res["через таблицу"] = self.links_to(service, table, ("пишет", "читает"))
        return res

    def arrows_to_step(self, step: Entity) -> list[Arrow]:
        proc = step.extra.get("process")
        short = step.extra.get("short")
        return [a for a in self.arrows.get(proc, []) if short in a.inside]

    def connections(self, service: str) -> list[Entity]:
        return [e for e in self.by_service.get(service, []) if e.kind == "связь"]

    def incoming(self, service: str) -> list[Entity]:
        """Связи других сервисов к этому."""
        return [
            e
            for s in self.services
            if s != service
            for e in self.connections(s)
            if e.extra.get("to") == service
        ]

    def column_facts(self, service: str, key: str) -> tuple[dict, dict] | None:
        """Таблица и колонка из фактов postgres по ключу «таблица.колонка»."""
        for t in (self.facts.get(service, {}).get("postgres") or {}).get("tables", []):
            for c in t.get("columns", []):
                if f"{t['name']}.{c['name']}" == key:
                    return t, c
        return None

    def what(self, e: Entity) -> str:
        """«Что» ключа — то, что стоит рядом с ним в списках: поиск в шапке страниц и find.py --list."""
        f = e.fields
        for name in ("Что делает", "Что на странице"):
            if name in f:
                return f[name].value
        if e.kind == "фоновая работа":
            return f["Когда"].value if "Когда" in f else ""
        if e.kind in ("связь", "связь-метод"):
            return f["Ожидание"].value if "Ожидание" in f else ""
        if e.kind in ("проблема", "ограничитель", "этап"):
            return e.title
        if e.kind == "колонка":
            if "Означает" in f:
                return f["Означает"].value
            if e.text:
                return e.first_phrase()
            tc = self.column_facts(e.service or "", e.addr)
            return (tc[1].get("db_comment") or tc[1].get("comment") or "") if tc else ""
        return e.first_phrase()

    def entries(self, service: str, kind: str) -> list[Entity]:
        return [
            e
            for e in self.by_service.get(service, [])
            if e.kind == kind and not e.extra.get("facts_only")
        ]


# ─── «как будет»: правки, мир «как будет», обложка, задачи, блоки ──────────────────────────────────

BLOCK_OPEN_RE = re.compile(
    r"^::: (новое|меняется|уходит) (c-[a-z0-9-]+) · ([^·]+?)(?: · вместо (.+?))?\s*$"
)
NEW_FILE_RE = re.compile(r"^Правка: (c-[a-z0-9-]+) · (.+?)\s*$")
CHANGE_KINDS = ("новое", "меняется", "уходит")
COVER_FIELDS = ("Ветка", "PR", "Требования", "Размер", "Описание утверждено")

# Решения изменения живут в его задаче бэклога (промт и папка, поле обложки «Требования:»): пункт списка или абзац,
# на который правки ссылаются якорем {#d-…}. Без пометки — согласовано; (не согласовано) — придумала сессия, решающий не
# ответил; (открыто) — вопрос; (по рекомендации) — решила сессия, не видно человеку. Пометка → статус: место в statuses
# настроек. Пометка в кавычках «(открыто)», в обратных кавычках и жирная **(открыто)** — не пометка, а слово о ней.
# ✅, (решено) и (предложено) — прежние написания: читаются, чтобы забытая по привычке пометка не стала согласием.
REQ_MARK_RE = re.compile(
    r"(?<![«*`])(✅|\((?:решено(?: по рекомендации)?|по рекомендации|не согласовано|предложено|открыто)\))"
)
REQ_MARK_RANK = {"✅": 0, "решено": 0, "решено по рекомендации": 1, "по рекомендации": 1, "не согласовано": 2,
                 "предложено": 2, "открыто": 3}
REQ_ANCHOR_RE = re.compile(r"\s*\{#(d-[a-z0-9-]+)\}")
REQ_LIST_RE = re.compile(r"^(\s*)(?:[-*+]|\d+\.)\s+")


def requirement_files(root: Path, spec: str) -> list[Path]:
    """Файлы набора требований по полю обложки «Требования:»: ссылка md (от TOBE/) или путь от корня репо;
    README.md или папка — все md папки с подпапками, другой md — он один."""
    out: list[Path] = []
    for t in re.findall(r"\]\(([^)#\s]+)", spec) or re.findall(r"`([^`]+)`", spec) or spec.split():
        p = ((root / "TOBE" / t) if t.startswith(".") else (root.parent / t)).resolve()
        if p.name == "README.md":
            p = p.parent
        out += sorted(p.rglob("*.md"), key=path_order) if p.is_dir() else [p] if p.is_file() else []
    return list(dict.fromkeys(out))


def requirement_items(lines: list[str]) -> list[tuple[int, int, int]]:
    """Пункты md требований: (начало, конец своих строк, конец с вложенными пунктами) — пункт списка с
    продолжением и вложенным или абзац. Вложенный пункт — ещё и отдельный пункт: у него своя пометка."""
    items, i, n = [], 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or line.startswith("#") or line.lstrip().startswith("|"):
            i += 1
            continue
        m = REQ_LIST_RE.match(line)
        indent = len(m.group(1)) if m else 0
        j, own = i + 1, None
        while j < n:
            x = lines[j]
            if x.startswith("#"):
                break
            if not x.strip():
                k = next((k for k in range(j, n) if lines[k].strip()), n)
                if not m or k == n or len(lines[k]) - len(lines[k].lstrip()) <= indent:
                    break
            elif REQ_LIST_RE.match(x):
                if not m or len(x) - len(x.lstrip()) <= indent:
                    break
                own = own or j
            j += 1
        items.append((i, own or j, j))
        i = own or j
    return items


def read_requirements(files: list[Path], repo: Path, statuses: list[str]) -> tuple[dict[str, dict], list[dict], list[str]]:
    """Решения с якорями, все пункты со слабой пометкой (вопросы к решающему) и ошибки набора требований.

    Статус пункта — самая слабая из его пометок (в своих строках, без вложенных пунктов). Решение — запись того же
    вида, что раньше давала обложка: title, line, text, «Статус», «Когда» (дата из текста) и file — путь от корня репо.
    """
    def status_of(mark: str) -> str:
        rank = REQ_MARK_RANK[mark.strip("()")]
        return statuses[rank] if rank < len(statuses) else mark.strip("()")

    decisions: dict[str, dict] = {}
    weak: list[dict] = []
    errors: list[str] = []
    for p in files:
        lines = read_md(p)
        rel = p.relative_to(repo).as_posix() if p.is_relative_to(repo) else p.as_posix()
        for start, own, end in requirement_items(lines):
            own_text = " ".join(x.strip() for x in lines[start:own])
            # пометок в пункте бывает несколько («(решено) … (решено) …») — статус по слабейшей
            marks = [status_of(x) for x in REQ_MARK_RE.findall(own_text)]
            anchors = REQ_ANCHOR_RE.findall(own_text)
            status = max(marks, key=lambda s: statuses.index(s) if s in statuses else len(statuses)) if marks else None
            if status is None and anchors:  # без пометки — согласовано; его слова в пункте требует проверка 25.5
                status = statuses[0]
            plain = REQ_ANCHOR_RE.sub("", REQ_LIST_RE.sub("", own_text, count=1)).strip()
            bold = re.search(r"\*\*(.+?)\*\*", plain)
            title = bold.group(1) if bold else REQ_MARK_RE.sub("", plain).strip()[:90]
            if status in statuses[2:]:
                weak.append({"file": rel, "line": start + 1, "status": status, "anchor": anchors[0] if anchors else None,
                             "title": title})
            for a in anchors:
                if a in decisions:
                    errors.append(f"{rel}:{start + 1} — якорь {a} уже есть: {decisions[a]['file']}:{decisions[a]['line']}")
                body = [REQ_ANCHOR_RE.sub("", REQ_LIST_RE.sub("", lines[start], count=1))]
                body += textwrap.dedent("\n".join(lines[start + 1:end])).split("\n") if end > start + 1 else []
                date = re.search(r"\d{4}-\d{2}-\d{2}", own_text)
                decisions[a] = {"title": title, "line": start + 1, "file": rel, "text": [x for x in body if x.strip()],
                                "Статус": status or "", **({"Когда": date.group(0)} if date else {})}
    return decisions, weak, errors


def cover_decisions(root: Path, statuses: list[str]) -> dict[str, dict]:
    """Решения изменения без модели «как будет»: поле «Требования:» обложки → набор требований → решения."""
    cover = root / "TOBE" / "README.md"
    spec = next((x.split(":", 1)[1] for x in (read_md(cover) if cover.is_file() else []) if x.startswith("Требования:")), "")
    return read_requirements(requirement_files(root, spec), root.parent, statuses)[0]
TASK_FIELDS = ("Правки", "Тесты", "После", "Удаляется", "Сделано")
TEST_FIELDS = ("Набор", "Вид", "Тест", "Проверяет")
WORK_FIELDS = ("Где", "Задачи", "После", "Готово, когда", "Сделано")


@dataclass
class Block:
    """Правка — блок ::: в копии «как будет»."""

    kind: str  # новое | меняется | уходит
    number: str  # c-…
    status: str
    instead: str | None
    file: str  # копия от корня карты: TOBE/orders/methods.md
    line: int  # строка «:::» открытия
    end: int = 0  # строка «:::» закрытия
    body: list[str] = field(default_factory=list)  # строки внутри, без «Почему:»
    why: str = ""
    what: str = ""  # раздел | этап | поля | текст | строки
    head: tuple | None = None  # (уровень, заголовок, якорь) — у раздела и этапа
    fields: list[str] = field(default_factory=list)  # имена полей — у правки полей
    rows: list[str] = field(default_factory=list)  # id строк таблицы — у правки строк
    owner: list[tuple] = field(default_factory=list)  # заголовки снаружи блока над ним: [(уровень, заголовок, якорь)]

    @property
    def asis_file(self) -> str:
        return "ASIS/" + self.file.split("/", 1)[1]


def parse_blocks(rel: str, lines: list[str]) -> tuple[list[Block], list[str]]:
    """Правки файла «как будет»: вид, номер, статус, что обёрнуто, «Почему:»; ошибки формата."""
    blocks: list[Block] = []
    errors: list[str] = []
    heads: list[tuple] = []
    cur: Block | None = None
    for i, line in enumerate(lines, 1):
        if line.startswith(":::"):
            m = BLOCK_OPEN_RE.match(line)
            if line.strip() == ":::":
                if not cur:
                    errors.append(f"{rel}:{i} — «:::» закрывает блок, которого нет")
                    continue
                cur.end = i
                _classify_block(cur, rel)
                if not cur.why:
                    errors.append(
                        f"{rel}:{cur.line} — у правки {cur.number} нет «Почему:»"
                    )
                blocks.append(cur)
                cur = None
                continue
            if not m:
                errors.append(
                    f"{rel}:{i} — строка правки не по форме «::: <вид> c-… · <статус>»: {line}"
                )
                continue
            if cur:
                errors.append(
                    f"{rel}:{i} — блок внутри блока {cur.number}: блоки не вкладываются"
                )
                continue
            cur = Block(
                m.group(1), m.group(2), m.group(3).strip(), m.group(4), rel, i,
                owner=list(heads),
            )
            continue
        if cur:
            if line.startswith("Почему:"):
                cur.why = line[len("Почему:") :].strip()
            else:
                cur.body.append(line)
            continue
        hm = HEAD_RE.match(line)
        if hm:
            lv = len(hm.group(1))
            heads = [h for h in heads if h[0] < lv] + [(lv, hm.group(2).strip(), hm.group(3))]
    if cur:
        errors.append(f"{rel}:{cur.line} — блок {cur.number} не закрыт «:::»")
    return blocks, errors


def _classify_block(b: Block, rel: str) -> None:
    first = next((x for x in b.body if x.strip()), "")
    hm = HEAD_RE.match(first)
    if hm:
        lv = len(hm.group(1))
        b.head = (lv, hm.group(2).strip(), hm.group(3))
        b.what = "этап" if rel.startswith("TOBE/_processes/") and lv == 2 else "раздел"
        return
    if first.lstrip().startswith("|"):
        b.what = "строки"
        b.rows = [
            c.strip("| ").split("|")[0].strip()
            for c in b.body
            if c.lstrip().startswith("|") and not re.match(r"^\|?\s*:?-{3,}", c.strip())
        ]
        return
    b.fields = [m.group(1) for x in b.body if (m := FIELD_RE.match(x.strip()))]
    b.what = "поля" if b.fields else "текст"  # текст без полей — сводка файла или абзацы раздела


def world_lines(lines: list[str]) -> tuple[list[str], list[int]]:
    """Копия → файл мира «как будет»: «новое» и «меняется» раскрыты, «уходит» убрано, «Почему:» и «:::» убраны,
    первая строка «Правка: …» нового файла — тоже. Второй список — номер строки копии для каждой строки мира."""
    out, src = [], []
    kind = None
    head = bool(lines) and lines[0].startswith("Правка: ")  # новый файл: «Правка:», «Почему:», пустая строка
    for i, line in enumerate(lines, 1):
        if head:
            if i == 1 or line.startswith("Почему:") or not line.strip():
                continue
            head = False
        if line.startswith(":::"):
            m = BLOCK_OPEN_RE.match(line)
            if m:
                kind = m.group(1)
            elif line.strip() == ":::":
                kind = None
            continue
        if kind == "уходит":
            continue
        if kind and line.startswith("Почему:"):
            continue
        out.append(line)
        src.append(i)
    return out, src


def sections_in(lines: list[str], start: int, end: int) -> list[tuple[int, int, str, str | None]]:
    """Разделы в строках копии [start, end) (номера с 0): (строка заголовка, конец, заголовок, якорь). Конец —
    следующий заголовок любого уровня, «Почему:», «:::» или end: «Код:» раздела стоит до подразделов."""
    out = []
    i = start
    while i < end:
        hm = HEAD_RE.match(lines[i])
        if not hm:
            i += 1
            continue
        j = i + 1
        while j < end and not HEAD_RE.match(lines[j]) and not lines[j].startswith(("Почему:", ":::")):
            j += 1
        out.append((i, j, hm.group(2).strip(), hm.group(3)))
        i = j
    return out


def block_span(b: Block, lines: list[str]) -> tuple[int, int]:
    """Строки правки в копии (номера с 0, конец не входит): тело блока или весь новый файл."""
    return (b.line, b.end - 1) if b.what != "файл" else (0, len(lines))


def code_gaps(chg: "ChangeModel", numbers: set[str] | None = None) -> list[str]:
    """Разделы правок «новое» и «меняется» целиком и разделы новых файлов без «Код:» — их ставит блок, который
    написал код (map.py code). numbers — только эти правки. Без «Код:» по правилам: файлы процессов, tests.md,
    фоновая работа («Описание:» ведёт на шаг), раздел-группа (пусто до подраздела), настройка без «Значение:»
    в settings.md (её место — в фактах). Ограничитель ({#lim-…}) «Код:» требует, как в «как есть», хотя в нём
    «Сколько:», а не «Значение:»."""
    out = []
    for b in chg.blocks:
        if b.kind == "уходит" or b.what not in ("раздел", "файл") or (numbers is not None and b.number not in numbers):
            continue
        if b.file.startswith("TOBE/_processes/") or b.file.endswith("/tests.md"):
            continue
        lines = read_md(chg.root / b.file)
        for i, j, title, anchor in sections_in(lines, *block_span(b, lines)):
            body = [x for x in lines[i + 1:j] if x.strip()]
            if not body or any(x.startswith(("Код:", "Описание:")) for x in body):
                continue
            limiter = (anchor or "").startswith("lim-")
            if b.file.endswith("/settings.md") and not limiter and not any(x.startswith("Значение:") for x in body):
                continue
            out.append(f"{b.file}:{i + 1} — {b.number}: «{title}» без «Код:»")
    return out


def _is_slice(rel: str) -> bool:
    """Срез процесса или своя работа сервиса: <сервис>/processes/<процесс>.md, <сервис>/own.md."""
    parts = rel.split("/")
    return (len(parts) == 3 and parts[1] == "processes") or (len(parts) == 2 and parts[1] == "own.md")


def _drop_gone_facts(world_root: Path, blocks: list[Block]) -> None:
    """Факты мира «как будет» без методов, таблиц и настроек, чьи разделы правки «уходит» убирают целиком: код их
    удалит («Удаляется:» задачи, проверка 25.8), а до блока факты ещё сняты с кода «как есть»."""
    gone: dict[str, dict[str, set[str]]] = {}
    heads = {"methods.md": ("метод", 2), "storage.md": ("таблица", 2), "settings.md": ("настройка", 3)}
    for b in blocks:
        parts = b.file.split("/")  # TOBE/<сервис>/<файл>.md
        if b.kind != "уходит" or len(parts) != 3 or parts[2] not in heads:
            continue
        kind, level = heads[parts[2]]
        for line in b.body:
            m = HEAD_RE.match(line)
            if m and len(m.group(1)) == level:
                gone.setdefault(parts[1], {}).setdefault(kind, set()).add(m.group(2).strip())
    for svc, keys in gone.items():
        fp = world_root / "ASIS" / svc / ".facts.json"
        if not fp.is_file():
            continue
        f = json.loads(fp.read_text(encoding="utf-8"))
        api = f.get("fastapi-openapi") or {}
        if "methods" in api:
            api["methods"] = [x for x in api["methods"] if f"{x['method']} {x['path']}" not in keys.get("метод", set())]
        pg = f.get("postgres") or {}
        if "tables" in pg:
            pg["tables"] = [t for t in pg["tables"] if t["name"] not in keys.get("таблица", set())]
        for part in f.get("parts", []):
            sec = f.get(part)
            if isinstance(sec, dict) and isinstance(sec.get("settings"), list):
                sec["settings"] = [s for s in sec["settings"] if s.get("name") not in keys.get("настройка", set())]
        fp.write_text(json.dumps(f, ensure_ascii=False, indent=2), encoding="utf-8")


def _simple_sections(lines: list[str]) -> tuple[list[str], list[dict]]:
    """Разделы любого уровня с полями «Имя: значение» и текстом — для обложки, задач и блоков работ."""
    heads = [(i, HEAD_RE.match(x)) for i, x in enumerate(lines)]
    heads = [(i, m) for i, m in heads if m]
    intro = lines[: heads[0][0]] if heads else lines
    out = []
    for n, (i, m) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        out.append(
            {
                "level": len(m.group(1)),
                "title": m.group(2).strip(),
                "anchor": m.group(3),
                "line": i + 1,
                "body": lines[i + 1 : end],
            }
        )
    return intro, out


def _fields_text(body: list[str], names: tuple[str, ...]) -> tuple[dict, list[str]]:
    """Поля из списка names (значение строкой, у поля без значения — пункты списка под ним) и текст."""
    fields: dict = {}
    text: list[str] = []
    cur = None
    for line in body:
        s = line.strip()
        if not s:
            cur = None
            continue
        m = re.match(r"^([^:]+): ?(.*)$", s)
        if m and m.group(1) in names:
            cur = m.group(1)
            fields[cur] = m.group(2).strip() if m.group(2).strip() else []
            continue
        if cur and isinstance(fields.get(cur), list) and s.startswith("- "):
            fields[cur].append(s[2:].strip())
            continue
        cur = None
        text.append(s)
    return fields, text


def keys_in(value) -> list[str]:
    vals = value if isinstance(value, list) else [value or ""]
    return [k for v in vals for k in LINK_RE.findall(v)]


class ChangeModel:
    """Идущее изменение (раздел 07): копии с правками в TOBE/, мир «как будет», обложка, задачи, тесты, блоки, доска.

    Изменение открыто, если есть обложка TOBE/README.md. Мир «как будет» — «как есть», в котором задетые файлы
    заменены копиями без пометок; на нём MapModel(world=True) считает всё производное."""

    def __init__(self, root: Path, asis: MapModel | None = None):
        self.root = root.resolve()
        self.dir = self.root / "TOBE"
        self.asis = asis or MapModel(self.root)
        self.errors: list[str] = []
        self.blocks: list[Block] = []
        self.copies: dict[str, str] = {}  # ASIS/<путь> → TOBE/<путь>
        self.new_files: set[str] = set()  # ASIS/<путь> копий без пары в «как есть»
        self.line_map: dict[str, list[int]] = {}  # ASIS/<путь> → строка копии на каждую строку мира
        self.title = ""
        self.intro: list[str] = []
        self.cover: dict = {}
        self.decisions: dict[str, dict] = {}  # d-… → решение из набора требований (read_requirements)
        self.req_weak: list[dict] = []  # пункты требований «предложено» и «открыто» — вопросы к решающему
        self.cover_refs: list[str] = []  # [[d-…]] раздела «Решения» обложки
        self.consequences: list[str] = []
        self.untouched: list[str] = []
        self.fates: list[str] = []
        self.tasks: dict[str, dict] = {}
        self.tests: dict[str, dict] = {}
        self.work: list[dict] = []
        self.board: dict = {}
        self.world: MapModel | None = None
        self.open = (self.dir / "README.md").is_file()
        if self.open:
            self._load()

    def _load(self) -> None:
        bp = self.dir / "board.yaml"
        if bp.is_file():
            self.board = (yaml.safe_load(bp.read_text(encoding="utf-8")) or {}).get("nodes") or {}
        tmp = Path(tempfile.mkdtemp(prefix="map-tobe-"))
        try:
            world_root = tmp / "architecture"
            shutil.copytree(self.root / "project", world_root / "project")
            self._new_services(world_root / "project")
            shutil.copytree(
                self.root / "ASIS",
                world_root / "ASIS",
                ignore=shutil.ignore_patterns("*.html", "keys.js"),
            )
            for p in sorted(self.dir.rglob("*.md"), key=path_order):
                rel = p.relative_to(self.dir).as_posix()
                if rel in ("README.md", "blocks.md") or rel.endswith("tasks.md") or rel.startswith(".draft/"):
                    continue  # .draft/ — черновик закрытия (map.py draft): копии без пометок, не правки
                lines = read_md(p)
                blocks, errs = parse_blocks(f"TOBE/{rel}", lines)
                self.blocks += blocks
                self.errors += errs
                asis_rel = f"ASIS/{rel}"
                self.copies[asis_rel] = f"TOBE/{rel}"
                gone_whole = bool(lines) and (bm := BLOCK_OPEN_RE.match(lines[0])) is not None and "уходит" in bm.group(0)
                if not (self.root / asis_rel).is_file() and not gone_whole:  # ушедший целиком, уже удалённый apply, — не новый
                    self.new_files.add(asis_rel)
                    self._new_file(f"TOBE/{rel}", lines)
                wl, src = world_lines(lines)
                self.line_map[asis_rel] = src
                out = world_root / asis_rel
                if (_is_slice(rel) or rel.startswith("_processes/")) and not any(x.strip() for x in wl):
                    out.unlink(missing_ok=True)  # срез или процесс, ушедший целиком: в мире его нет, а не пустой файл
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text("\n".join(wl), encoding="utf-8", newline="\n")
            _drop_gone_facts(world_root, self.blocks)
            self.world = MapModel(world_root, repo=self.asis.repo, world=True)
            # Временная копия удаляется ниже — строки её md запоминаются: по ним find.py --text --tobe ищет место слова.
            self.world.md_cache = {
                p.relative_to(world_root).as_posix(): read_md(p) for p in world_root.rglob("*.md")
            }
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self._cover()
        for p in sorted(self.dir.glob("*/tasks.md"), key=path_order):
            self._tasks(p.parent.name, p)
        self._work()
        seen: dict[str, Block] = {}
        for b in self.blocks:
            if b.number in seen:
                self.errors.append(
                    f"{b.file}:{b.line} — номер правки {b.number} уже есть: {seen[b.number].file}:{seen[b.number].line}"
                )
            seen[b.number] = b
            if b.status not in (self.asis.settings.get("statuses") or []):
                self.errors.append(
                    f"{b.file}:{b.line} — статус «{b.status}» не из project/settings.yaml (statuses)"
                )

    def _new_services(self, project: Path) -> None:
        """Новый сервис — папка в TOBE/ без записи в реестре: его запись до закрытия лежит в поле registry узла
        в TOBE/board.yaml. Мир «как будет» получает её в реестр (перед узлами из asis, которые он заменяет; фактов
        у сервиса ещё нет — facts: []) и место узла на доске; без неё проверки не видели бы его файлов."""
        reg_p, board_p = project / "services.yaml", project / "board.yaml"
        reg = yaml.safe_load(reg_p.read_text(encoding="utf-8-sig")) or {}
        new = {}
        for d in sorted((p for p in self.dir.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))), key=path_order):
            if d.name in reg:
                continue
            node = self.board.get(d.name)
            if isinstance(node, dict) and node.get("status") == "gone":
                continue  # ушедший сервис: запись реестра убирают на закрытии, до очистки «как будет»
            rec = node.get("registry") if isinstance(node, dict) else None
            if not isinstance(rec, dict):
                self.errors.append(f"TOBE/{d.name}/ — новый сервис без записи реестра: в TOBE/board.yaml у узла "
                                   f"{d.name} нет поля registry, и проверки «как будет» его файлов не видят")
                continue
            new[d.name] = ({**rec, "facts": []}, node)
        if not new:
            return
        out = {}
        for svc, rec in reg.items():
            for n, (r, node) in new.items():
                if svc in (node.get("asis") or []) and n not in out:
                    out[n] = r
            out[svc] = rec
        out.update({n: r for n, (r, _) in new.items() if n not in out})
        reg_p.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8")
        board = (yaml.safe_load(board_p.read_text(encoding="utf-8-sig")) if board_p.is_file() else None) or {}
        board["nodes"] = {**(board.get("nodes") or {}),
                          **{n: list(node["pos"]) for n, (_, node) in new.items() if node.get("pos")}}
        board_p.write_text(yaml.safe_dump(board, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _new_file(self, rel: str, lines: list[str]) -> None:
        """Новый файл «как будет» — одна правка «новое» на весь файл: «Правка: c-… · <статус>», «Почему: …»."""
        m = NEW_FILE_RE.match(lines[0] if lines else "")
        if not m:
            self.errors.append(f"{rel}:1 — новый файл без первой строки «Правка: c-… · <статус>»")
            return
        why = lines[1][len("Почему:") :].strip() if len(lines) > 1 and lines[1].startswith("Почему:") else ""
        if not why:
            self.errors.append(f"{rel}:2 — у правки {m.group(1)} нет второй строки «Почему: …»")
        self.blocks.append(
            Block("новое", m.group(1), m.group(2).strip(), None, rel, 1, len(lines), why=why, what="файл")
        )

    def _cover(self) -> None:
        lines = read_md(self.dir / "README.md")
        intro, secs = _simple_sections(lines)
        for s in secs:
            if s["level"] == 1:
                self.title = s["title"]
                f, t = _fields_text(s["body"], COVER_FIELDS)
                self.cover = f
                self.intro = t
            elif s["anchor"] and s["anchor"].startswith("d-"):
                self.errors.append(f"TOBE/README.md:{s['line']} — решение {s['anchor']} разделом обложки: решения с "
                                   f"якорями — в наборе требований, на обложке — строка «- [[{s['anchor']}]] — сжато»")
            elif s["level"] == 2 and s["title"] == "Решения":
                self.cover_refs += [r for x in s["body"] for r in re.findall(r"\[\[(d-[a-z0-9-]+)\]\]", x)]
            elif s["level"] == 2 and s["title"] in ("Последствия для процессов", "Не задеты", "Судьбы проблем"):
                items = [x.strip()[2:] for x in s["body"] if x.strip().startswith("- ")]
                {"Последствия для процессов": self.consequences, "Не задеты": self.untouched,
                 "Судьбы проблем": self.fates}[s["title"]].extend(items)
        spec = str(self.cover.get("Требования") or "")
        files = requirement_files(self.root, spec)
        if not files:
            self.errors.append(f"TOBE/README.md — «Требования:» {'нет' if not spec else f'«{spec[:60]}» — файлов нет'}: "
                               f"решения изменения читаются из его набора требований")
        statuses = list(self.asis.settings.get("statuses") or [])
        self.decisions, self.req_weak, errors = read_requirements(files, self.root.parent, statuses)
        self.errors += errors
        self.errors += [f"TOBE/README.md — в «Решения» [[{d}]], а в требованиях такого якоря нет"
                        for d in self.cover_refs if d not in self.decisions]

    def _tasks(self, svc: str, p: Path) -> None:
        _, secs = _simple_sections(read_md(p))
        part = None
        for s in secs:
            if s["level"] == 2:
                part = s["title"]
                continue
            if s["level"] == 3 and s["anchor"]:
                names = TASK_FIELDS if part == "Задачи" else TEST_FIELDS
                f, t = _fields_text(s["body"], names)
                rec = {"title": s["title"], "service": svc, "line": s["line"], "text": t, **f}
                (self.tasks if part == "Задачи" else self.tests)[s["anchor"]] = rec

    def _work(self) -> None:
        p = self.dir / "blocks.md"
        if not p.is_file():
            return
        intro, secs = _simple_sections(read_md(p))
        for s in secs:
            if s["level"] == 2:
                f, t = _fields_text(s["body"], WORK_FIELDS)
                self.work.append({"title": s["title"], "anchor": s["anchor"], "text": t, **f})

    # что задето ----------------------------------------------------------------------------------

    def services(self) -> list[str]:
        """Задетые сервисы — у кого есть папка в TOBE/."""
        return [
            s for s in self.world.services if (self.dir / s).is_dir()
        ] if self.world else []

    def processes(self) -> list[str]:
        """Задетые процессы — с файлом процесса в TOBE/ или со срезом любого участника."""
        out = []
        for rel in self.copies:
            parts = rel.split("/")
            if len(parts) == 3 and parts[1] == "_processes":
                out.append(parts[2][:-3])
            elif len(parts) == 4 and parts[2] == "processes":
                out.append(parts[3][:-3])
        return sorted(set(out))

    def blocks_in(self, asis_rel: str) -> list[Block]:
        return [b for b in self.blocks if b.asis_file == asis_rel]


def load(root: str | Path) -> MapModel:
    return MapModel(Path(root))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    stubs = "--stubs" in args
    if stubs:  # --stubs [начало пути]: заглушки выгрузки в файлах, чей путь от корня карты так начинается
        i = args.index("--stubs")
        prefix = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith("-") else ""
        args = args[:i] + args[i + 1 + (1 if prefix else 0) :]
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent
    m = load(root)
    if stubs:
        found = [s for s in m.stubs if s.startswith(prefix)]
        print(f"заглушек{' в ' + prefix if prefix else ''}: {len(found)}")
        for s in found:
            print(" ", s)
        return 1 if found else 0
    kinds: dict[str, int] = {}
    for e in m.entities.values():
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    print(
        f"карта {m.root}: сервисов {len(m.services)}, процессов {len(m.processes)}, ссылок {len(m.links)}"
    )
    print("сущности:", ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    for e in m.errors:
        print("ошибка:", e)
    return 1 if m.errors else 0


if __name__ == "__main__":
    sys.exit(main())
