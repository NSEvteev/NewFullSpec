"""Где мы в изменении: шаг процесса, блоки, ветка и PR, вопросы к тому, кто решает, что дальше; ворота шагов.

Зачем. Шаг изменения узнаётся по признакам в файлах и git, а не по памяти сессии: обложка «как будет» есть ли,
утверждено ли описание, у каких блоков стоит «Сделано:», слито ли в origin/main. Скилл процесса зовёт эту команду
первой и сверяет её вывод с путеводителем CHANGELOG.md. Ворота — места, где шаг начинается только при условии:
--gate отвечает кодом выхода, открыты ли они, и называет причину.

Кто зовёт. Скилл /dev — в начале каждой сессии; шаги процесса — ворота перед началом. Из корня репо, из Bash:
  python <карта>/tools/where.py                  где мы: изменение, шаги ✅ ▶ ⬜, блоки, ветка и PR, вопросы, дальше
  python <карта>/tools/where.py --gate ready     описание готово к «да»: нет «открыто», «предложено», узлов open,
                                                 «как будет» без ошибок
  python <карта>/tools/where.py --gate approved  описание утверждено: на обложке «Описание утверждено:» с датой,
                                                 коммитом и словами в «», и с тех пор нет «открыто» и «предложено»
  python <карта>/tools/where.py --gate blocks-done   у каждого блока работ есть «Сделано:»
  python <карта>/tools/where.py --gate done      done.py — сделано N из N
  python <карта>/tools/where.py --gate start     старт можно начинать: изменения нет, стою на main, main = origin/main,
                                                 live.py — 0 ошибок; незакоммиченное только называется
  python <карта>/tools/where.py --guide          где мы и что делать: что делать при предупреждении, нужно ли слово
                                                 того, кто решает, что читать к шагу, полон ли журнал
  python <карта>/tools/where.py --read <шаг>     что прочитать к шагу: dev (новая сессия), dev-start, dev-describe, …
  python <карта>/tools/where.py --why <шаг>      почему шаг устроен так: его раздел PROCESS-WHY.md
  … --no-facts      у --gate start: live.py без живого окружения
  … --no-git        не ходить в git и gh: признаки только из рабочей копии (проверочные карты, тесты)
  … --root <карта>  другая карта
Шаг узнаётся по признакам по порядку, первый подошедший:
  в TOBE/ есть файлы, а обложки нет        — ошибка
  обложки нет                              — изменения нет; задачу выбирает решающий, список — backlog.py
  обложка есть, правок и blocks.md нет     — старт, если в наборе требований (поле «Требования:» обложки) есть
                                             пункт «(открыто)»; иначе — описание: описать изменение
  нет «Описание утверждено:»               — описание; есть «открыто» или «предложено» — ждём того, кто решает
Вопросы к тому, кто решает: пункты набора требований с пометкой «(открыто)» или «(не согласовано)» — с якорем d-… или
без него (тогда — файл:строка), правки «как будет» с такими статусами, узлы доски open.
  утверждено, но есть «открыто»/«предложено» — описание (дописать): ждём «да» на новое
  утверждено, есть блок без «Сделано:»     — блок: первый, у которого блоки из «После:» сделаны
  все блоки сделаны в ветке, не в origin/main — доставка
  все блоки сделаны в origin/main          — закрытие
Блоки читаются из ветки изменения (поле «Ветка:» обложки, git show <ветка>:…/blocks.md), а не из рабочей копии:
сессия может стоять на main. Ветки нет — из рабочей копии, с предупреждением (если не все блоки сделаны); --no-git — из
рабочей копии молча. Ветка, чей PR слит (gh), — не «неслитая работа»: squash-merge не делает её слитой для git. Перед сравнением с
origin/main — git fetch, ожидание до 5 с; PR — через gh, ожидание до 5 с; не вышло — «не узнать (почему)».
Особые состояния — предупреждением: неотправленные коммиты в main; несколько неслитых веток change/…; «как будет»
пусто, а в ветке change/… неслитая работа; обложки нет, а в «как есть» остались «:::» или [[c-…; поле обложки
«Размер: маленькое» при большем объёме. Поле «Размер:» — строкой вывода, только если оно есть на обложке.

Что читает. Карту (mapmodel.py: ChangeModel — обложка, правки, блоки; статусы и кто решает — project/settings.yaml),
git и gh. Ничего не пишет.

Коды выхода: где мы — 0, ошибка состояния — 2; --gate — 0 открыты, 1 закрыты; 2 — ошибка ввода или карты.

Чего не делает. Не правит CHANGELOG.md и обложку — это скиллы процесса. Не решает за человека: показывает вопросы.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tobe_checks  # noqa: E402
from mapmodel import (  # noqa: E402
    WORK_FIELDS,
    ChangeModel,
    MapModel,
    _fields_text,
    _simple_sections,
    keys_in,
)

STEPS = ("старт", "описание", "блок", "доставка", "закрытие")
NEXT = {
    "старт": "/dev-start",
    "описание": "/dev-describe",
    "блок": "/dev-block",
    "доставка": "/dev-deliver",
    "закрытие": "/dev-close",
}
APPROVED_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s*·\s*([0-9a-f]{7,40})\s*·\s*«.+»\s*$")
PROCESS = "PROCESS.md"
WHY = "PROCESS-WHY.md"
SIZE_SMALL = "маленькое"
SMALL_OFF = "без агентов и ревьюеров, без новичков и сверки полноты, без вопроса «начинаем?»"
SMALL_SERVICES, SMALL_BLOCKS = 1, 2
JOURNAL_LIMIT = 5
# Что прочитать к шагу. Шаг отсюда и узнаёт свой вход: скилл зовёт --read, а не держит список у себя. {map} — папка
# карты от корня репо.
READ = {
    "dev": (
        "{map}/" + PROCESS + " — целиком",
        "{map}/CLAUDE.md — «Что где лежит», «Где искать что», «Как читать md карты»; идёт изменение — и «Как читать «как будет»»",
        "PROJECT.md — целиком",
        "CHANGELOG.md — где мы; _backlog/CLAUDE.md — бэклог",
        "память Claude — записи из PROJECT.md, «Память к чтению»",
    ),
    "dev-start": (
        "{map}/JOURNAL.md — неразобранные записи",
        ".claude/skills/backlog/format.md — формат задачи и пометки",
        "{map}/STANDARD.md — 7.6, обложка",
    ),
    "dev-describe": (
        "{map}/STANDARD.md — раздел 7",
        "{map}/CLAUDE.md — «Как читать «как будет»»",
        "требования изменения — поле «Требования:» обложки, целиком",
    ),
    "dev-block": (
        "{map}/CLAUDE.md — «Как читать «как будет»»",
        "PROJECT.md — «Команды», «Живое окружение», «Снимки интерфейса»",
        "{map}/standards/code.md",
    ),
    "dev-deliver": (
        "PROJECT.md — «Как используется», «Команды», «Соседние репо», «CI»",
        "{map}/TOBE/README.md — решения; {map}/TOBE/blocks.md — блоки и их «Сделано:»",
    ),
    "dev-close": (
        "{map}/TOBE/README.md — решения, «Не задеты», «Судьбы проблем», «Последствия для процессов», «PR:»",
        "{map}/STANDARD.md — разделы 1–6, если придётся писать md",
        "PROJECT.md — «Живое окружение», «Мёртвый код», «Соседние репо»",
    ),
}
# Что делать при особом состоянии: образец в тексте предупреждения → действие.
ADVICE = (
    ("неотправленных коммитов", "старту и описанию не мешают; до ветки изменения и до PR — отправить или спросить"),
    ("несколько неслитых веток", "показать и спросить; ветку не переключать"),
    ("неслитая работа", "git show <ветка>:<карта>/TOBE/README.md: обложка есть — перейти на эту ветку; нет — показать и спросить"),
    ("закрытие не доделано", "/dev-close — доделать, а не начинать новое"),
    ("блоки из рабочей копии", "на описании до коммита blocks.md так и есть; посреди кода — выяснить: git branch --list 'change/*'"),
    ("git fetch не вышел", "работать дальше; слито ли — сверить перед доставкой и закрытием"),
    ("больше маленького", "сказать решающему и либо снять поле, либо оставить его словом решающего"),
)


class StateError(Exception):
    """Состояние, в котором шаг узнать нельзя: код выхода 2."""


def git(repo: Path, *args: str, timeout: int = 5) -> tuple[bool, str]:
    try:
        res = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return res.returncode == 0, (res.stdout if res.returncode == 0 else res.stderr).strip()


def gh(repo: Path, *args: str, timeout: int = 5) -> tuple[bool, str]:
    try:
        res = subprocess.run(
            ["gh", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return res.returncode == 0, (res.stdout if res.returncode == 0 else res.stderr).strip()


def parse_blocks(text: str) -> list[dict]:
    """Блоки работ из текста blocks.md: якорь, заголовок, поля «Где», «Задачи», «После», «Готово, когда», «Сделано»."""
    _, secs = _simple_sections(text.split("\n"))
    out = []
    for s in secs:
        if s["level"] == 2 and s["anchor"]:
            f, t = _fields_text(s["body"], WORK_FIELDS)
            out.append({"anchor": s["anchor"], "title": s["title"], "text": t, **f})
    return out


class Where:
    def __init__(self, root: Path, use_git: bool):
        self.root = root.resolve()
        self.repo = self.root.parent
        self.use_git = use_git
        self.warnings: list[str] = []
        self.asis = MapModel(self.root)
        self.chg = ChangeModel(self.root, self.asis)
        self.maprel = self.root.relative_to(self.repo).as_posix()
        statuses = self.asis.settings.get("statuses") or []
        self.weak = set(statuses[2:])  # «предложено», «открыто» — слабее решений
        self.decider = (self.asis.settings.get("decider") or {}).get("to") or "человеку"
        tobe = self.root / "TOBE"
        files = [p for p in tobe.rglob("*") if p.is_file() and p.name != ".gitkeep"] if tobe.is_dir() else []
        if files and not self.chg.open:
            raise StateError("в TOBE/ есть файлы, а обложки TOBE/README.md нет — «как будет» без обложки")

    # признаки -------------------------------------------------------------------------------------

    def branch(self) -> str:
        return str(self.chg.cover.get("Ветка") or "").strip("` ")

    def blocks(self) -> list[dict]:
        local = self.root / "TOBE" / "blocks.md"
        br = self.branch()
        if self.use_git and br:
            ok, text = git(self.repo, "show", f"{br}:{self.maprel}/TOBE/blocks.md")
            if ok:
                return parse_blocks(text)
            local_blocks = parse_blocks(local.read_text(encoding="utf-8")) if local.is_file() else []
            # слитую ветку доставка удаляет: блоки, все сделанные, — уже в рабочей копии main, это не тревога
            if not (local_blocks and all(b.get("Сделано") for b in local_blocks)):
                self.warnings.append(f"ветки {br} нет или в ней нет blocks.md — блоки из рабочей копии")
            return local_blocks
        elif not self.use_git and local.is_file():
            pass
        return parse_blocks(local.read_text(encoding="utf-8")) if local.is_file() else []

    def merged_blocks(self) -> list[dict] | None:
        """Блоки в origin/main; None — не узнать."""
        if not self.use_git:
            return None
        ok, err = git(self.repo, "fetch", "origin", "main", "--quiet")
        if not ok:
            self.warnings.append(f"git fetch не вышел за 5 с ({err[:80]}) — сравнение с origin/main по старой копии")
        ok, text = git(self.repo, "show", f"origin/main:{self.maprel}/TOBE/blocks.md")
        return parse_blocks(text) if ok else []

    def questions(self) -> list[str]:
        """Пункты требований и правки со статусом «открыто» или «предложено», узлы доски open. Пункт требований —
        якорем d-…, а без якоря — местом в файле: «открыто» без якоря тоже вопрос."""
        out = [f"{w['anchor'] or w['file'] + ':' + str(w['line'])} ({w['status']})" for w in self.chg.req_weak]
        out += [f"{b.number} ({b.status})" for b in self.chg.blocks if b.status in self.weak]
        out += [f"узел {n} (open)" for n, v in (self.chg.board or {}).items() if (v or {}).get("status") == "open"]
        return out

    def approved(self) -> str:
        return str(self.chg.cover.get("Описание утверждено") or "").strip()

    def size(self) -> str:
        return str(self.chg.cover.get("Размер") or "").strip().lower()

    def journal_records(self) -> int:
        """Сколько неразобранных записей в журнале: разделы «### …»."""
        p = self.root / "JOURNAL.md"
        return sum(x.startswith("### ") for x in p.read_text(encoding="utf-8").splitlines()) if p.is_file() else 0

    def word_needed(self, step: str, info: dict) -> str:
        """Нужно ли для перехода слово того, кто решает."""
        small = self.size() == SIZE_SMALL
        if step == "нет":
            return "нужно: задача должна быть названа; не названа — показать список backlog.py и спросить"
        if info.get("blank"):
            return "не нужно: заполнить обложку и требования"
        if step == "старт" or info["questions"]:
            return "нужно: ответы на вопросы выше"
        if step == "описание" and not info.get("described"):
            return "не нужно: сначала описать"
        if step == "описание" and not self.approved():
            return "не нужно: у маленькой доработки «да» — слова со старта" if small else "нужно: «да» на описание и блоки"
        if step == "доставка":
            return "не нужно; внутри шага — что чинить по ревью и чужие коммиты в ветке"
        return "не нужно: порядок утверждён с описанием"

    def guide(self) -> list[str]:
        """«Где мы» и что с этим делать: всё, что скилл /dev иначе держал бы таблицами."""
        out = self.report()
        step, info = self.last
        if any("не узнать" in x for x in out):
            out.append("что делать: работать дальше; PR понадобится только доставке и закрытию")
        for w in self.warnings:
            out.append(f"предупреждение: {w}")
            out += [f"что делать: {text}" for sample, text in ADVICE if sample in w]
        out.append(f"Слово {self.decider}: {self.word_needed(step, info)}")
        skill = "dev-start" if step == "нет" else NEXT[step].lstrip("/")
        out.append(f"Читать к шагу: python {self.maprel}/tools/where.py --read {skill}; новая сессия — ещё --read dev")
        n = self.journal_records()
        if n >= JOURNAL_LIMIT:
            out.append(f"В журнале неразобранных записей: {n} — предложить сессию разбора ({PROCESS}, раздел 12)")
        return out

    def read_list(self, step: str) -> list[str]:
        step = step.lstrip("/")
        if step not in READ:
            raise StateError(f"нет шага «{step}»: {', '.join(READ)}")
        return [x.format(map=self.maprel) for x in READ[step]]

    def why(self, step: str) -> list[str]:
        """Раздел шага из PROCESS-WHY.md: от «## /<шаг>» до следующего такого заголовка."""
        head = "## /" + step.lstrip("/")
        p = self.root / WHY
        if not p.is_file():
            raise StateError(f"{WHY} нет")
        out: list[str] = []
        inside = False
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                inside = line.strip() == head
            if inside:
                out.append(line)
        if not out:
            raise StateError(f"в {WHY} нет раздела «{head}»")
        return out

    def gate_start(self, facts: bool) -> tuple[bool, str]:
        """Можно ли начинать старт: всё, что /dev-start иначе собирал бы несколькими командами."""
        step, _ = self.step()
        checks: list[str] = []
        ok = True
        if step == "нет":
            checks.append("изменения нет")
        elif step == "старт":
            checks.append("старт уже идёт: ждём ответа на открытые вопросы")
        else:
            ok = False
            checks.append(f"СТОП: идёт шаг «{step}» — это не старт: вернуться в /dev")
        if self.use_git:
            done, err = git(self.repo, "fetch", "origin", "main", "--quiet")
            if not done:
                checks.append(f"git fetch не вышел ({err[:60]})")
            _, branch = git(self.repo, "branch", "--show-current")
            if step == "нет" and branch != "main":
                ok = False
                checks.append(f"СТОП: стою на {branch or 'отдельном коммите'}, а нужно на main")
            _, ahead = git(self.repo, "rev-list", "--count", "origin/main..main")
            _, behind = git(self.repo, "rev-list", "--count", "main..origin/main")
            mark = ""
            if ahead.strip() not in ("", "0") or behind.strip() not in ("", "0"):
                ok = False
                mark = "СТОП: "
            checks.append(f"{mark}не отправлено {ahead.strip() or '?'}, не забрано {behind.strip() or '?'}")
            _, dirty = git(self.repo, "status", "--porcelain")
            names = [x.split(None, 1)[-1] for x in dirty.splitlines() if x.strip()]  # git() срезает пробел первой строки
            checks.append(f"незакоммичено {len(names)}" + (f": {', '.join(names[:5])}" if names else ""))
        live = Path(__file__).resolve().parent / "live.py"
        res = subprocess.run(
            [sys.executable, str(live), "--root", str(self.root), *([] if facts else ["--no-facts"])],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        found = [x for x in res.stdout.strip().splitlines() if x.strip()]
        if res.returncode == 0:
            checks.append("живая проверка: 0 ошибок" + ("" if facts else " (факты не сверены)"))
        else:
            ok = False
            checks.append("СТОП: живая проверка: " + "; ".join(found[:5]) if found else "СТОП: живая проверка не вышла")
        return ok, "; ".join(checks)

    def pr_merged(self, branch: str) -> bool:
        ok, out = gh(self.repo, "pr", "list", "--head", branch, "--state", "merged", "--json", "number")
        return ok and out.strip() not in ("", "[]")

    def special_states(self) -> None:
        if not self.use_git:
            return
        ok, n = git(self.repo, "rev-list", "--count", "origin/main..main")
        if ok and n.strip() not in ("", "0"):
            self.warnings.append(f"в main неотправленных коммитов: {n.strip()}")
        ok, out = git(self.repo, "branch", "--list", "change/*", "--no-merged", "origin/main")
        unmerged = [b.strip(" *+") for b in out.splitlines() if b.strip()] if ok else []
        # squash-merge не делает ветку слитой для git: ветка, чей PR слит, — не «неслитая работа»
        unmerged = [b for b in unmerged if not self.pr_merged(b)]
        if len(unmerged) > 1:
            self.warnings.append(f"несколько неслитых веток изменений: {', '.join(unmerged)}")
        if not self.chg.open and unmerged:
            self.warnings.append(f"«как будет» пусто, а в ветке {unmerged[0]} неслитая работа — разобрать")
        if not self.chg.open:
            left = [
                rel for rel in self.asis.files
                if re.search(r"^:::|\[\[[cdkt]-", (self.root / rel).read_text(encoding="utf-8"), re.M)
            ]
            if left:
                self.warnings.append(f"обложки нет, а в «как есть» остались пометки «как будет»: {left[0]} — закрытие не доделано")

    # шаг ------------------------------------------------------------------------------------------

    def step(self) -> tuple[str, dict]:
        """Шаг и подробности: блоки, текущий блок, вопросы."""
        info: dict = {"blocks": [], "current": None, "questions": self.questions()}
        if not self.chg.open:
            return "нет", info
        has_changes = bool(self.chg.blocks) or (self.root / "TOBE" / "blocks.md").is_file()
        info["described"] = has_changes
        if not has_changes:
            cover = self.root / "TOBE" / "README.md"
            if "<что сейчас не так" in cover.read_text(encoding="utf-8"):  # map.py start положил шаблон, его не заполнили
                info["blank"] = True
                return "старт", info
            # старт решает развилки в требованиях: пункт «открыто» там — старт ещё ждёт ответа
            open_word = (self.asis.settings.get("statuses") or [""])[-1]
            if any(w["status"] == open_word for w in self.chg.req_weak):
                return "старт", info
            return "описание", info
        if not self.approved() or info["questions"]:
            return "описание", info
        blocks = self.blocks()
        info["blocks"] = blocks
        done = {b["anchor"] for b in blocks if b.get("Сделано")}
        for b in blocks:
            if b["anchor"] in done:
                continue
            after = {k for k in keys_in(b.get("После", []))}
            if after <= done:
                info["current"] = b["anchor"]
                break
        if len(done) < len(blocks):
            return "блок", info
        merged = self.merged_blocks()
        if merged is not None and merged and all(b.get("Сделано") for b in merged):
            return "закрытие", info
        return "доставка", info

    def report(self) -> list[str]:
        step, info = self.step()
        self.last = (step, info)
        self.special_states()
        out: list[str] = []
        if step == "нет":
            out.append("Изменения нет")
            out.append(f"Дальше: задачу выбирает решающий; список — python {self.maprel}/tools/backlog.py")
            return out
        ap = self.approved()
        state = (
            f"описание утверждено {ap.split('·')[0].strip()}" if ap and not info["questions"]
            else "описание утверждено, есть новое без «да»" if ap
            else "описание не утверждено"
        )
        out.append(f"Изменение: «{self.chg.title}» — {state}")
        i = STEPS.index(step)
        out.append("Шаги: " + " · ".join(
            f"{'✅' if k < i else '▶' if k == i else '⬜'} {s}" for k, s in enumerate(STEPS)
        ))
        blocks = info["blocks"] or (self.blocks() if step in ("старт", "описание") else [])
        if blocks:
            out.append("Блоки: " + " · ".join(
                f"Б{b['anchor'][1:]} " + ("✅" if b.get("Сделано") else "▶" if b["anchor"] == info["current"] else "⬜")
                for b in blocks
            ))
        br = self.branch() or "—"
        pr = str(self.chg.cover.get("PR") or "").strip()
        if not pr and self.use_git and self.branch():
            ok, outp = gh(self.repo, "pr", "list", "--head", self.branch(), "--state", "all", "--json", "number,state")
            pr = (outp if ok and outp not in ("", "[]") else "нет") if ok else f"не узнать ({outp[:60]})"
        out.append(f"Ветка: {br} · PR: {pr or 'нет'}")
        size = self.size()
        if size:
            out.append(f"Размер: {size}" + (f" — {SMALL_OFF} ({PROCESS}, раздел 1)" if size == SIZE_SMALL else ""))
        n_services = len(self.chg.services())
        if size == SIZE_SMALL and (n_services > SMALL_SERVICES or len(blocks) > SMALL_BLOCKS):
            self.warnings.append(f"сервисов {n_services}, блоков {len(blocks)} — больше маленького")
        q = info["questions"]
        out.append(f"Вопросы к {self.decider}: " + (f"{len(q)} — " + ", ".join(q) if q else "нет"))
        if info.get("blank"):
            nxt = "/dev-start — обложка из шаблона не заполнена"
        elif step == "старт":
            nxt = f"/dev-start — ждём ответа на открытые вопросы к {self.decider}"
        elif step == "описание" and not info.get("described"):
            nxt = "/dev-describe — описать изменение: решения на обложке"
        elif step == "описание":
            nxt = "/dev-describe" + (f" — ждём ответа на вопросы к {self.decider}" if q else " — показать и ждать «да»")
        elif step == "блок":
            nxt = f"/dev-block {info['current'] or '?'}"
        else:
            nxt = NEXT[step]
        out.append(f"Дальше: {nxt}")
        return out

    # ворота ---------------------------------------------------------------------------------------

    def gate(self, name: str, facts: bool = True) -> tuple[bool, str]:
        if name == "start":
            return self.gate_start(facts)
        if not self.chg.open:
            return False, "изменения нет: обложки TOBE/README.md нет"
        q = self.questions()
        if name == "ready":
            if not self.chg.blocks and not self.chg.work:
                return False, "описания ещё нет: ни правок, ни блоков работ"
            errs = self.chg.errors + (self.chg.world.errors if self.chg.world else []) + tobe_checks.run(self.asis, self.chg).errors
            if q:
                tail = f"; ещё в «как будет» ошибок: {len(errs)}; первая — {errs[0]}" if errs else ""
                return False, f"есть вопросы к {self.decider}: {', '.join(q)}{tail}"
            if errs:
                return False, f"в «как будет» ошибок: {len(errs)}; первая — {errs[0]}"
            return True, "описание готово к «да»"
        if name == "approved":
            ap = self.approved()
            if not ap:
                return False, "на обложке нет «Описание утверждено:»"
            if not APPROVED_RE.match(ap):
                return False, f"«Описание утверждено: {ap}» — нужно «<дата> · <коммит> · «<слова>»»"
            if q:
                return False, f"после «да» появилось без «да»: {', '.join(q)}"
            return True, f"описание утверждено: {ap}"
        if name == "blocks-done":
            blocks = self.blocks()
            if not blocks:
                return False, "блоков работ нет"
            left = [b["anchor"] for b in blocks if not b.get("Сделано")]
            return (not left), (f"не сделаны: {', '.join(left)}" if left else "все блоки сделаны")
        if name == "done":
            done = Path(__file__).resolve().parent / "done.py"
            if not done.is_file():
                return False, "done.py нет"
            res = subprocess.run([sys.executable, str(done), "--root", str(self.root)], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace")
            last = (res.stdout.strip().splitlines() or [""])[-1]
            return res.returncode == 0, last
        raise StateError(f"нет ворот «{name}»: start, ready, approved, blocks-done, done")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="where.py", description="Где мы в изменении (шапка файла — подробно).")
    ap.add_argument("--gate")
    ap.add_argument("--guide", action="store_true")
    ap.add_argument("--read")
    ap.add_argument("--why")
    ap.add_argument("--no-facts", action="store_true")
    ap.add_argument("--no-git", action="store_true")
    ap.add_argument("--root")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else Path(__file__).resolve().parent.parent
    if not (root / "project" / "settings.yaml").is_file():
        print(f"ошибка: {root} — не корень карты (нет project/settings.yaml)", file=sys.stderr)
        return 2
    try:
        w = Where(root, not a.no_git)
        if a.read or a.why:
            print("\n".join(w.read_list(a.read) if a.read else w.why(a.why)))
            return 0
        if a.guide:
            print("\n".join(w.guide()))
            return 0
        if a.gate:
            ok, why = w.gate(a.gate, not a.no_facts)
            print(f"ворота {a.gate}: {'открыты' if ok else 'закрыты'} — {why}")
            for x in w.warnings:
                print(f"предупреждение: {x}", file=sys.stderr)
            return 0 if ok else 1
        print("\n".join(w.report()))
        for x in w.warnings:
            print(f"предупреждение: {x}")
        return 0
    except StateError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
