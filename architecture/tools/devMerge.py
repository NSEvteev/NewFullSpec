"""Доставка ветки изменения в main: проверка ветки, PR, merge и main без переключения на старый код.

Зачем. Где сервисы берут код с диска, git switch на старый локальный main подменяет файлы старой версией: живой сервис
подхватывает старый код. А неотправленные коммиты main уезжают в PR и склеиваются при squash. Порядок команд здесь один
и проверен, поэтому ни шага не пропустить.

Кто зовёт. Скилл /dev-deliver, основная сессия. Из корня репо, стоя на ветке изменения:
  python <карта>/tools/devMerge.py check                                 ветка готова к PR: git fetch и чтение, файлы не меняет
  python <карта>/tools/devMerge.py pr --title "<заголовок>" --body-file <файл> [--dry-run]
                                                                         push, PR, коммиты PR = коммиты ветки; печатает номер
  python <карта>/tools/devMerge.py merge <номер> [--dry-run]             squash-merge, main = origin/main, слитую ветку удалить
  python <карта>/tools/devMerge.py --selftest                            самопроверка на своих временных репо
--dry-run печатает, что будет сделано, и ничего не меняет.

Порядок merge: gh pr merge --squash --match-head-commit <голова> (пройдёт, только если на GitHub та же голова, что
проверяли); PR должен стать MERGED; git fetch; git branch -f main origin/main; git switch main. Слитая ветка удаляется,
только если её содержимое совпало с origin/main; не совпало — пришли чужие более новые коммиты: скрипт называет их и
ветку оставляет. --delete-branch у gh не ставится: gh сначала переключается на старый локальный main.

Что читает и пишет. Читает обложку TOBE/README.md (поле «Ветка:»), git и gh. Пишет только git и GitHub: md не трогает,
номер PR на обложку вписывает сессия.

Коды выхода: 0 — сделано или готово; 1 — стоп: причина в выводе, main не тронут; 2 — ошибка вызова.

Чего не делает. Не решает, что делать с чужими коммитами в ветке: называет их, решает тот, кто решает. Тело PR не пишет.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

Run = Callable[..., tuple[int, str]]


def shell(cmd: list[str], cwd: Path) -> tuple[int, str]:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return res.returncode, (res.stdout + res.stderr).strip()


class Delivery:
    def __init__(self, repo: Path, gh: Run | None = None, say: Callable[[str], None] = print):
        self.repo = repo
        self.gh_run = gh or (lambda *a: shell(["gh", *a], repo))
        self.say = say

    def git(self, *args: str) -> tuple[int, str]:
        return shell(["git", *args], self.repo)

    def out(self, *args: str) -> str:
        return self.git(*args)[1].strip()

    def cover_branch(self, root: Path | None) -> str:
        p = (root or self.repo / "architecture") / "TOBE" / "README.md"
        if not p.is_file():
            return ""
        m = re.search(r"^Ветка:\s*(.+)$", p.read_text(encoding="utf-8"), re.M)
        return m.group(1).strip(" `") if m else ""

    def check(self, root: Path | None = None) -> bool:
        """Ветка готова к PR: стою на ней, неотправленных в main нет, коммиты названы."""
        self.git("fetch", "origin", "--quiet")
        branch, ok = self.out("branch", "--show-current"), True
        want = self.cover_branch(root)
        self.say(f"ветка: {branch}" + (f"; на обложке: {want}" if want else ""))
        if branch == "main" or (want and branch != want):
            self.say(f"стоп: нужно стоять на ветке изменения {want or 'change/…'}")
            ok = False
        unsent = self.out("rev-list", "--count", "origin/main..main")
        self.say(f"неотправленных в main: {unsent}")
        if unsent != "0":
            self.say("стоп: они уедут в PR и склеятся при squash — разобрать: " + self.out("log", "--oneline", "origin/main..main"))
            ok = False
        log = self.out("log", "--format=%h %an %ad %s", "--date=short", "origin/main..HEAD")
        self.say("коммиты ветки — в списке только коммиты изменения:\n" + (log or "нет"))
        if not log:
            self.say("стоп: в ветке нет коммитов")
            ok = False
        return ok

    def pr(self, title: str, body_file: str, dry: bool) -> int | None:
        """Push, PR, сверка коммитов PR с коммитами ветки. Номер PR или None."""
        branch = self.out("branch", "--show-current")
        if branch == "main":
            self.say("стоп: стою на main")
            return None
        if not Path(body_file).is_file():
            self.say(f"стоп: файла тела PR {body_file} нет")
            return None
        if dry:
            self.say(f"сделаю: git push -u origin {branch}")
            self.say(f"сделаю: gh pr create --base main --head {branch} --title «{title}» --body-file {body_file}")
            return 0
        code, text = self.git("push", "-u", "origin", branch)
        if code:
            self.say(f"стоп: push не вышел: {text[:300]}")
            return None
        code, text = self.gh_run("pr", "create", "--base", "main", "--head", branch, "--title", title, "--body-file", body_file)
        if code:
            self.say(f"стоп: PR не создан: {text[:300]}")
            return None
        m = re.search(r"/pull/(\d+)", text)
        if not m:
            self.say(f"стоп: номер PR не найден в ответе: {text[:300]}")
            return None
        num = int(m.group(1))
        code, text = self.gh_run("pr", "view", str(num), "--json", "commits")
        have = [c["oid"] for c in json.loads(text)["commits"]] if code == 0 else []
        want = self.out("log", "--reverse", "--format=%H", "origin/main..HEAD").split()
        if have != want:
            self.say(f"стоп: коммиты PR #{num} не совпали с коммитами ветки: в PR {len(have)}, в ветке {len(want)}")
            return None
        self.say(f"PR #{num}: коммитов {len(have)}, совпали с веткой. Вписать «PR: #{num}» на обложку и закоммитить.")
        return num

    def merge(self, num: int, dry: bool) -> bool:
        """Squash-merge и main без переключения на старый код."""
        branch = self.out("branch", "--show-current")
        if branch == "main" or not branch:
            self.say(f"стоп: нужно стоять на ветке изменения, а не на {branch or 'отдельном коммите'}")
            return False
        head = self.out("rev-parse", "HEAD")
        if dry:
            self.say(f"сделаю: gh pr merge {num} --squash --match-head-commit {head[:9]}")
            self.say("сделаю: git fetch origin; git branch -f main origin/main; git switch main")
            self.say(f"сделаю: ветку {branch} удалить, если её содержимое совпало с origin/main")
            return True
        code, text = self.gh_run("pr", "merge", str(num), "--squash", "--match-head-commit", head)
        if code:
            self.say(f"стоп: merge не вышел, main не тронут: {text[:300]}")
            return False
        code, text = self.gh_run("pr", "view", str(num), "--json", "state,mergeCommit")
        state = json.loads(text) if code == 0 else {}
        if state.get("state") != "MERGED":
            self.say(f"стоп: PR #{num} не слит ({state.get('state') or text[:120]}), main не тронут")
            return False
        self.say(f"PR #{num} MERGED: {(state.get('mergeCommit') or {}).get('oid', '?')[:9]}")
        self.git("fetch", "origin")
        same = self.git("diff", "--quiet", "HEAD", "origin/main")[0] == 0
        if not same:
            self.say("в origin/main пришли ещё и чужие более новые коммиты — назвать решающему:\n" + self.out("diff", "--stat", "HEAD", "origin/main"))
        code, text = self.git("branch", "-f", "main", "origin/main")
        if code:
            self.say(f"стоп: main не передвинут: {text[:300]}")
            return False
        code, text = self.git("switch", "main")
        if code:
            self.say(f"стоп: на main не перешёл: {text[:300]}")
            return False
        self.say(self.out("status", "-sb").splitlines()[0])
        if same:
            self.git("branch", "-D", branch)
            code, text = self.git("push", "origin", "--delete", branch)
            self.say(f"ветка {branch} удалена" + ("" if code == 0 else f" здесь; на GitHub — нет: {text[:200]}"))
        else:
            self.say(f"ветка {branch} оставлена: её содержимое не совпало с origin/main")
        return True


def selftest() -> int:
    """Свои временные репо и подставной gh: чистый путь проходит, каждая порча останавливается."""
    bad: list[str] = []

    def check_that(cond: bool, what: str) -> None:
        if not cond:
            bad.append(what)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        base = Path(tmp)

        def git(cwd: Path, *args: str) -> str:
            code, text = shell(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd)
            if code:
                raise RuntimeError(f"git {args}: {text}")
            return text.strip()

        def repos(name: str) -> tuple[Path, Path]:
            """Голый origin и клон с веткой change/x, в которой один коммит."""
            root = base / name
            root.mkdir()
            git(root, "init", "--bare", "-q", "-b", "main", "origin.git")
            git(root, "clone", "-q", "origin.git", "work")
            work = root / "work"
            git(work, "config", "user.name", "t")
            git(work, "config", "user.email", "t@t")
            git(work, "switch", "-q", "-c", "main")
            (work / "a.txt").write_text("один\n", encoding="utf-8")
            git(work, "add", "a.txt")
            git(work, "commit", "-qm", "первый")
            git(work, "push", "-q", "-u", "origin", "main")
            git(work, "switch", "-q", "-c", "change/x")
            (work / "a.txt").write_text("два\n", encoding="utf-8")
            git(work, "add", "a.txt")
            git(work, "commit", "-qm", "изменение")
            git(work, "push", "-q", "-u", "origin", "change/x")
            return root, work

        def fake_gh(root: Path, merges: bool = True, extra: bool = False) -> Run:
            """gh, который сливает ветку squash-ем в origin; extra — там же появляется чужой новый коммит."""

            def run(*args: str) -> tuple[int, str]:
                if args[:2] == ("pr", "merge"):
                    if merges:
                        other = root / "other"
                        git(root, "clone", "-q", "origin.git", "other")
                        git(other, "merge", "-q", "--squash", "origin/change/x")
                        git(other, "-c", "user.name=t", "commit", "-qm", "слито (#7)")
                        if extra:
                            (other / "b.txt").write_text("чужое\n", encoding="utf-8")
                            git(other, "add", "b.txt")
                            git(other, "commit", "-qm", "чужой коммит")
                        git(other, "push", "-q", "origin", "main")
                    return 0, ""
                if args[:2] == ("pr", "view") and "state,mergeCommit" in args:
                    return 0, json.dumps({"state": "MERGED" if merges else "OPEN", "mergeCommit": {"oid": "abc123456789"}})
                return 1, "неизвестный вызов"

            return run

        quiet = lambda _: None  # noqa: E731

        root, work = repos("ok")
        check_that(Delivery(work, say=quiet).check(root), "check: чистая ветка не прошла")
        before = git(work, "rev-parse", "main")
        check_that(Delivery(work, fake_gh(root), quiet).merge(7, True), "merge --dry-run: отказ")
        check_that(git(work, "rev-parse", "main") == before, "merge --dry-run: main тронут")
        check_that(Delivery(work, fake_gh(root), quiet).merge(7, False), "merge: чистый путь не прошёл")
        check_that(git(work, "branch", "--show-current") == "main", "merge: не перешёл на main")
        check_that(git(work, "rev-parse", "main") == git(work, "rev-parse", "origin/main"), "merge: main ≠ origin/main")
        check_that("change/x" not in git(work, "branch", "--list", "change/x"), "merge: ветка не удалена")
        check_that("change/x" not in git(work, "ls-remote", "--heads", "origin", "change/x"), "merge: ветка на origin не удалена")

        body = base / "тело.md"
        body.write_text("тело\n", encoding="utf-8")
        root, work = repos("prdry")
        check_that(Delivery(work, say=quiet).pr("заголовок", str(body), True) == 0, "pr --dry-run: чистый путь")
        check_that(Delivery(work, say=quiet).pr("заголовок", "нет-файла.md", True) is None, "pr: нет файла тела — не пойман")
        git(work, "switch", "-q", "main")
        check_that(Delivery(work, say=quiet).pr("заголовок", str(body), True) is None, "pr --dry-run на main — не пойман")

        root, work = repos("unsent")
        git(work, "switch", "-q", "main")
        (work / "c.txt").write_text("своё\n", encoding="utf-8")
        git(work, "add", "c.txt")
        git(work, "commit", "-qm", "неотправленный")
        git(work, "switch", "-q", "change/x")
        check_that(not Delivery(work, say=quiet).check(root), "check: неотправленный коммит main не пойман")

        root, work = repos("onmain")
        git(work, "switch", "-q", "main")
        check_that(not Delivery(work, say=quiet).check(root), "check: стою на main — не пойман")
        check_that(not Delivery(work, fake_gh(root), quiet).merge(7, False), "merge: стою на main — не пойман")

        root, work = repos("notmerged")
        before = git(work, "rev-parse", "main")
        check_that(not Delivery(work, fake_gh(root, merges=False), quiet).merge(7, False), "merge: PR не слит — не пойман")
        check_that(git(work, "rev-parse", "main") == before, "merge: PR не слит, а main тронут")
        check_that(git(work, "branch", "--show-current") == "change/x", "merge: PR не слит, а ветка сменилась")

        root, work = repos("foreign")
        check_that(Delivery(work, fake_gh(root, extra=True), quiet).merge(7, False), "merge: чужой коммит — отказ")
        check_that(bool(git(work, "branch", "--list", "change/x")), "merge: чужой коммит, а ветка удалена")

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
    ap = argparse.ArgumentParser(prog="devMerge.py", description="Доставка ветки в main (шапка файла — подробно).")
    ap.add_argument("what", nargs="?", choices=("check", "pr", "merge"))
    ap.add_argument("num", nargs="?", type=int)
    ap.add_argument("--title")
    ap.add_argument("--body-file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    root = Path(__file__).resolve().parent.parent
    d = Delivery(root.parent)
    if a.what == "check":
        return 0 if d.check(root) else 1
    if a.what == "pr":
        if not a.title or not a.body_file:
            print("ошибка: у pr нужны --title и --body-file", file=sys.stderr)
            return 2
        return 0 if d.pr(a.title, a.body_file, a.dry_run) is not None else 1
    if a.what == "merge":
        if a.num is None:
            print("ошибка: у merge нужен номер PR", file=sys.stderr)
            return 2
        return 0 if d.merge(a.num, a.dry_run) else 1
    print("ошибка: check, pr, merge или --selftest", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
