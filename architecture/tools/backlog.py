"""Бэклог: единая папка задач и требований — список, новая задача, сколько осталось решить, проверка, в работу, удалить.

Зачем. Задача живёт сразу в трёх местах: промт, папка, раздел списка. Руками одно из них забывается, а «сколько
осталось решить» по тексту не посчитать глазами. Скрипт держит три места вместе и считает остаток по самому промту,
поэтому отдельного поля статуса, которое разойдётся с текстом, нет.

Кто зовёт. Скилл /backlog, шаги /dev-start и /dev-close (map.py start зовёт отсюда ensure). Из корня репо:
  python <карта>/tools/backlog.py                         нумерованный список задач с остатком
  python <карта>/tools/backlog.py new <тема> "<название>" [--tobe <тема родителя>]
                                                          промт, папка, раздел списка; --tobe — короткий promt-tobe-<тема>.md
  python <карта>/tools/backlog.py status <номер|тема>     шаги с отметками, что будет на следующих, вопросы к решающему
  python <карта>/tools/backlog.py check [<номер|тема>]    три места сходятся; новые строки без цитаты и пометки,
                                                          незаполненные места, битые ссылки
  python <карта>/tools/backlog.py take <номер|тема> <ветка>   в списке — «в работе: ветка …»
  python <карта>/tools/backlog.py drop <тема> [--force] [--ignore-links]
                                                          удалить задачу: раздел списка, промт, папка; только по теме:
                                                          номер сдвигается; незакоммиченные правки — только с --force;
                                                          ссылки md на промт и папку задачи из других задач бэклога и из
                                                          карты <карта>/ASIS — называет файлом и строкой и не удаляет;
                                                          удалить всё равно, оставив их битыми, — --ignore-links
  python <карта>/tools/backlog.py --selftest              самопроверка во временной папке
  … --repo <папка>   другой корень репо

Что читает. Папку бэклога (ключ backlog в project/settings.yaml, нет ключа — _backlog), её CLAUDE.md, промты и md папок
задач, git diff HEAD — какие строки новые; drop — ещё md карты <карта>/ASIS. Ссылка для drop — ссылка md [текст](путь),
путь которой ведёт в промт или папку задачи; имя файла словами или в кавычках — не ссылка: так пишут «задача сделана». Пометки разбирает mapmodel.py: так же их читают where.py и проверки «как будет».

Что пишет. new, take, drop — файлы бэклога, drop ещё и индекс git; остальные команды ничего не пишут. Не коммитит.

Шаги задачи (раздел промта заполнен, в нём нет вопросов — шаг пройден; заполнить — значит убрать «<заполнить: …>»):
  1 Записать — «Что хотим» (у promt-tobe — «Что надо будет сделать»); 2 Кто и что — «Кто и что должен уметь», «Критерии
  приёмки»; 3 Что потянет за собой — раздел с тем же именем; 4 Макет — раздел «Макет»; 5 Готово к /dev — шаги 1–4
  пройдены и вопросов нет. Запись вопросы не держат: «Что хотим» с пометкой всё равно записано.
  Текущий — первый непройденный. Вопрос — пункт с пометкой (не согласовано) или (открыто) в промте и md папки задачи.

Коды выхода: 0 — готово (предупреждения check код не меняют); 1 — ошибка задачи или расхождение мест; 2 — ошибка вызова.

Чего не делает. Не решает за решающего: остаток считает, пометки не снимает. Строки «без цитаты и пометки» — подсказка
для глаз, а не приговор: факт из кода в требованиях тоже попадёт в этот список.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapmodel import REQ_MARK_RE, read_md, read_requirements  # noqa: E402

TOOLS = Path(__file__).resolve().parent
TEMPLATES = TOOLS.parents[1] / ".claude" / "skills" / "backlog" / "templates"
DEFAULT_DIR = "_backlog"
LIST_FILE = "CLAUDE.md"
THEME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
HEAD_RE = re.compile(r"^### (.+?) → \[`promt-([a-z0-9-]+)\.md`\]")
BLANK = "<заполнить"
STATUSES = ["решено", "по рекомендации", "не согласовано", "открыто"]
# Шаги: название, разделы промта (любой набор из списка заполнен — шаг пройден), что будет на шаге.
STEPS = (
    ("Записать", (("Что хотим",), ("Что надо будет сделать",)), "слова решающего дословно: промт, папка, строка в списке"),
    ("Кто и что", (("Кто и что должен уметь", "Критерии приёмки"),),
     "кто пользователь, что он должен уметь, как поймём, что готово; не знаешь, что хочешь, — предложу решение целиком"),
    ("Что потянет за собой", (("Что потянет за собой",),), "что понадобится следом: сейчас или короткой задачей на потом"),
    ("Макет", (("Макет",),), "есть экран — макет до кода, по экрану за раз; нет экрана — пропускаем"),
    ("Готово к /dev", (), "вопросы закрыты — можно брать в работу"),
)
# Разделы, где нет требований: факты и как начать. Строки из них страховка не показывает.
NOT_REQUIREMENTS = ("Что есть в системе", "Откуда начинать", "Что делали")
# Ответ «шаг не нужен» и служебная разметка — не требование.
SERVICE_LINES = ("<!--", "|", "не нуж", "ничего")
OLD_MARK_RE = re.compile(r"(?<![«*`])(\((?:решено|предложено)\)|✅)")
PENDING_RE = re.compile(r"(?<![«*`])\((?:не согласовано|предложено|открыто)\)")
# Цитата решающего: с датой, «выбрал «…»», «кто: «…»» или фраза от трёх слов. Короткие кавычки — это надпись на экране.
QUOTE_RE = re.compile(r"\d{4}-\d{2}-\d{2}[^«]*«|выбрал[аи]? «|:\s*«|«[^»]*\s[^»]*\s[^»]*»")
LINK_RE = re.compile(r"\]\(([^)#\s]+)")


class Fail(Exception):
    """Ошибка, которую должен увидеть человек; код выхода 1."""


def backlog_dir(repo: Path) -> Path:
    """Папка бэклога: ключ backlog настроек карты, у которой лежит этот инструмент или которая рядом с repo."""
    for settings in (repo / TOOLS.parent.name / "project" / "settings.yaml", repo / "architecture" / "project" / "settings.yaml"):
        if settings.is_file():
            value = (yaml.safe_load(settings.read_text(encoding="utf-8")) or {}).get("backlog")
            if value:
                return repo / str(value)
    return repo / DEFAULT_DIR


def template(name: str, values: dict[str, str]) -> str:
    """Шаблон без его комментария-подсказки, с подставленными значениями."""
    p = TEMPLATES / name
    if not p.is_file():
        raise Fail(f"шаблона {p} нет")
    text = re.sub(r"\A<!--.*?-->\s*", "", p.read_text(encoding="utf-8"), flags=re.S)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def read_list(folder: Path) -> tuple[list[str], list[dict]]:
    """Строки CLAUDE.md и задачи в порядке файла: тема, название, границы раздела. Порядок значит только порядок показа."""
    path = folder / LIST_FILE
    lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n") if path.is_file() else []
    heads = [(i, HEAD_RE.match(x)) for i, x in enumerate(lines)]
    heads = [(i, m) for i, m in heads if m]
    items = []
    for k, (i, m) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        items.append({"theme": m.group(2), "title": m.group(1), "start": i, "end": end, "body": lines[i + 1:end]})
    return lines, items


def field(body: list[str], name: str) -> str:
    """Значение пункта «- **Имя.** …» раздела списка."""
    prefix = f"- **{name}.**"
    return next((x[len(prefix):].strip() for x in body if x.startswith(prefix)), "")


def resolve(folder: Path, ref: str) -> dict:
    """Задача по номеру из показанного списка или по теме."""
    _, items = read_list(folder)
    if ref.isdigit():
        if not 1 <= int(ref) <= len(items):
            raise Fail(f"задачи с номером {ref} нет: в списке {len(items)}")
        return items[int(ref) - 1]
    theme = re.sub(r"^promt-|\.md$", "", ref)
    found = next((x for x in items if x["theme"] in (theme, f"tobe-{theme}")), None)
    if not found:
        raise Fail(f"задачи «{ref}» нет в списке {LIST_FILE}")
    return found


def task_files(folder: Path, theme: str) -> list[Path]:
    """Документы задачи: промт и все md её папки."""
    promt, sub = folder / f"promt-{theme}.md", folder / theme
    return ([promt] if promt.is_file() else []) + (sorted(sub.rglob("*.md")) if sub.is_dir() else [])


def sections(path: Path) -> dict[str, str]:
    """Разделы промта: заголовок «## …» → текст."""
    out: dict[str, str] = {}
    head = None
    for line in read_md(path):
        if line.startswith("## "):
            head = line[3:].strip()
            out[head] = ""
        elif head:
            out[head] += line + "\n"
    return out


def filled(text: str | None) -> bool:
    return bool(text and text.strip()) and BLANK not in text


def questions(folder: Path, theme: str) -> list[dict]:
    """Пункты задачи с пометкой (не согласовано) или (открыто): читаются тем же кодом, что у where.py."""
    return read_requirements(task_files(folder, theme), folder.parent, STATUSES)[1]


def progress(folder: Path, theme: str) -> dict:
    """Какие шаги пройдены, какой текущий, сколько вопросов."""
    secs = sections(folder / f"promt-{theme}.md") if (folder / f"promt-{theme}.md").is_file() else {}
    asked = questions(folder, theme)
    done: list[bool] = []
    for i, (_title, sets, _what) in enumerate(STEPS):
        if not sets:
            done.append(all(done) and not asked)
            continue
        names = [x for group in sets if all(filled(secs.get(y)) for y in group) for x in group]
        answered = i == 0 or not any(PENDING_RE.search(secs.get(x, "")) for x in names)
        done.append(bool(names) and answered)
    current = next((i for i, ok in enumerate(done) if not ok), None)
    return {
        "done": done,
        "current": current,
        "unagreed": sum(x["status"] == "не согласовано" for x in asked),
        "open": sum(x["status"] == "открыто" for x in asked),
        "questions": asked,
    }


def counts(p: dict) -> str:
    return f"не согласовано: {p['unagreed']} · открыто: {p['open']}"


def show_list(folder: Path) -> list[str]:
    """Нумерованный список: номер нужен только чтобы выбрать из показанного, порядка в бэклоге нет."""
    _, items = read_list(folder)
    if not items:
        return ["Бэклог пуст."]
    out = [f"Бэклог: задач {len(items)}. Номер — только чтобы выбрать из этого списка, порядка здесь нет."]
    for n, it in enumerate(items, 1):
        p = progress(folder, it["theme"])
        step = "готово к /dev" if p["current"] is None else f"шаг {p['current'] + 1} из {len(STEPS)}"
        if n > 1:
            out.append("")
        out.append(f"{n}. {it['title']} [{it['theme']}] — {step} · {counts(p)}")
        got, start = field(it["body"], "Получим"), field(it["body"], "С чего начать")
        if got and BLANK not in got:
            out.append(f"   Получим: {got}")
        if start.startswith("в работе"):
            out.append(f"   {start}")
    return out


def show_status(folder: Path, it: dict) -> list[str]:
    """Отметки шагов, что будет дальше и все вопросы: чтобы было видно объём и можно было бросить."""
    p = progress(folder, it["theme"])
    now = p["current"]
    title = f"«{it['title']}»"
    out = [f"{title} — готово к /dev" if now is None else f"{title} — шаг {now + 1} из {len(STEPS)}: {STEPS[now][0]}"]
    for i, (name, _sets, what) in enumerate(STEPS):
        mark = "✅" if p["done"][i] else "▶" if i == now else "⬜"
        out.append(f"{mark} {i + 1}. {name}" + ("" if p["done"][i] else f" — {what}"))
    out.append(counts(p))
    out += [f"  {q['file']}:{q['line']} — ({q['status']}) {q['title']}" for q in p["questions"]]
    out.append("Можно остановиться на любом шаге: /dev доуточнит сам.")
    return out


def new(repo: Path, theme: str, title: str, parent: str | None = None) -> list[str]:
    """Промт, папка, раздел списка. Папка есть всегда, даже пустая: git хранит её по .gitkeep."""
    folder = backlog_dir(repo)
    if not THEME_RE.fullmatch(theme):
        raise Fail("тема — латиницей через дефис")
    if parent and not theme.startswith("tobe-"):
        theme = f"tobe-{theme}"
    promt, sub = folder / f"promt-{theme}.md", folder / theme
    if promt.exists():
        raise Fail(f"{promt.name} уже есть")
    if parent and not (folder / f"promt-{parent}.md").is_file():
        raise Fail(f"задачи-родителя promt-{parent}.md нет")
    folder.mkdir(parents=True, exist_ok=True)
    values = {"название": title, "тема": theme, "родитель": parent or ""}
    write(promt, template("promt-tobe.md" if parent else "promt.md", values))
    sub.mkdir(exist_ok=True)
    if not any(sub.iterdir()):
        write(sub / ".gitkeep", "")
    index = folder / LIST_FILE
    head = index.read_text(encoding="utf-8").replace("\r\n", "\n") if index.is_file() else template("list-head.md", {})
    write(index, head.rstrip("\n") + "\n\n" + template("list-item.md", values).rstrip("\n") + "\n")
    rel = folder.relative_to(repo).as_posix()
    return [f"{rel}/{promt.name}", f"{rel}/{theme}/", f"раздел в {rel}/{LIST_FILE}: заполнить через Edit"]


def ensure(repo: Path, theme: str, title: str) -> tuple[list[str], list[str]]:
    """Для map.py start: промт и папка задачи; нет — новая задача. Отдаёт пути от корня репо и что сделано."""
    folder = backlog_dir(repo)
    rel = folder.relative_to(repo).as_posix()
    if (folder / f"promt-{theme}.md").is_file():
        done = [f"требования: задача {rel}/promt-{theme}.md уже есть"]
    else:
        new(repo, theme, title)
        done = [f"требования: новая задача {rel}/promt-{theme}.md, заполнить через Edit"]
    return [f"{rel}/promt-{theme}.md", f"{rel}/{theme}/"], done


def take(repo: Path, ref: str, branch: str) -> list[str]:
    """Пометить в списке, что задача в работе."""
    folder = backlog_dir(repo)
    it = resolve(folder, ref)
    lines, _ = read_list(folder)
    for i in range(it["start"], it["end"]):
        if lines[i].startswith("- **С чего начать.**"):
            lines[i] = f"- **С чего начать.** в работе: ветка `{branch}`"
            write(folder / LIST_FILE, "\n".join(lines))
            return [f"{it['theme']}: в работе, ветка {branch}"]
    raise Fail(f"у задачи {it['theme']} в списке нет пункта «С чего начать»")


def links_to(repo: Path, it: dict) -> list[str]:
    """Ссылки md на промт и папку задачи из остального бэклога и из карты «как есть»: после drop они ведут в никуда.
    Свои файлы задачи и её раздел списка не в счёт — они уходят вместе с ней."""
    folder = backlog_dir(repo)
    promt, sub = (folder / f"promt-{it['theme']}.md").resolve(), (folder / it["theme"]).resolve()
    own_lines = range(it["start"] + 1, it["end"] + 1)  # раздел задачи в списке, номера строк с 1
    asis = repo / TOOLS.parent.name / "ASIS"
    sources = sorted(folder.rglob("*.md")) + (sorted(asis.rglob("*.md")) if asis.is_dir() else [])
    out = []
    for path in sources:
        real = path.resolve()
        if real == promt or sub in real.parents:
            continue
        for no, line in enumerate(read_md(path), 1):
            if path == folder / LIST_FILE and no in own_lines:
                continue
            hits = []
            for target in LINK_RE.findall(line):
                if target.startswith(("http:", "https:", "mailto:")):
                    continue
                dest = (repo / target.lstrip("/") if target.startswith("/") else path.parent / target).resolve()
                if dest == promt or dest == sub or sub in dest.parents:
                    hits.append(target)
            if hits:
                out.append(f"{path.relative_to(repo).as_posix()}:{no} — ссылка на {', '.join(dict.fromkeys(hits))}")
    return out


def drop(repo: Path, ref: str, force: bool = False, ignore_links: bool = False) -> list[str]:
    """Удалить задачу целиком: раздел списка, промт, папка; всё сразу в индексе git, одним коммитом. Ссылки на неё из
    других задач и карты — сначала назвать: удаляет при них только ignore_links, и они остаются в выводе."""
    if ref.isdigit():
        raise Fail("удалять только по теме: номер — строка показанного списка, он сдвигается")
    folder = backlog_dir(repo)
    it = resolve(folder, ref)
    promt, sub = folder / f"promt-{it['theme']}.md", folder / it["theme"]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", str(promt), str(sub)], cwd=repo, capture_output=True,
                           text=True, encoding="utf-8", errors="replace").stdout.strip()
    links = links_to(repo, it)
    stop = []
    if dirty and not force:
        stop.append(f"у задачи незакоммиченные правки: закоммитить или --force\n{dirty}")
    if links and not ignore_links:
        stop.append(f"на файлы задачи ссылаются ({len(links)}) — поправить ссылки или удалить всё равно: --ignore-links\n"
                    + "\n".join(links))
    if stop:
        raise Fail("\n".join(stop))
    lines, _ = read_list(folder)
    kept = lines[:it["start"]] + lines[it["end"]:]
    write(folder / LIST_FILE, "\n".join(kept).rstrip("\n") + "\n")
    subprocess.run(["git", "rm", "-r", "-q", "-f", "--ignore-unmatch", str(promt), str(sub)], cwd=repo, capture_output=True)
    subprocess.run(["git", "add", "--", str(folder / LIST_FILE)], cwd=repo, capture_output=True)
    if promt.exists():
        promt.unlink()
    if sub.exists():
        shutil.rmtree(sub)
    left = [f"остались битые ссылки ({len(links)}):"] + links if links else []
    return [f"удалено: {promt.name}, {it['theme']}/, раздел списка"] + left


def added_lines(path: Path, repo: Path) -> set[int] | None:
    """Номера новых строк файла против HEAD; файла в HEAD нет или git нет — None: новый файл целиком."""
    rel = path.relative_to(repo).as_posix()
    known = subprocess.run(["git", "cat-file", "-e", f"HEAD:{rel}"], cwd=repo, capture_output=True)
    if known.returncode != 0:
        return None
    res = subprocess.run(["git", "diff", "-U0", "HEAD", "--", rel], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out: set[int] = set()
    for m in re.finditer(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", res.stdout, re.M):
        start, count = int(m.group(1)), int(m.group(2) or 1)
        out.update(range(start, start + count))
    return out


def unmarked(path: Path, repo: Path) -> list[str]:
    """Страховка: новые строки требований без цитаты и пометки. Пункт без пометки считается согласованным, поэтому
    забытая пометка делает выдумку сессии решением: такие строки надо увидеть глазами."""
    fresh = added_lines(path, repo)
    rel = path.relative_to(repo).as_posix()
    out, head, parent_marked = [], None, False
    for no, line in enumerate(read_md(path), 1):
        if line.startswith("#"):
            head, parent_marked = (line.lstrip("# ").strip() if line.startswith("## ") else head), False
            continue
        text = line.strip()
        nested = line.startswith((" ", "\t"))
        marked = bool(REQ_MARK_RE.search(text))
        if not nested:
            parent_marked = marked
        if OLD_MARK_RE.search(text) and (fresh is None or no in fresh):
            out.append(f"{rel}:{no} — прежняя пометка: без пометки значит согласовано, вместо (предложено) — (не согласовано): {text[:70]}")
            continue
        if fresh is not None and no not in fresh:
            continue
        if (not text or head is None or head.startswith(NOT_REQUIREMENTS) or text.lower().startswith(SERVICE_LINES)
                or text.endswith(":") or BLANK in text or marked or QUOTE_RE.search(text) or (nested and parent_marked)):
            continue
        out.append(f"{rel}:{no} — без цитаты и пометки: {text[:90]}")
    return out


def loose_ends(path: Path, repo: Path) -> list[str]:
    """Незаполненные места шаблона и ссылки на файлы, которых нет: удалённая задача, ненарисованный макет."""
    rel = path.relative_to(repo).as_posix()
    out = []
    for no, line in enumerate(read_md(path), 1):
        if BLANK in line:
            out.append(f"{rel}:{no} — не заполнено: {line.strip()[:70]}")
        for target in LINK_RE.findall(line):
            if not target.startswith(("http:", "https:", "mailto:", "/")) and not (path.parent / target).exists():
                out.append(f"{rel}:{no} — ссылка ведёт в никуда: {target}")
    return out


def check(repo: Path, ref: str | None) -> tuple[list[str], list[str]]:
    """Ошибки — разошлись промт, папка и список; предупреждения — страховка пометок."""
    folder = backlog_dir(repo)
    _, items = read_list(folder)
    errors, warnings = [], []
    themes = [x["theme"] for x in items]
    if ref:
        themes = [resolve(folder, ref)["theme"]]
    else:
        listed = set(themes)
        for p in sorted(folder.glob("promt-*.md")):
            if p.stem[6:] not in listed:
                errors.append(f"{p.name}: нет в списке {LIST_FILE}")
        for sub in sorted(x for x in folder.iterdir() if x.is_dir() and not x.name.startswith((".", "_"))) if folder.is_dir() else []:
            if not (folder / f"promt-{sub.name}.md").is_file():
                errors.append(f"{sub.name}/: папка без промта")
    for theme in themes:
        if not (folder / f"promt-{theme}.md").is_file():
            errors.append(f"{theme}: в списке есть, а promt-{theme}.md нет")
        if not (folder / theme).is_dir():
            errors.append(f"{theme}: нет папки {theme}/")
        for it in items:
            if it["theme"] == theme and any(BLANK in x for x in it["body"]):
                warnings.append(f"{LIST_FILE}, раздел {theme}: не заполнен")
        for p in task_files(folder, theme):
            warnings += loose_ends(p, repo)
            if p.name != "CHECK.md":  # файл проверки — команды и ожидаемые числа, а не требования
                warnings += unmarked(p, repo)
    return errors, warnings


def selftest() -> int:
    """Весь путь задачи во временном репо: новая, остаток, страховка, в работу, удалить, расхождения мест."""
    bad: list[str] = []

    def want(cond: bool, what: str) -> None:
        if not cond:
            bad.append(what)

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=repo, capture_output=True)
        folder = repo / DEFAULT_DIR
        new(repo, "demo", "Показ дней")
        promt = folder / "promt-demo.md"
        want(promt.is_file() and (folder / "demo" / ".gitkeep").is_file(), "new: нет промта или .gitkeep")
        want("Показ дней" in show_list(folder)[1] and show_list(folder)[1].startswith("1. "), f"список: {show_list(folder)}")
        fresh = progress(folder, "demo")
        want(fresh["current"] == 0 and not fresh["done"][4], f"свежая задача: шаг {fresh['current']}, готова {fresh['done'][4]}")
        want(resolve(folder, "1")["theme"] == resolve(folder, "demo")["theme"], "номер и тема дали разное")

        text = promt.read_text(encoding="utf-8")
        for name, body in (
            ("Что хотим", "Видеть дни рядом."),
            ("Кто и что должен уметь", "- (не согласовано) Как покупатель вижу дни.\n- (открыто) **Сколько дней**\n  - 30. Цена: мало."),
            ("Критерии приёмки", "- Дни видны, Анна: «вот так»."),
        ):
            text = re.sub(rf"(## {name}\n\n)<заполнить[^\n]*", lambda m, b=body: m.group(1) + b, text)
        write(promt, text)
        p = progress(folder, "demo")
        want(p["current"] == 1 and p["unagreed"] == 1 and p["open"] == 1, f"остаток при вопросах: {p['current']} {counts(p)}")
        status = "\n".join(show_status(folder, resolve(folder, "demo")))
        want("шаг 2 из 5" in status and "⬜ 5." in status and "Можно остановиться" in status and "вопросов к решающему нет" not in status, f"status: {status}")
        answered = text.replace("(не согласовано) Как покупатель", "Как покупатель, Анна: «вижу дни», ").replace("- (открыто) **Сколько дней**\n  - 30. Цена: мало.", "- 30 дней, выбрал «30»")
        write(promt, answered)
        p = progress(folder, "demo")
        want(p["current"] == 2 and p["unagreed"] == 0 and p["open"] == 0, f"остаток после ответов: {p['current']} {counts(p)}")

        lines = (text.rstrip("\n") + "\n\n## Лишнее\n\n- Выдумка сессии без пометки\n- (предложено) По-старому\n- Его слова: «да»\n"
                 "- Кнопка «Скачать» справа\nничего\nне нужен\n- [старое](promt-gone.md)\n")
        write(promt, lines)
        warn = check(repo, "demo")[1]
        want(any("Выдумка" in x for x in warn), f"страховка не поймала выдумку: {warn}")
        want(any("прежняя пометка" in x and "По-старому" in x for x in warn), f"страховка не поймала старую пометку: {warn}")
        want(not any("вот так" in x or "Его слова" in x or "Сколько дней" in x or "30. Цена" in x or "ничего" in x or "не нужен" in x for x in warn), f"лишнее в страховке: {warn}")
        want(any("Кнопка" in x for x in warn), f"короткие кавычки приняты за цитату: {warn}")
        want(any("в никуда: promt-gone.md" in x for x in warn), f"битая ссылка не поймана: {warn}")
        want(any("не заполнено" in x for x in warn), f"незаполненное не показано: {warn}")

        subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], cwd=repo, capture_output=True)
        want(not any("Выдумка" in x for x in check(repo, "demo")[1]), "страховка показала строку из коммита")

        new(repo, "more", "Что дальше", parent="demo")
        tobe = folder / "promt-tobe-more.md"
        want(tobe.is_file() and "Что надо будет сделать" in tobe.read_text(encoding="utf-8"), "new --tobe: не короткий промт")
        want(progress(folder, "tobe-more")["current"] == 0, "короткий промт — не на шаге 1")
        want(resolve(folder, "more")["theme"] == "tobe-more", "короткий промт не находится по названной теме")
        take(repo, "demo", "change/demo")
        want(any("в работе: ветка `change/demo`" in x for x in resolve(folder, "demo")["body"]), "take не записал")
        want(any("в работе" in x for x in show_list(folder)), "список не показал «в работе»")
        want(ensure(repo, "demo", "Показ дней")[0][0].endswith("promt-demo.md"), "ensure не нашёл задачу")
        want((folder / "promt-fresh.md").exists() is False and ensure(repo, "fresh", "Новое")[0][1].endswith("fresh/") and (folder / "promt-fresh.md").is_file(), "ensure не завёл задачу")

        (folder / "orphan").mkdir()
        write(folder / "promt-lost.md", "# Задача: потеряна\n")
        errs = check(repo, None)[0]
        want(any("orphan/" in x for x in errs) and any("promt-lost" in x for x in errs), f"расхождения не пойманы: {errs}")
        (folder / "orphan").rmdir()
        (folder / "promt-lost.md").unlink()

        try:
            drop(repo, "1")
            bad.append("drop по номеру: нет ошибки")
        except Fail:
            pass
        more = folder / "promt-tobe-more.md"
        write(more, more.read_text(encoding="utf-8") + "\nСм. [`promt-demo.md`](promt-demo.md#что-хотим) и [макет](demo/m.md).\n"
              "`promt-demo.md` (задача сделана) и [сайт](https://x/promt-demo.md).\n")
        write(folder / "demo" / "m.md", "[назад](../promt-demo.md)\n")  # своя ссылка задачи уходит вместе с ней
        asis = repo / TOOLS.parent.name / "ASIS" / "svc"
        asis.mkdir(parents=True)
        write(asis / "README.md", "# svc\n\nТребования — [задача](../../../_backlog/demo/).\nИ [от корня](/_backlog/promt-demo.md).\n"
              "```\n[в коде](../../../_backlog/demo/)\n```\n")
        refs = links_to(repo, resolve(folder, "demo"))
        want(len(refs) == 3 and sum(x.startswith("_backlog/promt-tobe-more.md:") for x in refs) == 1
             and f"{TOOLS.parent.name}/ASIS/svc/README.md:3 — ссылка на ../../../_backlog/demo/" in refs
             and "_backlog/promt-tobe-more.md:17 — ссылка на promt-demo.md, demo/m.md" in refs
             and any(x.startswith(f"{TOOLS.parent.name}/ASIS/svc/README.md:4 ") for x in refs), f"ссылки на задачу: {refs}")
        try:
            drop(repo, "demo", force=True)
            bad.append("drop удалил задачу, на которую ссылаются")
        except Fail as e:
            want("--ignore-links" in str(e) and "README.md:3" in str(e), f"drop при ссылках: {e}")
        want(promt.exists() and (folder / "demo").is_dir(), "drop при ссылках всё-таки удалил файлы")
        write(promt, promt.read_text(encoding="utf-8") + "\nправка\n")
        try:
            drop(repo, "demo")
            bad.append("drop потерял незакоммиченную правку")
        except Fail as e:
            want("--force" in str(e), f"drop: {e}")
        gone = drop(repo, "demo", force=True, ignore_links=True)
        want("остались битые ссылки (3):" in gone, f"drop --ignore-links не назвал оставшиеся ссылки: {gone}")
        want("CLAUDE.md" not in subprocess.run(["git", "diff", "--name-only"], cwd=repo, capture_output=True, text=True).stdout, "drop оставил список вне индекса")
        want(not promt.exists() and not (folder / "demo").exists(), "drop оставил файлы")
        want("demo" not in [x["theme"] for x in read_list(folder)[1]], "drop оставил раздел")
        want(not check(repo, None)[0], f"после drop расхождения: {check(repo, None)[0]}")
        for call, args in ((new, (repo, "Плохая Тема", "x")), (resolve, (folder, "99"))):
            try:
                call(*args)
                bad.append(f"{call.__name__}: нет ошибки на {args[-1]}")
            except Fail:
                pass
    for x in bad:
        print(f"ошибка самопроверки: {x}")
    if bad:
        return 1
    print("Самопроверка: всё сходится.")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Бэклог: список, новая задача, остаток, проверка (шапка файла — подробно).")
    ap.add_argument("command", nargs="?", choices=("new", "status", "check", "take", "drop"))
    ap.add_argument("args", nargs="*")
    ap.add_argument("--tobe", metavar="РОДИТЕЛЬ")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--ignore-links", action="store_true")
    ap.add_argument("--repo", type=Path, default=TOOLS.parents[1])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    repo = a.repo.resolve()
    folder = backlog_dir(repo)
    need = {"new": 2, "status": 1, "take": 2, "drop": 1}
    if a.command in need and len(a.args) != need[a.command]:
        print(f"{a.command}: нужно аргументов — {need[a.command]}", file=sys.stderr)
        return 2
    try:
        if a.command is None:
            print("\n".join(show_list(folder)))
        elif a.command == "new":
            print("\n".join(new(repo, a.args[0], a.args[1], a.tobe)))
        elif a.command == "status":
            print("\n".join(show_status(folder, resolve(folder, a.args[0]))))
        elif a.command == "take":
            print("\n".join(take(repo, a.args[0], a.args[1])))
        elif a.command == "drop":
            print("\n".join(drop(repo, a.args[0], a.force, a.ignore_links)))
        else:
            errors, warnings = check(repo, a.args[0] if a.args else None)
            for x in errors:
                print(f"ошибка: {x}")
            for x in warnings:
                print(f"предупреждение: {x}")
            if not errors and not warnings:
                print("Сходится: промты, папки, список; новых строк без цитаты и пометки нет.")
            return 1 if errors else 0
    except Fail as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
