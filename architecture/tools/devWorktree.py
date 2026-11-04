"""Рабочая копия для параллельного блока: завести и убрать так, чтобы основная папка не пострадала.

Зачем. Два агента с коммитами в одной рабочей копии нельзя: pre-commit прячет и возвращает чужие правки. Зависимости
интерфейса в копии — ссылка на основную папку, и git worktree remove идёт по этой ссылке: без снятия ссылки удаление
стирает зависимости основной папки. Поэтому ссылки снимает скрипт, а не память сессии.

Кто зовёт. Скилл /dev-block, основная сессия. Из корня репо:
  python <карта>/tools/devWorktree.py add <блок> [--link <путь от корня репо>]…   копия .claude/worktrees/<блок>
                                                               на новой ветке <текущая ветка>-<блок>; папка — в
                                                               .git/info/exclude; --link — ссылка на ту же папку основной
  python <карта>/tools/devWorktree.py rm <блок>                снять все ссылки в копии, затем git worktree remove;
                                                               незакоммиченное в копии — отказ, ветка остаётся
  python <карта>/tools/devWorktree.py --selftest               самопроверка на своём временном репо

Что читает и пишет. git; папку копии; .git/info/exclude. Основную папку не меняет.

Коды выхода: 0 — сделано; 1 — отказ: причина в выводе; 2 — ошибка вызова.

Чего не делает. Не переносит коммиты: cherry-pick в ветку изменения — дело основной сессии, ветка блока после него
удаляется ею же. Не проверяет пакет, установленный ссылкой: эта проверка — в брифе агента.
"""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

PLACE = ".claude/worktrees"


def shell(cmd: list[str], cwd: Path) -> tuple[int, str]:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return res.returncode, (res.stdout + res.stderr).strip()


def repo_root(cwd: Path) -> Path:
    code, out = shell(["git", "rev-parse", "--show-toplevel"], cwd)
    if code:
        raise ValueError(f"не репо git: {out[:120]}")
    return Path(out)


def make_link(link: Path, target: Path) -> tuple[bool, str]:
    """Ссылка на папку. На Windows — junction: не требует прав и работает для зависимостей интерфейса."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        code, out = shell(["cmd", "/c", "mklink", "/J", str(link), str(target)], link.parent)
        return code == 0, out
    os.symlink(target, link, target_is_directory=True)
    return True, ""


def is_link(p: Path) -> bool:
    return p.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(p))


def remove_link(p: Path) -> None:
    """Снимает только ссылку: цель не трогается."""
    if os.name == "nt":
        os.rmdir(p)
    else:
        p.unlink()


def find_links(top: Path) -> list[Path]:
    """Все ссылки на папки в копии; внутрь ссылок не заходит."""
    found = []
    for dirpath, dirnames, _ in os.walk(top, followlinks=False):
        for name in list(dirnames):
            p = Path(dirpath) / name
            if name == ".git":
                dirnames.remove(name)
            elif is_link(p):
                found.append(p)
                dirnames.remove(name)
    return found


def add(repo: Path, block: str, links: list[str], say=print) -> bool:
    top = repo / PLACE / block
    if top.exists():
        say(f"отказ: {top} уже есть")
        return False
    code, branch = shell(["git", "branch", "--show-current"], repo)
    if code or not branch:
        say("отказ: не на ветке")
        return False
    new = f"{branch}-{block}"
    code, out = shell(["git", "worktree", "add", "-q", "-b", new, f"{PLACE}/{block}", "HEAD"], repo)
    if code:
        say(f"отказ: {out[:300]}")
        return False
    exclude = repo / ".git" / "info" / "exclude"
    if exclude.is_file():
        text = exclude.read_text(encoding="utf-8")
        if PLACE not in text:
            exclude.write_text(text.rstrip("\n") + f"\n{PLACE}/\n", encoding="utf-8")
    for rel in links:
        target = repo / rel
        if not target.is_dir():
            say(f"ссылка не создана: {rel} нет в основной папке")
            continue
        link = top / rel
        if link.exists():
            say(f"ссылка не создана: {rel} уже есть в копии")
            continue
        made, out = make_link(link, target)
        say(f"ссылка {rel}" if made else f"ссылка не создана: {rel}: {out[:200]}")
    say(f"рабочая копия {PLACE}/{block}, ветка {new}. Агенту: каждая команда — cd {PLACE}/{block} && …")
    return True


def rm(repo: Path, block: str, say=print) -> bool:
    top = repo / PLACE / block
    if not top.is_dir():
        say(f"отказ: {top} нет")
        return False
    code, dirty = shell(["git", "status", "--porcelain"], top)
    if code == 0 and dirty.strip():
        say(f"отказ: в копии незакоммиченное, ссылки не сняты:\n{dirty[:600]}")
        return False
    links = find_links(top)
    for link in links:
        remove_link(link)
    code, out = shell(["git", "worktree", "remove", f"{PLACE}/{block}"], repo)
    if code:
        say(f"отказ: {out[:300]}; ссылок снято {len(links)}")
        return False
    say(f"копия {block} убрана; ссылок снято {len(links)}. Ветка блока осталась: удалить после переноса коммитов.")
    return True


def selftest() -> int:
    """Главное — цель ссылки цела после rm; порчи останавливаются."""
    bad: list[str] = []
    quiet = lambda _: None  # noqa: E731

    def on_error(func, path, _):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        repo = Path(tmp).resolve() / "r"
        repo.mkdir()

        def git(*args: str) -> str:
            code, out = shell(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], repo)
            if code:
                raise RuntimeError(out)
            return out

        git("init", "-q", "-b", "main")
        (repo / "a.txt").write_text("x\n", encoding="utf-8")
        (repo / ".gitignore").write_text("web/node_modules/\n", encoding="utf-8")
        git("add", "a.txt", ".gitignore")
        git("commit", "-qm", "первый")
        deps = repo / "web" / "node_modules"
        deps.mkdir(parents=True)
        marker = deps / "пакет.txt"
        marker.write_text("зависимости\n", encoding="utf-8")

        if not add(repo, "b3", ["web/node_modules", "нет/такой"], quiet):
            bad.append("add: чистый путь не прошёл")
        top = repo / PLACE / "b3"
        if not (top / "a.txt").is_file():
            bad.append("add: копия без файлов")
        if not is_link(top / "web" / "node_modules"):
            bad.append("add: ссылка не создана")
        if not (top / "web" / "node_modules" / "пакет.txt").is_file():
            bad.append("add: ссылка не ведёт к зависимостям")
        if "main-b3" not in git("branch", "--list", "main-b3"):
            bad.append("add: ветка блока не создана")
        if PLACE not in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8"):
            bad.append("add: папка не в .git/info/exclude")
        if ".claude" in git("status", "--porcelain"):
            bad.append("add: копия видна в git status основной папки")
        if add(repo, "b3", [], quiet):
            bad.append("add: вторая копия с тем же именем не отвергнута")

        (top / "новый.txt").write_text("правка\n", encoding="utf-8")
        if rm(repo, "b3", quiet):
            bad.append("rm: незакоммиченное в копии не остановило")
        if not is_link(top / "web" / "node_modules"):
            bad.append("rm при отказе снял ссылку")
        (top / "новый.txt").unlink()

        if not rm(repo, "b3", quiet):
            bad.append("rm: чистый путь не прошёл")
        if not marker.is_file():
            bad.append("rm стёр зависимости основной папки — главная порча")
        if top.exists():
            bad.append("rm: копия осталась")
        if rm(repo, "нет", quiet):
            bad.append("rm: несуществующая копия не отвергнута")
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
    ap = argparse.ArgumentParser(prog="devWorktree.py", description="Рабочая копия блока (шапка файла — подробно).")
    ap.add_argument("what", nargs="?", choices=("add", "rm"))
    ap.add_argument("block", nargs="?")
    ap.add_argument("--link", action="append", default=[])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.what or not a.block:
        print("ошибка: add <блок>, rm <блок> или --selftest", file=sys.stderr)
        return 2
    try:
        repo = repo_root(Path.cwd())
    except ValueError as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2
    done = add(repo, a.block, a.link) if a.what == "add" else rm(repo, a.block)
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
