"""Слова решающего из журналов разговора: дословно, по времени, с сообщениями из очереди и ответами на вопросы.

Зачем. Пересказ после сжатия теряет уточнения, а сверка описания с тем, что решающий говорил, нужна по полной записи.
Журнал разговора — большой файл, читать его целиком в контекст дорого: скрипт отдаёт только реплики человека.

Кто зовёт. Скилл /dev-describe (сверка полноты) и любая сессия после сжатия. Из корня репо:
  python <карта>/tools/devWords.py --since 2026-11-03            все сессии проекта с этой даты
  python <карта>/tools/devWords.py --session <id или начало id>  одна сессия
  python <карта>/tools/devWords.py --selftest                    самопроверка на придуманном журнале
  … --dir <папка журналов>   другая папка; по умолчанию ~/.claude/projects/<имя проекта>
  … --max <N>                обрезать реплику до N знаков; по умолчанию не обрезать

Что считает словами. Реплика человека; сообщение, отправленное, пока сессия работала (вложение queued_command); ответ на
вопрос AskUserQuestion. Не считает: служебные вставки, вывод команд, сводку сжатия, текст скиллов.

Что читает. Журналы *.jsonl; время в них — UTC. Ничего не пишет.

Коды выхода: 0 — готово; 2 — ошибка вызова.

Чего не делает. Не сверяет и не понимает: сверяет сессия.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICE = ("<", "[Image", "Base directory for this skill", "This session is being continued", "Caveat:")
ANSWERED = ("The user answered", "Your questions have been answered", "User has answered")


def project_dir() -> Path:
    """Папка журналов проекта: путь репо, где двоеточие и косые — дефисы."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[:\\/]", "-", str(REPO))


def text_of(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [x.get("text", "") for x in content or [] if isinstance(x, dict) and x.get("type") == "text"]


def words_in(path: Path) -> list[tuple[str, str]]:
    """Реплики одного журнала: (время, текст)."""
    out: list[tuple[str, str]] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            ts = (e.get("timestamp") or "")[:16].replace("T", " ")
            attach = e.get("attachment") or {}
            if e.get("type") == "attachment" and attach.get("type") == "queued_command":
                q = "\n".join(text_of(attach.get("prompt"))).strip()
                if q and not q.startswith(SERVICE):
                    out.append((ts, q))
                continue
            if e.get("type") != "user" or e.get("isMeta"):
                continue
            content = (e.get("message") or {}).get("content")
            for t in text_of(content):
                t = t.strip()
                if t and not t.startswith(SERVICE):
                    out.append((ts, t))
            if isinstance(content, list):
                for x in content:
                    if isinstance(x, dict) and x.get("type") == "tool_result":
                        r = "\n".join(text_of(x.get("content"))).strip()
                        if r.startswith(ANSWERED):
                            out.append((ts, r))
    return out


def collect(folder: Path, since: str | None, session: str | None) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for p in sorted(folder.glob("*.jsonl")):
        if session and not p.stem.startswith(session):
            continue
        rows += [(ts, p.stem[:6], t) for ts, t in words_in(p) if not since or ts >= since]
    return sorted(rows, key=lambda r: r[0])


def selftest() -> int:
    lines = [
        {"type": "user", "timestamp": "2026-11-01T10:00:00Z", "message": {"content": "Придуманная реплика"}},
        {"type": "user", "timestamp": "2026-11-01T10:01:00Z", "isMeta": True, "message": {"content": "служебное"}},
        {"type": "user", "timestamp": "2026-11-01T10:02:00Z", "message": {"content": "<command-name>/dev</command-name>"}},
        {"type": "user", "timestamp": "2026-11-01T10:03:00Z", "message": {"content": "This session is being continued"}},
        {"type": "attachment", "timestamp": "2026-11-02T10:04:00Z", "attachment": {"type": "queued_command", "prompt": "Из очереди"}},
        {"type": "user", "timestamp": "2026-11-02T10:05:00Z", "message": {"content": [{"type": "tool_result", "content": "вывод команды"}]}},
        {"type": "user", "timestamp": "2026-11-02T10:06:00Z", "message": {"content": [{"type": "tool_result", "content": [{"type": "text", "text": "The user answered: да"}]}]}},
        {"type": "assistant", "timestamp": "2026-11-02T10:07:00Z", "message": {"content": [{"type": "text", "text": "ответ сессии"}]}},
    ]
    bad: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        body = "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\nне json\n"
        (folder / "abcdef-1.jsonl").write_text(body, encoding="utf-8")
        got = [t for _, _, t in collect(folder, None, None)]
        if got != ["Придуманная реплика", "Из очереди", "The user answered: да"]:
            bad.append(f"реплики: {got}")
        if [t for _, _, t in collect(folder, "2026-11-02", None)] != ["Из очереди", "The user answered: да"]:
            bad.append("--since не отсёк раннее")
        if collect(folder, None, "нет"):
            bad.append("--session нашёл чужую сессию")
    for x in bad:
        print(f"ошибка самопроверки: {x}")
    if bad:
        return 1
    print("Самопроверка: всё сходится.")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="devWords.py", description="Слова решающего (шапка файла — подробно).")
    ap.add_argument("--since")
    ap.add_argument("--session")
    ap.add_argument("--dir")
    ap.add_argument("--max", type=int)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.since and not a.session:
        print("ошибка: нужно --since <дата> или --session <id>", file=sys.stderr)
        return 2
    folder = Path(a.dir) if a.dir else project_dir()
    if not folder.is_dir():
        print(f"ошибка: папки журналов {folder} нет", file=sys.stderr)
        return 2
    rows = collect(folder, a.since, a.session)
    for ts, sid, text in rows:
        print(f"{ts} {sid}: {text[: a.max] if a.max else text}")
    print(f"реплик {len(rows)}, время — UTC")
    return 0


if __name__ == "__main__":
    sys.exit(main())
