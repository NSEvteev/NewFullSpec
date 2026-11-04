"""Общие помощники частей скрипта фактов: контекст, пути и ссылки, разбор кода, .env, секреты, compose, живые источники.

Зачем. Части (tools/facts/<часть>.py) делают разное, но одинаково пишут ссылки «путь:строка», одинаково прячут секреты
и одинаково ходят в живые источники. Это здесь, чтобы у двух частей не было двух правил.

Кто зовёт. Только части скрипта фактов и сам tools/extract.py. Сам модуль ничего не печатает и не пишет.

Что важно:
  - ссылка на код — путь от корня репо; файл вне репо — через ../ (как в строках «Код:» карты);
  - значение секрета в факты не пишется: имя секрета — по шаблонам secret_names из project/settings.yaml,
    пароль внутри адреса базы заменяется на ***;
  - живые источники (схема методов, база) — только чтение; без прокси: адреса локальные;
  - тесты запускаются с очищенным окружением (без адресов баз и Redis) и с потолком памяти на процесс и его детей.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SKIP_DIRS = {"__pycache__", "node_modules", "dist", "build", ".pytest_cache", ".mypy_cache", ".venv", "venv"}
TEST_DIRS = {"tests", "__tests__", "test", "mocks", "__mocks__"}
MIGRATION_DIRS = {"migrations", "alembic"}
CODE_EXTS_PY = (".py",)
# переменные, которые задаёт сама среда запуска, а не настройка сервиса
RUNTIME_VARS = {"PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "CHOKIDAR_USEPOLLING"}
COMMENT_LINE = re.compile(r"^\s*(#|//|/?\*)")


@dataclass
class Ctx:
    """Что получает часть: сервис, его запись реестра, настройки проекта, разделы прежних частей."""

    service: str
    info: dict
    settings: dict
    registry: dict
    repo: Path
    facts: dict = field(default_factory=dict)  # разделы частей, которые уже отработали
    previous: dict = field(default_factory=dict)  # прежний .facts.json сервиса (для итога тестов без --tests)
    run_tests: bool = False

    @property
    def root(self) -> Path:
        return (self.repo / self.info["root"]).resolve()

    @property
    def package(self) -> Path:
        return (self.repo / self.info["package"]).resolve()

    def rel(self, path: Path | str) -> str:
        return rel(self.repo, path)

    def ref(self, path: Path | str, line: int) -> str:
        return f"{self.rel(path)}:{line}"

    def is_secret(self, name: str) -> bool:
        return is_secret(self.settings, name)

    def mask(self, name: str, value: str) -> str:
        return "‹секрет›" if self.is_secret(name) else re.sub(r"(://[^:/@\s]*):[^@\s]*@", r"\1:***@", value)


# ─── пути и файлы ──────────────────────────────────────────────────────────────────────────────────


def rel(repo: Path, path: Path | str) -> str:
    """Путь от корня репо в виде a/b/c.py; вне репо — через ../."""
    p = Path(path)
    if not p.is_absolute():
        p = repo / p
    p = p.resolve()
    if p.is_relative_to(repo):
        return p.relative_to(repo).as_posix()
    return Path(os.path.relpath(p, repo)).as_posix()


def iter_files(root: Path, exts: tuple[str, ...], skip_tests: bool = True):
    """Файлы кода под root с нужными расширениями; без служебных папок и, по умолчанию, без тестов."""
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in exts:
            continue
        parts = set(p.relative_to(root).parts)
        if parts & SKIP_DIRS or any(x.endswith(".egg-info") for x in parts):
            continue
        if skip_tests and (parts & TEST_DIRS or p.name.startswith(("test_", "setupTests")) or ".test." in p.name):
            continue
        yield p


def code_files(pkg: Path, exts: tuple[str, ...]) -> list[Path]:
    """Код сервиса без миграций базы и тестов."""
    return [p for p in iter_files(pkg, exts) if not set(p.relative_to(pkg).parts) & MIGRATION_DIRS]


def code_lines(files: list[Path]) -> int:
    n = 0
    for p in files:
        n += sum(1 for line in p.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
    return n


def parse(p: Path) -> ast.Module | None:
    try:
        return ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None


def docstring_lines(p: Path) -> set[int]:
    """Номера строк описаний модуля, классов и функций — ссылки на них не ставятся: описание может врать."""
    tree = parse(p)
    out: set[int] = set()
    if not tree:
        return out
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            d = n.body[0]
            if isinstance(d, ast.Expr) and isinstance(d.value, ast.Constant) and isinstance(d.value.value, str):
                out |= set(range(d.lineno, (d.end_lineno or d.lineno) + 1))
    return out


def ref_key(r: str) -> tuple[str, int]:
    path, _, line = r.rpartition(":")
    return path, int(line) if line.isdigit() else 0


# ─── секреты ───────────────────────────────────────────────────────────────────────────────────────


def is_secret(settings: dict, name: str) -> bool:
    """Секрет ли настройка — по шаблонам secret_names проекта (регистр не важен)."""
    rules = settings.get("secret_names") or {}
    up = name.upper()
    hit = any(fnmatch.fnmatchcase(up, m.upper()) for m in rules.get("match", []))
    return hit and not any(fnmatch.fnmatchcase(up, e.upper()) for e in rules.get("except", []))


# ─── .env и подстановка ${VAR:-умолчание} ─────────────────────────────────────────────────────────


@dataclass
class EnvVar:
    name: str
    value: str
    file: str
    line: int


def load_env_file(repo: Path, path: Path) -> dict[str, EnvVar]:
    res: dict[str, EnvVar] = {}
    if not path.is_file():
        return res
    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        res[k] = EnvVar(k, v, rel(repo, path), i)
    return res


_VAR = re.compile(r"\$\{(?P<name>\w+)(?:(?P<op>:?[-?])(?P<arg>[^${}]*))?\}")


def interpolate(s: str, env: dict[str, EnvVar]) -> str:
    """Раскрыть ${VAR}, ${VAR:-умолчание}, ${VAR:?сообщение}; вложенные — изнутри наружу."""
    prev = None
    while prev != s:
        prev = s

        def sub(m: re.Match) -> str:
            name, op, arg = m["name"], m["op"], m["arg"] or ""
            v = env[name].value if name in env else ""
            if op and op.endswith("-") and not v:
                return arg
            return v

        s = _VAR.sub(sub, s)
    return s


# ─── compose с номерами строк ──────────────────────────────────────────────────────────────────────


def compose_paths(ctx: Ctx) -> tuple[Path | None, Path | None, str]:
    """(compose-файл, его файл переменных, имя проекта) из ключа compose настроек проекта."""
    c = ctx.settings.get("compose") or {}
    if not c.get("file"):
        return None, None, ""
    file = ctx.repo / c["file"]
    env = ctx.repo / c["env"] if c.get("env") else None
    return file, env, c.get("project") or file.parent.name


def _node_to_py(node):
    """yaml-узел → объект python, у которого у каждого значения сохранена строка файла."""
    if isinstance(node, yaml.MappingNode):
        return {k.value: _node_to_py(v) for k, v in node.value} | {"__line__": node.start_mark.line + 1}
    if isinstance(node, yaml.SequenceNode):
        return [_node_to_py(v) for v in node.value]
    return {"__value__": node.value, "__line__": node.start_mark.line + 1}


def load_compose(file: Path) -> dict:
    return _node_to_py(yaml.compose(file.read_text(encoding="utf-8")))


def val(node) -> str:
    return node["__value__"] if isinstance(node, dict) and "__value__" in node else str(node)


def line_of(node) -> int:
    return node.get("__line__", 0) if isinstance(node, dict) else 0


# ─── живые источники ───────────────────────────────────────────────────────────────────────────────


def http_json(url: str, timeout: float = 8.0):
    """GET и разбор JSON — без прокси: адреса живых источников локальные."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def psql(container: str, user: str, db: str, sql: str) -> list[list[str]]:
    """Запрос к базе в контейнере через psql; только чтение — запросы select."""
    out = subprocess.run(
        ["docker", "exec", container, "psql", "-U", user, "-d", db, "-At", "-F", "\t", "-c", sql],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"psql вернул {out.returncode}")
    return [line.split("\t") for line in out.stdout.rstrip("\n").split("\n") if line]


def run_limited(cmd: list[str], cwd: Path, env: dict, timeout: int, mem_gb: float = 4.0) -> tuple[int, str, bool]:
    """Запустить процесс с потолком памяти на него и всех его детей; (код выхода, вывод, упёрся ли в потолок).

    Зачем потолок: прогон тестов может занять всю память машины. В Windows — объект задания (Job Object): при
    превышении выделение памяти падает внутри процесса, а задание убивается целиком. В других системах — предел
    адресного пространства процесса (RLIMIT_AS).
    """
    if sys.platform != "win32":
        import resource

        lim = int(mem_gb * 1024**3)
        try:
            p = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_AS, (lim, lim)),
            )
            out = p.stdout + p.stderr
            hit = "MemoryError" in out
            return p.returncode, out + (f"\n[упёрся в потолок памяти {mem_gb:g} ГБ]\n" if hit else ""), hit
        except subprocess.TimeoutExpired as e:
            return 1, f"{e.stdout or ''}\n[остановлено: дольше {timeout} с]\n", False

    import ctypes
    import threading
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class BASIC(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED(ctypes.Structure):
        _fields_ = [
            ("Basic", BASIC),
            ("Io", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x200
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    info = EXTENDED()
    info.Basic.LimitFlags = JOB_OBJECT_LIMIT_JOB_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    info.JobMemoryLimit = int(mem_gb * 1024**3)
    if not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    h = k32.OpenProcess(0x1F0FFF, False, proc.pid)
    k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(h))
    chunks: list[str] = []
    reader = threading.Thread(target=lambda: chunks.append(proc.stdout.read()), daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        k32.TerminateJobObject(wintypes.HANDLE(job), 1)
        proc.wait()
        chunks.append(f"\n[остановлено: дольше {timeout} с]\n")
    reader.join(5)
    k32.QueryInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info), None)
    peak = info.PeakJobMemoryUsed / 1024**3
    hit = peak >= mem_gb * 0.95
    k32.CloseHandle(wintypes.HANDLE(h))
    k32.CloseHandle(wintypes.HANDLE(job))
    out = "".join(chunks)
    if hit:
        out += f"\n[упёрся в потолок памяти {mem_gb:g} ГБ, пик {peak:.1f} ГБ]\n"
    return proc.returncode, out, hit


# ─── сравнение для живой проверки ──────────────────────────────────────────────────────────────────


def diff(old, new, path: str = "", ignore: frozenset[str] = frozenset(), ids: dict[str, str] | None = None) -> list[str]:
    """Расхождения двух разделов строками «путь: было → стало».

    ignore — ключи, которые меняются сами и расхождением не считаются (число строк в таблице, дата прогона).
    ids — у списков записей: имя ключа списка → поле, по которому записи сопоставляются (methods → «method path»).
    """
    ids = ids or {}
    out: list[str] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            if k in ignore:
                continue
            p = f"{path}.{k}" if path else k
            if k not in new:
                out.append(f"{p}: было, нет")
            elif k not in old:
                out.append(f"{p}: не было, есть")
            else:
                out += diff(old[k], new[k], p, ignore, ids)
        return out
    if isinstance(old, list) and isinstance(new, list):
        key = ids.get(path.rsplit(".", 1)[-1])
        if key and all(isinstance(x, dict) for x in old + new):
            name = lambda x: " ".join(str(x.get(f, "")) for f in key.split())  # noqa: E731
            o, n = {name(x): x for x in old}, {name(x): x for x in new}
            for k in sorted(set(o) | set(n)):
                p = f"{path}[{k}]"
                if k not in n:
                    out.append(f"{p}: было, нет")
                elif k not in o:
                    out.append(f"{p}: не было, есть")
                else:
                    out += diff(o[k], n[k], p, ignore, ids)
            return out
    if old != new:
        out.append(f"{path}: {json.dumps(old, ensure_ascii=False)[:80]} → {json.dumps(new, ensure_ascii=False)[:80]}")
    return out
