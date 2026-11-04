"""Снимки страниц: вход, ширины, ошибки консоли и прокрутка вбок — одной командой, в своём окне браузера.

Зачем. Снимок нужен описанию, блоку и доставке, и каждый раз сессия заново собирала вход с пропуском, ширины и сервер для
страниц карты. Браузер без своего имени — общий на всю машину: другая сессия перехватывает его посреди съёмки.

Кто зовёт. Скиллы /dev-describe, /dev-block, /dev-deliver. Из корня репо, сервисы подняты:
  python <карта>/tools/devShot.py /orders --out <папка>                      страница интерфейса, вход — ролью user
  python <карта>/tools/devShot.py /orders --role admin --out <папка>         вход админом: его действия могут сохраниться в данных
  python <карта>/tools/devShot.py --map TOBE/index.html --out <папка>        страница карты; сервер поднимает и гасит сам
  … --size 1920x1080 [--size 2560x1440 …]   ширины; по умолчанию все три: см. SIZES
  … --name <приставка>                      имя файлов; по умолчанию — из адреса
  … --dry-run                               что будет сделано; пропуск в выводе скрыт
  python <карта>/tools/devShot.py --selftest                                 самопроверка без браузера

Что печатает. Строку на снимок: файл, прокрутка вбок, ошибки консоли. Картинки в контекст не несёт: открыть файл через Read
— дело сессии, только там, где нужно смотреть.

Настройка — ключ ui в project/settings.yaml (адрес интерфейса, команда входа, ключ localStorage, ширины): своего адреса и
своего входа у скрипта нет. Ключа нет — снимаются только страницы карты (--map) и страницы с полным адресом, без входа.

Что читает и пишет. Команда входа ui.login_command печатает значение для localStorage (в вывод скрипта оно не попадает);
playwright-cli в своём окне -s=<имя>, запускается из папки --out: из репо он мусорит своей папкой. Пишет только в --out. Репо
и базу не меняет; действия под admin страница может сохранить как настройки человека: поэтому умолчание — роль user.

Коды выхода: 0 — снято, бед нет; 1 — беда в строке снимка или снимок не вышел; 2 — ошибка вызова.

Чего не делает. Не кликает и не подменяет ответы сервисов: сценарии — playwright-cli run-code, как в PROJECT.md,
«Снимки интерфейса».
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parents[1]
SIZES = ("1920x1080", "2560x1440")
SIZE_RE = re.compile(r"^(\d{3,5})x(\d{3,5})$")
PLAYWRIGHT = "playwright-cli.cmd" if os.name == "nt" else "playwright-cli"

Cli = Callable[[list[str]], tuple[int, str]]


def load_ui(root: Path = TOOLS.parent) -> dict:
    """Ключ ui настроек проекта: адрес интерфейса, вход, ширины. Нет ключа — пустой словарь."""
    data = yaml.safe_load((root / "project" / "settings.yaml").read_text(encoding="utf-8")) or {}
    return data.get("ui") or {}


def login_value(ui: dict, role: str) -> str | None:
    """Значение localStorage для входа — вывод команды проекта; команды нет — входа нет."""
    command = ui.get("login_command")
    if not command:
        return None
    args = shlex.split(str(command).replace("{role}", role))
    if args and args[0] == "python":  # тот же интерпретатор, каким запущен скрипт
        args[0] = sys.executable
    res = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO)
    if res.returncode != 0 or not res.stdout.strip():
        raise ValueError(f"вход не получен: ui.login_command вернула код {res.returncode}")
    return res.stdout.strip()


def page_path(target: str) -> str:
    """Git Bash превращает аргумент /orders в C:/Program Files/Git/orders: вернуть как было."""
    m = re.match(r"^[A-Za-z]:/.*?/Git(/.*)$", target.replace("\\", "/"))
    return m.group(1) if m else target


def file_name(target: str) -> str:
    name = re.sub(r"[^\w-]+", "-", target.split("?")[0]).strip("-")
    return name or "page"


def parse_sizes(sizes: list[str]) -> list[tuple[int, int]]:
    out = []
    for s in sizes:
        m = SIZE_RE.match(s)
        if not m:
            raise ValueError(f"ширина «{s}» — нужно видом 1920x1080")
        out.append((int(m.group(1)), int(m.group(2))))
    return out


def plan(url: str, sizes: list[tuple[int, int]], name: str, auth: str | None, key: str = "auth") -> list[tuple[list[str], str]]:
    """Команды playwright-cli по порядку: (аргументы, что ждём). Вход — до перехода на страницу."""
    origin = re.match(r"^https?://[^/]+", url).group(0)
    steps: list[tuple[list[str], str]] = [(["open", origin], "")]
    if auth:
        steps.append((["localstorage-set", key, auth], ""))
    for w, h in sizes:
        steps += [
            (["resize", str(w), str(h)], ""),
            (["goto", url], ""),
            (["screenshot", f"--filename={name}-{w}.png"], f"shot:{w}"),
            (["eval", "document.documentElement.scrollWidth > window.innerWidth"], f"scroll:{w}"),
            (["console", "error"], f"console:{w}"),
        ]
    steps.append((["close"], ""))
    return steps


def shoot(steps: list[tuple[list[str], str]], cli: Cli, say: Callable[[str], None]) -> bool:
    """Исполняет план, печатает строку на снимок. Окно закрывает всегда."""
    ok = True
    results: dict[int, dict[str, str]] = {}
    try:
        for args, mark in steps:
            if args[0] == "close":
                continue
            code, out = cli(args)
            if code and not mark.startswith("console"):
                say(f"не вышло: {args[0]}: {out[:200]}")
                return False
            if mark:
                kind, width = mark.split(":")
                results.setdefault(int(width), {})[kind] = out
    finally:
        cli(["close"])
    for width, got in sorted(results.items()):
        scroll = "true" in got.get("scroll", "").lower()
        errors = len(re.findall(r"\[error\]|^error", got.get("console", ""), re.I | re.M))
        path = re.search(r"[^\s()\[\]]+\.png", got.get("shot", ""))
        if scroll or errors:
            ok = False
        say(f"{width}: {path.group(0) if path else '?'} · прокрутка вбок: {'ЕСТЬ' if scroll else 'нет'} · ошибок консоли: {errors}")
    return ok


class MapServer:
    """Страницы карты браузеру отдаёт сервер: file:// playwright-cli не открывает."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.proc: subprocess.Popen | None = None
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]

    def __enter__(self) -> "MapServer":
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(self.port), "--bind", "127.0.0.1", "--directory", str(self.directory)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(50):
            try:
                urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"http://127.0.0.1:{self.port}/", timeout=1)
                return self
            except OSError:
                time.sleep(0.1)
        return self

    def __exit__(self, *_) -> None:
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=10)


def selftest() -> int:
    bad: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "project").mkdir()
        (root / "project" / "settings.yaml").write_text("title: x\n", encoding="utf-8")
        if load_ui(root) != {}:
            bad.append("настройки без ключа ui должны дать пустой словарь")
        (root / "project" / "settings.yaml").write_text("ui:\n  origin: http://localhost:5000\n", encoding="utf-8")
        if load_ui(root).get("origin") != "http://localhost:5000":
            bad.append("ключ ui не прочитан")
    if login_value({}, "user") is not None:
        bad.append("без команды входа вход не нужен")
    got = login_value({"login_command": "python -c \"print('entry-{role}')\""}, "user")
    if got != "entry-user":
        bad.append(f"вывод команды входа: {got}")
    try:
        login_value({"login_command": 'python -c "raise SystemExit(3)"'}, "user")
        bad.append("упавшая команда входа не поймана")
    except ValueError:
        pass
    token = "значение-входа"
    steps = plan("http://localhost:5000/orders", parse_sizes(["1920x1080", "2560x1440"]), "orders", token, "store")
    if ["localstorage-set", "store", token] not in [a for a, _ in steps]:
        bad.append("ключ localStorage не из настроек")
    names = [a[0] for a, _ in steps]
    if names.index("localstorage-set") > names.index("goto"):
        bad.append("вход должен быть до перехода на страницу")
    if names.count("screenshot") != 2 or names[0] != "open" or names[-1] != "close":
        bad.append(f"порядок команд: {names}")
    try:
        parse_sizes(["1920"])
        bad.append("ширина без высоты не поймана")
    except ValueError:
        pass
    said: list[str] = []

    if page_path("C:/Program Files/Git/orders") != "/orders" or page_path("/report") != "/report":
        bad.append("путь страницы из Git Bash не восстановлен")

    def clean(args: list[str]) -> tuple[int, str]:
        return (0, {"screenshot": "- [Screenshot of viewport](a-1920.png)", "eval": "false", "console": ""}.get(args[0], ""))

    if not shoot(plan("http://x/p", [(1920, 1080)], "a", None), clean, said.append) or not said[-1].startswith("1920: a-1920.png · прокрутка вбок: нет"):
        bad.append(f"чистый снимок: {said}")
    closed: list[str] = []

    def scrolls(args: list[str]) -> tuple[int, str]:
        closed.append(args[0])
        return (0, {"screenshot": "a-1920.png", "eval": "true", "console": ""}.get(args[0], ""))

    if shoot(plan("http://x/p", [(1920, 1080)], "a", None), scrolls, lambda _: None) or "close" not in closed:
        bad.append("прокрутка вбок не поймана или окно не закрыто")

    def errors(args: list[str]) -> tuple[int, str]:
        return (0, {"screenshot": "a-1920.png", "eval": "false", "console": "[ERROR] значения не получены"}.get(args[0], ""))

    if shoot(plan("http://x/p", [(1920, 1080)], "a", None), errors, lambda _: None):
        bad.append("ошибка консоли не поймана")
    closed.clear()

    def fails(args: list[str]) -> tuple[int, str]:
        closed.append(args[0])
        return (1, "нет браузера") if args[0] == "goto" else (0, "")

    if shoot(plan("http://x/p", [(1920, 1080)], "a", None), fails, lambda _: None) or "close" not in closed:
        bad.append("сбой перехода не остановил или окно не закрыто")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "i.html").write_text("<html>карта</html>", encoding="utf-8")
        with MapServer(Path(tmp)) as server:
            body = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"http://127.0.0.1:{server.port}/i.html", timeout=5).read()
            if "карта".encode() not in body:
                bad.append("сервер карты не отдал страницу")
        if server.proc and server.proc.poll() is None:
            bad.append("сервер карты не погашен")
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
    ap = argparse.ArgumentParser(prog="devShot.py", description="Снимки страниц (шапка файла — подробно).")
    ap.add_argument("page", nargs="?")
    ap.add_argument("--map", dest="map_page")
    ap.add_argument("--out")
    ap.add_argument("--role", default="user", choices=("user", "admin"))
    ap.add_argument("--size", action="append", default=[])
    ap.add_argument("--name")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    target = a.map_page or (page_path(a.page) if a.page else None)
    if not target or not a.out:
        print("ошибка: нужна страница или --map, и --out <папка>", file=sys.stderr)
        return 2
    ui = load_ui()
    try:
        sizes = parse_sizes(a.size or [str(s) for s in ui.get("sizes") or SIZES])
        auth = None if a.map_page else login_value(ui, a.role)
    except ValueError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2
    name = a.name or file_name(target)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    session = f"devshot-{os.getpid()}"

    def cli(args: list[str]) -> tuple[int, str]:
        res = subprocess.run([PLAYWRIGHT, f"-s={session}", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=out)
        text = (res.stdout + res.stderr).strip()
        return res.returncode, text.replace(auth, "<вход>") if auth else text

    def run(url: str) -> bool:
        steps = plan(url, sizes, name, auth, str(ui.get("storage_key") or "auth"))
        if a.dry_run:
            for args, _ in steps:
                print("сделаю: playwright-cli " + " ".join("<вход>" if x == auth else x for x in args))
            return True
        return shoot(steps, cli, print)

    if a.map_page:
        with MapServer(TOOLS.parent) as server:
            ok = run(f"http://127.0.0.1:{server.port}/{a.map_page}")
    else:
        if not target.startswith("http") and not ui.get("origin"):
            print("ошибка: нет ui.origin в project/settings.yaml — дай полный адрес страницы или заполни настройку", file=sys.stderr)
            return 2
        ok = run(target if target.startswith("http") else str(ui["origin"]).rstrip("/") + "/" + target.lstrip("/"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
