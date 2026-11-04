"""Запомненные строки кода: текст строки по каждой ссылке «Код:» карты — ASIS/<сервис>/.anchors.json.

Зачем. Ссылка `путь:строка` переживает правку кода, только если знать, какой текст на этой строке стоял, когда
ссылку писали. По запомненному тексту живая проверка видит, что строка изменилась (проверить шаг), перенос ссылок
находит, куда она съехала, поиск по коду находит ссылку и после сдвига.

Кто зовёт. build.py — полная сборка запоминает новые ссылки и забывает ушедшие; build.py --check — ловит ссылки,
которых нет в запомненных (№24); live.py, relocate.py, map.py accept, find.py --code — читают. Руками файл не
правится.

Файл ASIS/<сервис>/.anchors.json — объект {"<путь от корня репо>:<строка>": "<текст строки без пробелов по краям>"},
ключи по порядку. Строка с похожим на секрет литералом (пароль, ключ, токен в кавычках) хранится отпечатком
«sha256:<12 знаков>», а не текстом. Ссылка из md сервиса — в файл этого сервиса; ссылки файлов процессов — в
ASIS/_processes/.anchors.json.

Чего не делает. Не правит md (это relocate.py) и не решает, сдвиг это или правка смысла: сравнивает текст.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SECRET_LITERAL = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|private[_-]?key)\w*\s*[:=]\s*[\"'][^\"']{8,}[\"']"
)


def stored(text: str) -> str:
    """Как строка хранится: секретоподобная — отпечатком."""
    if SECRET_LITERAL.search(text):
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return text


class Lines:
    """Строки файлов кода; каждый файл читается один раз."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.cache: dict[str, list[str] | None] = {}

    def get(self, path: str) -> list[str] | None:
        if path not in self.cache:
            f = self.repo / path
            self.cache[path] = (
                f.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").split("\n")
                if f.is_file() else None
            )
        return self.cache[path]

    def text(self, path: str, line: int) -> str | None:
        lines = self.get(path)
        if lines is None or not 0 < line <= len(lines):
            return None
        return lines[line - 1].strip()


def owner_dir(rel_md: str) -> str:
    """Папка, в чей .anchors.json идёт ссылка md: ASIS/<сервис> или ASIS/_processes."""
    parts = rel_md.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else "ASIS/_processes"


def refs(m) -> dict[str, dict[str, list[str]]]:
    """Ссылки карты по папкам: {папка: {"путь:строка": [md:строка, …]}} — по всем «Код:» модели."""
    out: dict[str, dict[str, list[str]]] = {}
    for e in m.entities.values():
        for r in e.code:
            out.setdefault(owner_dir(r.md), {}).setdefault(f"{r.path}:{r.line}", []).append(f"{r.md}:{r.md_line}")
    return out


def load(root: Path, folder: str) -> dict[str, str]:
    p = root / folder / ".anchors.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def dump(data: dict[str, str]) -> str:
    return json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=1) + "\n"


def remember(m) -> dict[str, tuple[dict[str, str], int, int]]:
    """Что запомнит полная сборка: {папка: (новый файл, новых ссылок, забытых)}. Старый текст не перезаписывается:
    по нему видно, что строка изменилась."""
    lines = Lines(m.repo)
    out = {}
    for folder, keys in refs(m).items():
        old = load(m.root, folder)
        new: dict[str, str] = {}
        added = 0
        for key in keys:
            if key in old:
                new[key] = old[key]
                continue
            path, _, n = key.rpartition(":")
            t = lines.text(path, int(n))
            if t is not None:
                new[key] = stored(t)
                added += 1
        out[folder] = (new, added, len(set(old) - set(new)))
    return out


def changed(m) -> list[tuple[str, str, str, str | None, list[str]]]:
    """Ссылки, чей текст в коде не совпал с запомненным: (папка, путь:строка, было, сейчас, где в md)."""
    lines = Lines(m.repo)
    out = []
    for folder, keys in refs(m).items():
        old = load(m.root, folder)
        for key, where in keys.items():
            if key not in old:
                continue
            path, _, n = key.rpartition(":")
            now = lines.text(path, int(n))
            if now is None or stored(now) != old[key]:
                out.append((folder, key, old[key], now, where))
    return out


def missing(m) -> list[tuple[str, str, list[str]]]:
    """Ссылки, которых нет в запомненных (№24): (папка, путь:строка, где в md)."""
    out = []
    for folder, keys in refs(m).items():
        old = load(m.root, folder)
        out += [(folder, k, w) for k, w in keys.items() if k not in old]
    return out


def find_moved(lines: Lines, path: str, text: str, near: int) -> list[int]:
    """Строки файла с тем же текстом — кандидаты, куда съехала ссылка; ближние к старой — первыми."""
    got = lines.get(path) or []
    hits = [i + 1 for i, x in enumerate(got) if stored(x.strip()) == text]
    return sorted(hits, key=lambda i: abs(i - near))
