"""Хуки Claude Code для карты: что нельзя править руками, md карты — только через Edit и Write, после правки md —
его проверки и своя страница.

Зачем. Собранное (html, обзор системы, ключи поиска) и машинное (факты, запомненные строки) пишут только скрипты:
правка руками исчезнет при следующей сборке или соврёт. md карты правится только Edit и Write, чтобы после каждой
правки сработала проверка этого md. Хук держит оба правила, а после правки показывает пишущему ошибки его md, сломанные
ссылки на него, «ждёт пары» и новые ссылки на код с текстом строки.

Кто зовёт. Claude Code — по записям в .claude/settings.json:
  PreToolUse  Edit|Write|MultiEdit   python <карта>/tools/hook.py pre-edit
  PreToolUse  Bash|PowerShell        python <карта>/tools/hook.py pre-shell
  PostToolUse Edit|Write|MultiEdit   python <карта>/tools/hook.py post-edit
Хук получает на вход JSON Claude Code (tool_name, tool_input, cwd) и читает его как UTF-8.

Что такое «md карты». Корень карты — папка с project/settings.yaml; хук ищет её, поднимаясь от файла. md карты — все md
под корнем, кроме CLAUDE.md, PROCESS.md, PROCESS-WHY.md, STANDARD.md, KIT.md, PROJECT.md, JOURNAL.md, ASIS/README.md и папок
standards/ и tools/. Файл не под картой — хук молчит.

Что запрещено:
  до Edit или Write — html карты, ASIS/README.md, ASIS/keys.js, .facts.json, .anchors.json;
  до Bash или PowerShell — писать md карты: перенаправление > и >> в md, tee, sed -i, mv, rm, cp, git checkout -- <md>,
  git restore <md>; в PowerShell — Set-Content, Add-Content, Out-File, Remove-Item, Move-Item, Copy-Item, New-Item,
  их сокращения и [IO.File]::Write…. Каждая часть составной команды (после &&, ||, ;, |) — отдельно. Скрипты карты
  (build.py, map.py, relocate.py, extract.py) разрешены, если стоят отдельной частью команды.
  Встроенный Python (python -c, python - <<EOF) — запись в md карты: write_text, write_bytes, open(…) с режимом w, a,
  x или +, unlink, rename, os.remove/replace/rename, shutil.move/copy/rmtree. Куда пишет, хук видит по тексту: путь в
  вызове, а у имени — по его присваиванию и циклу for (до трёх шагов). Нельзя: цель — md карты; цель — папка карты
  или маска в ней (цикл for f in Path("…/TOBE").rglob(…) и запись в f, rmtree папки); цель не видна (sys.argv,
  input), а в тексте команды есть хоть один путь карты — даже только для чтения. Можно: запись в $S, os.environ,
  tempfile; файл с другим расширением, хоть и под картой (board.yaml, отчёт .txt); md, которые не md карты (PROCESS.md,
  папки tools/ и standards/); чтение карты.
После Edit или Write md карты — build.py <md> --own: ошибки md — кодом выхода 2 (так Claude Code показывает их
Claude); остальные списки — дополнительным контекстом; после project/*.yaml или TOBE/board.yaml — напоминание о сборке.

Коды выхода: 0 — можно / проверено; 2 — нельзя (до) или в md ошибки (после); ошибку разбора входа хук не глотает —
тоже 2 с сообщением.

Чего не видит. Скрипт, сохранённый через Write и запущенный потом, может записать md — хук этого не заметит; сторож
на этот случай — проверка при коммите (build.py --check --staged).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

NOT_MAP_FILES = {"CLAUDE.md", "PROCESS.md", "PROCESS-WHY.md", "STANDARD.md", "KIT.md", "PROJECT.md", "JOURNAL.md"}
NOT_MAP_DIRS = ("standards/", "tools/")
GENERATED = ("ASIS/README.md", "ASIS/keys.js")
MAP_SCRIPTS = re.compile(r"^\s*(?:\w+=\S*\s+)*(?:python3?|py)\s+\S*tools[/\\](?:build|map|relocate|extract)\.py\b")
SHELL_WRITE = re.compile(
    r"(?:^|\s)(?:tee|mv|rm|cp|del|sc|ac|ri|Set-Content|Add-Content|Out-File|Remove-Item|Move-Item|Copy-Item|New-Item)\b"
    r"|sed\s+(?:-\w*i|--in-place)|git\s+(?:checkout\s+--|restore)\b|\[IO\.File\]::Write",
    re.I,
)
MD_TOKEN = re.compile(r"""["']?([^\s"'<>|;&]+\.md)\b""")
INLINE_PY = re.compile(r"\b(?:python3?|py)(?:\.exe)?\s+(?:-[A-Za-z]+\s+)*(?:-c\b|-(?=\s|$)|<<)", re.M)
PY_METHOD_WRITE = re.compile(r"\.(write_text|write_bytes|unlink|rename|open)\s*\(")
PY_CALL_WRITE = re.compile(r"(?<![\w.])(open|io\.open|codecs\.open|os\.(?:remove|unlink|replace|rename)"
                           r"|shutil\.(?:move|copy\w*|rmtree))\s*\(")
PY_PATH = re.compile(r"[^\s\"'`(),;=<>|&\[\]{}]+")
PY_NAME = re.compile(r"[A-Za-z_]\w*")
OUTSIDE = re.compile(r"environ|getenv|tempfile|gettempdir|scratchpad|\$|%TEMP%", re.I)


def map_root(path: Path) -> Path | None:
    for p in [path, *path.parents]:
        if (p / "project" / "settings.yaml").is_file():
            return p
    return None


def norm(path: str, cwd: str | None) -> Path:
    p = Path(path)
    if not p.is_absolute() and cwd:
        p = Path(cwd) / p
    try:
        return p.resolve()
    except OSError:
        return p.absolute()


def classify(p: Path) -> tuple[Path | None, str, str]:
    """(корень карты, путь от корня, вид): вид — md (md карты), generated, machine, other."""
    root = map_root(p.parent)
    if not root:
        return None, "", "other"
    rel = p.relative_to(root).as_posix() if p.is_relative_to(root) else ""
    if not rel:
        return None, "", "other"
    if rel.endswith(".html") or rel in GENERATED:
        return root, rel, "generated"
    if p.name in (".facts.json", ".anchors.json"):
        return root, rel, "machine"
    if rel.endswith(".md") and p.name not in NOT_MAP_FILES and not rel.startswith(NOT_MAP_DIRS):
        return root, rel, "md"
    return root, rel, "other"


def deny(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 2


def pre_edit(data: dict) -> int:
    path = (data.get("tool_input") or {}).get("file_path")
    if not path:
        return 0
    root, rel, kind = classify(norm(path, data.get("cwd")))
    if kind == "generated":
        if rel == "ASIS/README.md":
            return deny(f"{rel} — обзор системы собирается из первых фраз README сервисов и процессов: правь их, затем build.py")
        return deny(f"{rel} — собирает генератор: правится md, страница соберётся сама")
    if kind == "machine":
        return deny(f"{rel} — машинный файл: факты вынимает extract.py, строки кода запоминает build.py")
    return 0


def _args(text: str, start: int) -> list[str]:
    """Аргументы вызова от start (за «(») до парной «)» — по запятым верхнего уровня, кавычки учтены."""
    args, cur, depth, quote, i = [], [], 0, "", start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                cur.append(text[i:i + 2])
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    args.append("".join(cur).strip())
    return [a for a in args if a]


def _receiver(text: str, end: int) -> str:
    """Выражение перед «.метод(», которое кончается на end: имена, точки и скобки подряд — Path("x").with_suffix(…)."""
    i = end
    while i > 0:
        ch = text[i - 1]
        if ch in ")]":
            depth, j = 0, i - 1
            while j >= 0:
                if text[j] in ")]":
                    depth += 1
                elif text[j] in "([":
                    depth -= 1
                    if depth == 0:
                        break
                j -= 1
            if j < 0:
                break
            i = j
        elif ch.isalnum() or ch in "_.":
            i -= 1
        else:
            break
    return text[i:end]


def _writes_mode(mode: str) -> bool:
    mode = mode.split("=", 1)[-1].strip().strip("\"'")
    return bool(re.fullmatch(r"[rwxabt+]+", mode)) and bool(re.search(r"[wax+]", mode))


def _write_targets(code: str) -> list[str]:
    """Куда пишет встроенный Python: выражения путей в вызовах записи, удаления и переноса."""
    targets: list[str] = []
    for m in PY_METHOD_WRITE.finditer(code):
        name, args = m.group(1), _args(code, m.end())
        receiver = _receiver(code, m.start())
        if not receiver or receiver in ("io", "codecs", "os"):
            continue  # io.open(…) — разберёт PY_CALL_WRITE
        if name == "open" and not (args and _writes_mode(next((a for a in args if a.startswith("mode")), args[0]))):
            continue
        targets.append(receiver)
        if name == "rename":
            targets += args[:1]
    for m in PY_CALL_WRITE.finditer(code):
        name, args = m.group(1), _args(code, m.end())
        if not args:
            continue
        if name.endswith("open"):
            mode = next((a for a in args if a.startswith("mode")), args[1] if len(args) > 1 and "=" not in args[1] else "")
            if _writes_mode(mode):
                targets.append(args[0])
        elif name.startswith("shutil.copy"):
            targets += args[1:2]
        elif name.endswith(("replace", "rename", "move")):
            targets += args[:2]
        else:
            targets.append(args[0])
    return targets


def _resolve(code: str, expr: str) -> str:
    """expr и правые части присваиваний и циклов for его имён — до трёх шагов: куда указывает p в p.write_text."""
    out, todo, seen = [expr], [expr], set()
    for _ in range(3):
        found = []
        for e in todo:
            for name in PY_NAME.findall(e):
                if name in seen:
                    continue
                seen.add(name)
                n = re.escape(name)
                for m in re.finditer(rf"(?:^|[;\n])\s*{n}\s*=(?!=)\s*([^;\n]+)"
                                     rf"|\bfor\s+(?:\w+\s*,\s*)*{n}(?:\s*,\s*\w+)*\s+in\s+([^:\n]+)", code):
                    found.append(m.group(1) or m.group(2))
        out += found
        todo = found
    return "\n".join(out)


def _where(token: str, cwd: str | None) -> str:
    """md — путь md карты; map — папка карты или маска в ней (кроме tools/, standards/); иначе пусто."""
    mask = any(c in token for c in "*?")
    p = norm(re.split(r"[*?]", token)[0] or ".", cwd)
    if not mask and p.suffix:
        return "md" if classify(p)[2] == "md" else ""
    root = map_root(p)
    if not root:
        return ""
    rel = "" if p == root else p.relative_to(root).as_posix() + "/"
    return "" if rel.startswith(NOT_MAP_DIRS) else "map"


def _paths(text: str) -> list[str]:
    return [t for t in PY_PATH.findall(text) if ("/" in t or "\\" in t or t.endswith(".md")) and not t.startswith(("$", "%"))]


def py_write_to_map(cmd: str, cwd: str | None) -> str | None:
    """Встроенный Python пишет md карты или в её папку — что и куда; иначе None. Правила — в шапке файла."""
    if not INLINE_PY.search(cmd):
        return None
    mentions_map = any(_where(t, cwd) for t in _paths(cmd))
    for target in _write_targets(cmd):
        if OUTSIDE.search(target):
            continue
        chain = _resolve(cmd, target)
        found = {t: _where(t, cwd) for t in _paths(chain)}
        md = [t for t, kind in found.items() if kind == "md"]
        if md:
            return f"пишет md карты {md[0]}"
        if OUTSIDE.search(chain):
            continue
        folder = [t for t, kind in found.items() if kind == "map"]
        if folder:
            return f"пишет в папку карты {folder[0]} ({target.strip()[:40]})"
        if not found and mentions_map:
            return f"пишет в {target.strip()[:40]} — куда, не видно, а скрипт трогает карту"
    return None


def pre_shell(data: dict) -> int:
    cmd = (data.get("tool_input") or {}).get("command") or ""
    cwd = data.get("cwd")
    if what := py_write_to_map(cmd, cwd):
        return deny(
            f"встроенный Python {what} — мимо проверки md и с CRLF: правь md карты через Edit или Write, удалить или "
            f"переименовать — map.py rm / map.py mv; читать карту и писать результат в $S — можно"
        )
    for part in re.split(r"&&|\|\||;|\|", cmd):
        if MAP_SCRIPTS.match(part):
            continue
        redirects = re.findall(r">{1,2}\s*(\S+\.md)", part)
        if not SHELL_WRITE.search(part) and not redirects:
            continue
        # только перенаправление (> файл) — пишется один файл: путь md в тексте, который дописывают, — не запись
        tokens = MD_TOKEN.findall(part) if SHELL_WRITE.search(part) else redirects
        for token in tokens:
            _, rel, kind = classify(norm(token, cwd))
            if kind == "md":
                return deny(
                    f"«{part.strip()[:80]}» пишет md карты {rel} мимо Edit/Write — правь через Edit или Write, "
                    f"удалить или переименовать — map.py rm / map.py mv"
                )
    return 0


def post_edit(data: dict) -> int:
    path = (data.get("tool_input") or {}).get("file_path")
    if not path:
        return 0
    p = norm(path, data.get("cwd"))
    root, rel, kind = classify(p)
    if root is None:
        return 0
    if rel.startswith("project/") or rel == "TOBE/board.yaml":
        out = "правлены данные карты — нужна полная сборка build.py" + (
            " (настройки проекта меняют все страницы)" if rel == "project/settings.yaml" else "")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": out}},
                         ensure_ascii=False))
        return 0
    if kind != "md":
        return 0
    res = subprocess.run(
        # свой build.py рядом с хуком: у копии проверочной карты своей папки tools/ нет
        [sys.executable, str(Path(__file__).resolve().parent / "build.py"), "--root", str(root), rel, "--own"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    text = res.stdout.strip() + ("\n" + res.stderr.strip() if res.stderr.strip() else "")
    if res.returncode == 2:
        print(f"{rel}: в md ошибки — страница не собрана\n{text}", file=sys.stderr)
        return 2
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": f"{rel}: {text}"}},
                         ensure_ascii=False))
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8")
        data = json.loads(raw) if raw.strip() else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return deny(f"hook.py: вход не разобран ({e}) — хук не может проверить правку")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if mode == "pre-edit":
        return pre_edit(data)
    if mode == "pre-shell":
        return pre_shell(data)
    if mode == "post-edit":
        return post_edit(data)
    return deny(f"hook.py: неизвестный режим «{mode}»: pre-edit, pre-shell, post-edit")


if __name__ == "__main__":
    sys.exit(main())
