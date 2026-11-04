"""Часть фактов «pytest»: сколько тестов у сервиса на Python и, с --tests, итог их прогона.

Зачем. В tests.md пишется только «почему тесты такие»; сколько собрано и чем кончился прогон — отсюда, с датой.
Числа меняются при каждом прогоне, поэтому руками не пишутся.

Что читает. Поле tests реестра — папки тестов от root; tests_skip — словами, почему тесты считаются, но не
запускаются. Сбор (pytest --co) — всегда; прогон — только с extract.py <сервис> --tests: тесты идут с очищенным
окружением (без адресов баз, Redis и прокси — чтобы не тронуть живые базы) и с потолком памяти 4 ГБ на прогон.
Без --tests итог прошлого прогона переносится из прежнего .facts.json.

Раздел .facts.json:
  collected        папка тестов → сколько собрано
  collect_errors   папка → errors (сколько), files (до 10 файлов, которые не собрались), hint (первая строка ошибки)
  run              date, python, env — с каким окружением шёл прогон; results — папка → passed, failed, skipped,
                   errors, memory_limit (упёрся в потолок памяти), timeout (остановлен по времени),
                   collection_error, failed_names и error_names (до 20 имён); у сервиса с tests_skip — skipped: почему

Что нельзя. Запускать прогон для всех сервисов разом: только по одному сервису (extract.py <сервис> --tests).
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys

from facts._base import Ctx, diff, run_limited

SANITIZE = re.compile(r"REDIS|DATABASE|_DB_|DB_URL|POSTGRES|AUTH_DB|^TEST_|PROXY", re.I)
TEST_MEM_GB = 4.0


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not SANITIZE.search(k)}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _pytest(ctx: Ctx, args: list[str], timeout: int) -> str:
    base = [sys.executable, "-m", "pytest", *args, "-p", "no:cacheprovider"]
    _, out, _ = run_limited([*base, "--no-cov"], ctx.root, _clean_env(), timeout, TEST_MEM_GB)
    if "unrecognized arguments: --no-cov" in out:
        _, out, _ = run_limited(base, ctx.root, _clean_env(), timeout, TEST_MEM_GB)
    return out


def extract(ctx: Ctx) -> dict:
    res: dict = {"collected": {}, "run": (ctx.previous.get("pytest") or {}).get("run")}
    for t in ctx.info.get("tests", []):
        if not (ctx.root / t).is_dir():
            continue
        out = _pytest(ctx, [t, "--co", "-q"], 300)
        m = re.search(r"(\d+) tests? collected", out) or re.search(r"collected (\d+) items?", out)
        res["collected"][t] = int(m[1]) if m else 0
        e = re.search(r"(\d+) errors? during collection|(\d+) errors? in [\d.]+s", out)
        if e or "ERROR collecting" in out:
            res.setdefault("collect_errors", {})[t] = {
                "errors": int((e[1] or e[2]) if e else 1),
                "files": re.findall(r"ERROR collecting (\S+)", out)[:10],
                "hint": next((ln.strip() for ln in out.splitlines() if re.match(r"^E\s+\w+(Error|Exception)", ln.strip())), "")[:200],
            }
    if ctx.run_tests and ctx.info.get("tests_skip"):
        res["run"] = {"date": dt.date.today().isoformat(), "skipped": ctx.info["tests_skip"], "results": {}}
    elif ctx.run_tests:
        results = {}
        for t in res["collected"]:
            out = _pytest(ctx, [t, "-q", "-rfE"], 900)
            summary = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
            last = [ln for ln in out.splitlines() if re.search(r"\d+ (passed|failed|skipped|error)", ln)]
            if last:
                for n, kind in re.findall(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed)", last[-1]):
                    key = "errors" if kind.startswith("error") else kind
                    summary[key] = summary.get(key, 0) + int(n)
            summary["memory_limit"] = "упёрся в потолок памяти" in out
            summary["timeout"] = "[остановлено: дольше" in out
            summary["collection_error"] = bool(re.search(r"errors? during collection|Interrupted: \d+ errors?", out))
            summary["failed_names"] = re.findall(r"^FAILED (\S+)", out, re.M)[:20]
            summary["error_names"] = re.findall(r"^ERROR (\S+)", out, re.M)[:20]
            results[t] = summary
        res["run"] = {"date": dt.date.today().isoformat(), "python": sys.version.split()[0],
                      "env": "очищено от адресов баз, Redis и прокси", "results": results}
    return res


def compare(old: dict, new: dict) -> list[str]:
    return diff(old, new, "pytest", ignore=frozenset({"run"}))
