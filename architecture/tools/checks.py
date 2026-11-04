"""Проверки карты поверх модели: то, что не видно в одном md при разборе, — пары между файлами, факты против
разделов, язык, секреты.

Зачем. Модель (mapmodel.py) при разборе ловит ошибки одного файла: формат, ключи, ссылки md, строки «Код:»,
стрелки процесса. Здесь — остальное: каждому факту есть раздел, на каждый шаг ведёт стрелка, каждый вызов по сети
описан в «Связях», числовые колонки с единицами, в md нет значений секретов, в тексте нет запрещённых слов.
Две карты — чистая проверочная и испорченные (tools/samples/bad/) — держат проверки честными: на чистой все молчат,
на испорченной своя срабатывает.

Кто зовёт. build.py при каждой сборке и с --check; тесты tools/tests/test_checks.py. Отдельно:
  python <карта>/tools/checks.py [--root <карта>]   — сообщения проверок; код выхода 1, если есть ошибки
Что читает. Модель карты, project/settings.yaml (слова, единицы, служебные имена, шаблоны имён секретов, файлы
секретов), файлы секретов (.env) — только чтобы найти их значения в md. Ничего не пишет; значения секретов не
печатает никогда — в сообщении только имя.

Номера проверок — как в списке проверок карты:
   1, 3, 4, 5, 8, 9, 18 — формат, ссылки md и [[…]], «Код:», процесс, файлы справочника, якоря — ловит модель при разборе
   2  первый абзац и первая фраза шага — без «ниже», «выше», «как сказано» (предупреждение)
   6  значения секретов из .env не попали в md
   7  запрещённые слова и слова без уточнения (предупреждение)
  10  факт ↔ раздел: на каждый метод, таблицу, настройку, экспорт из фактов есть раздел (кроме служебных)
  11  раздел справочника, которого нет в фактах (предупреждение)
  12  срез ↔ процесс: процесс с тем же ключом есть, сервис — его участник
  13  на каждый шаг среза ведёт хотя бы одна стрелка (остальное о «внутри» ловит модель)
  14  `зовёт` чужого метода по сети ↔ подраздел «Связей»; стрелка-запрос ↔ шаг отправителя, который её зовёт
  15  связь, которую не зовёт ни один шаг (предупреждение)
  16  «Связи»: кого зовут — есть в реестре или настройках; вызываемый метод есть в его справочнике
  17  точка входа не может иметь сразу строку `Справочник:` и шаг, который её обрабатывает
  19  у каждой числовой колонки — единица в `Единицы:`, единица из списка проекта
  20  узел доски размещён в project/board.yaml (предупреждение)
  21  `Код:` раздела справочника ведёт в код своего сервиса (предупреждение)
  23  у настройки с секретным именем в фактах нет значения (только маска)
Сообщение — «путь:строка — что не так; что делать»; путь — от корня карты.

Чего не делает. «Как будет» (№25) проверяет tobe_checks.py, незапомненные строки кода (№24) — build.py --check,
изменившиеся — live.py. Не ходит в живые системы.
"""

from __future__ import annotations

import fnmatch
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapmodel import (  # noqa: E402
    INLINE_CODE_RE,
    LINK_RE,
    REFERENCE_FILES,
    MapModel,
    facts_settings,
    first_phrase,
    split_key,
)

NUMERIC = {"integer", "bigint", "smallint", "numeric", "float8", "real", "double precision", "decimal"}
ENTRY = ("метод", "функция", "страница", "команда")
NETWORK_KINDS = ("service", "frontend", "cli")  # кого зовут по сети; пакет и библиотеку — функцией
DEICTIC_RE = re.compile(r"(?<![\w-])(ниже|выше|как сказано)(?![\w-])", re.I)
SECRET_MASK = "‹секрет›"


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def is_secret_name(name: str, rules: dict) -> bool:
    u = name.upper()
    return any(fnmatch.fnmatchcase(u, p) for p in rules.get("match", [])) and not any(
        fnmatch.fnmatchcase(u, p) for p in rules.get("except", [])
    )


def plain(text: str) -> str:
    """Текст без кода в обратных кавычках и без ссылок [[…]] — в них имена из кода, их слова не проверяются."""
    return LINK_RE.sub(" ", INLINE_CODE_RE.sub(" ", text))


def run(m: MapModel, texts: list[tuple[str, Path]] | None = None) -> Report:
    """Все проверки карты. texts — md, чей текст проверять на секреты и слова: (имя в сообщении, путь); по умолчанию —
    md самой карты. Мир «как будет» лежит во временной папке, поэтому для него сюда передают копии из TOBE/."""
    r = Report()
    files = texts if texts is not None else [(rel, m.root / rel) for rel in m.files]
    _deictic(m, r)
    _secrets_in_md(m, r, files)
    _words(m, r, files)
    _facts_vs_sections(m, r)
    _slices(m, r)
    _calls(m, r)
    _entries(m, r)
    _units(m, r)
    _board(m, r)
    _owner(m, r)
    _secret_facts(m, r)
    return r


def at(e) -> str:
    return f"{e.file}:{e.line}" if e.line else e.file


# ─── проверки файла ────────────────────────────────────────────────────────────────────────────────


def _deictic(m: MapModel, r: Report) -> None:
    """№2: первый абзац и первая фраза шага читаются отдельно — без отсылок «ниже», «выше»."""
    for e in m.entities.values():
        if not e.text:
            continue
        if e.kind in ("документ", "срез", "своя работа", "процесс"):
            src, what = e.text[0], "первый абзац"
        elif e.kind == "шаг":
            src, what = first_phrase(e.text[0]), "первая фраза шага"
        else:
            continue
        hit = DEICTIC_RE.search(plain(src))
        if hit:
            r.warn(
                f"{at(e)} — {what} со словом «{hit.group(1)}»: генератор ставит его на другие страницы, "
                f"там «{hit.group(1)}» ни к чему не ведёт"
            )


def _secrets_in_md(m: MapModel, r: Report, files: list[tuple[str, Path]]) -> None:
    """№6: значения секретов из файлов .env (secret_files настроек проекта) не попали в md карты."""
    rules = m.settings.get("secret_names") or {}
    values: dict[str, str] = {}
    for pattern in m.settings.get("secret_files") or []:
        for p in sorted(m.repo.glob(pattern), key=lambda x: [s.casefold() for s in x.parts]):
            if not p.is_file():
                continue
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                k, sep, v = line.partition("=")
                k, v = k.strip(), v.strip().strip("'\"")
                if sep and len(v) >= 8 and is_secret_name(k, rules) and v != SECRET_MASK:
                    values.setdefault(v, k)
    if not values:
        return
    for rel, path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for v, k in values.items():
            if v in text:
                n = text[: text.index(v)].count("\n") + 1
                r.err(f"{rel}:{n} — в тексте значение секрета {k}: убери его, пиши имя настройки")


def _words(m: MapModel, r: Report, files: list[tuple[str, Path]]) -> None:
    """№7: запрещённые слова и слова без уточнения — в пределах фразы."""
    words = m.settings.get("words") or {}
    quals = m.settings.get("qualifiers") or {}
    # слово — начало слова; после «/» — часть пути (`/api/v1/…`), это имя из кода
    # заглавное сокращение (API, CLI) — словом целиком и с учётом регистра: иначе «CLI» ловит `client_id`
    wre = [
        (w, re.compile(rf"(?<![\w/-]){re.escape(w)}(?!\w)") if w.isupper() else re.compile(rf"(?<![\w/-]){re.escape(w)}\w*", re.I), repl)
        for w, repl in words.items()
    ]
    qre = [(w, re.compile(rf"(?<![\w/-]){re.escape(w)}\w*", re.I), q) for w, q in quals.items()]
    for rel, path in files:
        for n, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            if line.startswith(("Код:", "|", "#")) or line.lstrip().startswith("```"):  # заголовки — имена
                continue
            text = plain(line)
            for w, rx, repl in wre:
                hit = rx.search(text)
                if hit:
                    r.warn(f"{rel}:{n} — слово «{hit.group(0)}»: пиши «{repl}»")
            for w, rx, q in qre:
                for phrase in re.split(r"(?<=[.!?;])\s", text):
                    hit = rx.search(phrase)
                    if hit and not any(x.lower() in phrase.lower() for x in q):
                        r.warn(f"{rel}:{n} — «{hit.group(0)}» без уточнения ({', '.join(q)}) в той же фразе")


# ─── проверки карты ────────────────────────────────────────────────────────────────────────────────


def _facts_vs_sections(m: MapModel, r: Report) -> None:
    """№10, №11: факт ↔ раздел справочника."""
    names = m.settings.get("service_names") or {}
    skip_methods = set(names.get("methods") or [])
    skip_settings = set(names.get("settings") or [])
    for svc in m.services:
        f = m.facts.get(svc)
        if not f:
            continue
        parts = set(f.get("parts") or [])
        have: dict[str, set[str]] = {"метод": set(), "таблица": set(), "настройка": set(), "функция": set()}
        if "fastapi-openapi" in parts:
            for x in (f.get("fastapi-openapi") or {}).get("methods", []):
                key = f"{x['method']} {x['path']}"
                have["метод"].add(key)
                if key not in skip_methods and not m.get(svc, key):
                    r.err(f"ASIS/{svc}/methods.md — метод {key} есть в фактах ({x.get('ref', '')}), а раздела нет")
        if "postgres" in parts:
            for t in (f.get("postgres") or {}).get("tables", []):
                have["таблица"].add(t["name"])
                e = m.get(svc, t["name"])
                if not e or e.kind != "таблица":
                    r.err(f"ASIS/{svc}/storage.md — таблица {t['name']} есть в фактах, а раздела нет")
        for s in facts_settings(f):
            have["настройка"].add(s["name"])
            e = m.get(svc, s["name"])
            if s["name"] not in skip_settings and (e is None or e.extra.get("facts_only")):
                r.err(
                    f"ASIS/{svc}/settings.md — настройка {s['name']} есть в фактах ({s.get('ref', '')}), "
                    f"а раздела в «Настройках» нет"
                )
        if "python-exports" in parts:
            for x in (f.get("python-exports") or {}).get("exports", []):
                have["функция"].add(x["name"])
                if not m.get(svc, x["name"]):
                    r.err(f"ASIS/{svc}/exports.md — {x['name']} есть в фактах ({x.get('ref', '')}), а раздела нет")
        checked = {"метод": "fastapi-openapi", "таблица": "postgres", "функция": "python-exports"}
        for e in m.by_service.get(svc, []):
            if e.extra.get("facts_only"):
                continue
            part = checked.get(e.kind)
            if e.kind == "настройка":
                ok = any(p in parts for p in ("pydantic-settings", "vite-env"))
            else:
                ok = part in parts if part else False
            if ok and e.addr not in have[e.kind]:
                r.warn(f"{at(e)} — {e.kind} {e.addr} есть в md, а в фактах нет: опечатка в имени или раздел устарел")


def _slices(m: MapModel, r: Report) -> None:
    """№12, №13: срез ↔ процесс; на каждый шаг среза ведёт стрелка."""
    for (svc, proc), sl in m.slices.items():
        pe = m.processes.get(proc)
        if pe is None:
            r.err(f"{sl.file}:1 — срез процесса {proc}, а файла ASIS/_processes/{proc}.md нет")
            continue
        if svc not in pe.extra.get("participants", []):
            r.err(f"{sl.file}:1 — у {svc} есть срез, а в «Участники:» процесса {proc} его нет")
        inside = {x for a in m.arrows.get(proc, []) for x in a.inside}
        for addr in sl.extra.get("steps", []):
            st = m.get(svc, addr)
            if st and st.extra.get("short") not in inside:
                r.err(
                    f"{at(st)} — на шаг {st.extra.get('short')} не ведёт ни одна стрелка процесса {proc}: "
                    f"поставь его в столбец «внутри» стрелки, которую он делает"
                )


def _network(m: MapModel, svc: str | None) -> bool:
    return bool(svc) and (svc.startswith("external:") or m.registry.get(svc, {}).get("kind") in NETWORK_KINDS)


def _calls(m: MapModel, r: Report) -> None:
    """№14, №15, №16: вызовы по сети ↔ «Связи»."""
    used: set[str] = set()
    for ln in m.links:
        if ln.kind != "зовёт":
            continue
        caller = m._service_of_file(ln.src_file)
        if not caller or ln.service == caller or not _network(m, ln.service):
            continue
        conn = m.get(caller, f"{caller} → {ln.service}")
        sub = m.get(caller, f"{caller} → {ln.service}: {ln.key}")
        if conn:
            used.add(conn.addr)
        if sub:
            used.add(sub.addr)
        if not sub:
            r.err(
                f"{ln.src_file}:{ln.src_line} — шаг зовёт [[{ln.raw}]], а в «Связях» README {caller} нет "
                f"«### → {ln.service}» / «#### {ln.key}»: допиши связь — как вызов себя ведёт"
            )
    for proc, arrows in m.arrows.items():
        for a in arrows:
            if a.kind not in ("запрос", "внешний провайдер") or a.sender in ("human", "schedule"):
                continue
            if f"{a.file}:{a.line} — «внутри» ???" in m.stubs:  # сторона отправителя ещё не перенесена
                continue
            keys = [split_key(k, set(m.services)) for k in LINK_RE.findall(a.how)]
            if not keys:
                continue
            steps = [x for x in a.inside if x.startswith(f"{a.sender}#")]
            calls = {
                (ln.service, ln.key)
                for x in steps
                for ln in m.links
                if ln.kind == "зовёт" and ln.src == f"{a.sender}/{proc}#{x.split('#', 1)[1]}"
            }
            if not any(k in calls for k in keys) and not _stream_event(m, proc, a, keys, steps):
                r.err(
                    f"{a.file}:{a.line} — стрелка {a.id} «{a.sender} → {a.receiver}»: ни один шаг отправителя "
                    f"в «внутри» не зовёт {a.how}; допиши «Справочник: зовёт …» в шаг {a.sender}"
                )
    for svc in m.services:
        for c in m.connections(svc):
            to = c.extra.get("to", "")
            if to.startswith("external:"):
                if to[9:] not in m.external:
                    r.err(f"{at(c)} — провайдера {to[9:]} нет в external настроек проекта")
            elif to not in m.registry:
                r.err(f"{at(c)} — сервиса {to} нет в реестре project/services.yaml")
            subs = [e for e in m.by_service.get(svc, []) if e.kind == "связь-метод" and e.parent == c.addr]
            for s in subs:
                key = s.addr.split(": ", 1)[1]
                dead = "Не доходит" in s.fields or "Не доходит" in c.fields
                if to in m.registry and not dead and not m.get(to, key) and not _fact_method(m, to, key):
                    r.err(f"{at(s)} — метода {key} нет в справочнике {to}")
                if s.addr not in used and not dead:
                    r.warn(f"{at(s)} — связь «{s.addr}» не зовёт ни один шаг: допиши `зовёт` в шаг или убери связь")


def _stream_event(m: MapModel, proc: str, a, keys: list[tuple[str, str]], steps: list[str]) -> bool:
    """Событие потока — стрелка от сервера к клиенту по своему методу с `Вид: поток SSE` или `WebSocket`: её шаг
    отправителя не зовёт метод, а обрабатывает его. Ответ обычного метода так не проходит — он часть стрелки-запроса."""
    for svc, key in keys:
        e = m.get(svc, key) if svc == a.sender else None
        kind = e.fields["Вид"].value if e and "Вид" in e.fields else ""
        if not kind.startswith(("поток SSE", "WebSocket")):
            continue
        handled = {
            ln.key
            for x in steps
            for ln in m.links
            if ln.kind == "обрабатывает" and ln.src == f"{a.sender}/{proc}#{x.split('#', 1)[1]}"
        }
        if key in handled:
            return True
    return False


def _fact_method(m: MapModel, svc: str, key: str) -> bool:
    return any(
        f"{x['method']} {x['path']}" == key for x in (m.facts.get(svc, {}).get("fastapi-openapi") or {}).get("methods", [])
    )


def _entries(m: MapModel, r: Report) -> None:
    """№17: у точки входа — шаг или строка `Справочник:`, не оба."""
    for e in m.entities.values():
        if e.kind in ENTRY and "Справочник" in e.fields and m.steps_handling(e.service or "", e.addr):
            r.err(
                f"{e.file}:{e.fields['Справочник'].line} — у {e.addr} строка «Справочник:», а его уже обрабатывают "
                f"шаги: что метод трогает — в шагах, строку убери"
            )


def _units(m: MapModel, r: Report) -> None:
    """№19: каждая числовая колонка таблицы — с единицей из списка проекта."""
    units = set(m.settings.get("units") or [])
    skip = set((m.settings.get("service_names") or {}).get("columns") or [])
    for svc in m.services:
        for t in (m.facts.get(svc, {}).get("postgres") or {}).get("tables", []):
            e = m.get(svc, t["name"])
            if not e or e.kind != "таблица":
                continue
            given: dict[str, str] = {}
            f = e.fields.get("Единицы")
            for item in ([f.value] if f and f.value else []) + (f.items if f else []):
                for part in item.split(" · "):
                    mm = re.match(r"`([^`]+)`\s*—\s*(.+)", part.strip())
                    if mm:
                        given[mm.group(1)] = mm.group(2).strip()
            for col, unit in given.items():
                if unit not in units:
                    r.err(f"{at(e)} — единица «{unit}» у {col} не из списка units настроек проекта: {', '.join(sorted(units))}")
            for c in t.get("columns", []):
                if c.get("type") in NUMERIC and c["name"] not in skip and c["name"] not in given:
                    r.err(f"{at(e)} — числовая колонка {t['name']}.{c['name']} без единицы: допиши в «Единицы:»")


def _board(m: MapModel, r: Report) -> None:
    """№20: узлы доски размещены."""
    nodes = set(m.services) | {f"external:{k}" for k in m.external} | set(m.settings.get("stores") or [])
    for n in sorted(nodes - set(m.board)):
        r.warn(f"project/board.yaml — узел {n} не размещён: на доске он встанет на место по умолчанию")


def _owner(m: MapModel, r: Report) -> None:
    """№21: `Код:` раздела справочника ведёт в код своего сервиса или в общие файлы репо (`shared_paths`)."""
    known = tuple(m.settings.get("shared_paths") or ())
    for svc in m.services:
        info = m.registry.get(svc, {})
        roots = [x for x in (info.get("root"), info.get("package")) if x]
        if not roots:
            continue
        for e in m.by_service.get(svc, []):
            if not any(e.file.endswith(f"/{name}.md") for name in REFERENCE_FILES):
                continue
            alien = [c for c in e.code if not any(c.path.startswith(x) for x in roots)]
            alien = [c for c in alien if not (known and c.path.startswith(known))]
            if alien:
                r.warn(
                    f"{at(e)} — «Код:» ведёт в чужой код ({alien[0].path}): знание этого кода — у его хозяина, "
                    f"здесь — ключ на его раздел"
                )


def _secret_facts(m: MapModel, r: Report) -> None:
    """№23: у настройки с секретным именем в фактах нет значения — только маска."""
    rules = m.settings.get("secret_names") or {}
    for svc, f in m.facts.items():
        for s in facts_settings(f):
            if not is_secret_name(s["name"], rules):
                continue
            for k in ("value", "default"):
                v = str(s.get(k) or "")
                if v and v != SECRET_MASK and "‹секрет›" not in v:
                    r.err(f"ASIS/{svc}/.facts.json — у {s['name']} в «{k}» значение секрета: перевыними факты, скрипт его маскирует")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    root = Path(args[args.index("--root") + 1]) if "--root" in args else Path(__file__).resolve().parent.parent
    m = MapModel(root)
    r = run(m)
    for e in m.errors + r.errors:
        print("ошибка:", e)
    for w in m.warnings + r.warnings:
        print("предупреждение:", w)
    print(f"ошибок: {len(m.errors) + len(r.errors)}, предупреждений: {len(m.warnings) + len(r.warnings)}")
    return 1 if m.errors or r.errors else 0


if __name__ == "__main__":
    sys.exit(main())
