"""Монитор хода агента: сводка раз в N секунд, пока агент не пришлёт итоговый отчёт (STATUS:).

Агенты разработки отчитываются только в конце; этот скрипт читает журнал вызовов агента
(~/.claude/projects/*/*/subagents/agent-<id>.jsonl) и репо, в котором он работает, и печатает
строку, только когда с прошлого раза что-то изменилось: сколько идёт, вызовов, новые коммиты,
файлов в работе, последнее действие и последняя «мысль вслух».

Запускать инструментом Monitor сразу после запуска агента (/dev-block, шаг 6):
    PYTHONIOENCODING=utf-8 python .claude/scripts/agent_progress.py <agent_id> <репо> <коммит до блока> [интервал_с=300] [метка]
Каждая строка — событие монитора; сводку — решающему 2–3 строками. Монитор живёт до 30 минут — перезапускать.
"""

import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime

agent, repo, base = sys.argv[1], sys.argv[2], sys.argv[3]
every = int(sys.argv[4]) if len(sys.argv) > 4 else 300
label = sys.argv[5] if len(sys.argv) > 5 else "агент"
sys.stdout.reconfigure(encoding="utf-8")
PATTERN = os.path.join(os.path.expanduser("~"), ".claude", "projects", "*", "*", "subagents", f"agent-{agent}.jsonl")


def git(*args: str) -> str:
    """Вывод git в репо агента (пусто при ошибке)."""
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip()


def snapshot() -> dict | None:
    """Состояние агента: вызовы, последнее действие и мысль, коммиты после base, файлы в работе."""
    files = glob.glob(PATTERN)
    if not files:
        return None
    calls, last_call, last_text, first, last, done = 0, "", "", None, None, False
    for line in open(files[0], encoding="utf-8"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ts = d.get("timestamp", "")
        first = first or ts
        last = ts or last
        content = d.get("message", {}).get("content")
        for x in content if isinstance(content, list) else []:
            if x.get("type") == "tool_use":
                calls += 1
                i = x.get("input", {})
                last_call = (i.get("description") or i.get("command") or i.get("file_path") or x["name"])[:110]
            if x.get("type") == "text" and d.get("message", {}).get("role") == "assistant" and x.get("text", "").strip():
                last_text = x["text"].strip().replace("\n", " ")
                done = done or "STATUS:" in last_text[:40]  # отчёт бывает обёрнут в блок кода
    return {"calls": calls, "last_call": last_call, "last_text": last_text[:200], "first": first, "last": last,
            "commits": git("log", "--oneline", f"{base}..HEAD").splitlines(),
            "dirty": len(git("status", "--porcelain").splitlines()), "done": done}


def minutes(a: str | None, b: str | None) -> str:
    """Минуты между двумя отметками времени журнала."""
    try:
        return str(int((datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds() // 60))
    except (AttributeError, ValueError):
        return "?"


prev = None
while True:
    s = snapshot()
    if s and (prev is None or s["calls"] != prev["calls"] or s["commits"] != prev["commits"] or s["done"]):
        new = [c for c in s["commits"] if not prev or c not in prev["commits"]]
        print(f"[{label}] идёт {minutes(s['first'], s['last'])} мин · вызовов {s['calls']} · коммитов {len(s['commits'])}"
              + (f" (новые: {'; '.join(new)})" if new else "") + f" · файлов в работе {s['dirty']}", flush=True)
        print(f"  сейчас: {s['last_call']}", flush=True)
        if s["last_text"]:
            print(f"  мысль: {s['last_text']}", flush=True)
        if s["done"]:
            print(f"[{label}] прислал итоговый отчёт", flush=True)
            break
        prev = s
    time.sleep(every)
