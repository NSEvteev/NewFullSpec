"""Тест команд процесса на состояниях проверочной карты: where.py (где мы, ворота) и done.py (сделано ли).

Зачем. Шаг изменения, ворота и «сделано» процесс узнаёт этими командами; ошибись они — скилл поведёт не в тот шаг,
пустит код без «да» или очистит «как будет», которое не сделано. Каждое состояние проверяется прогоном.

Состояние — папка tools/samples/good/expect/<команда>/<номер>-<состояние>/:
  case.yaml   — как из чистой проверочной карты (на ней идёт описание с вопросами) получить это состояние: те же
                remove, replace, add, close, что у испорченных карт (tests/test_checks.py, функция spoiled);
  expect.txt  — строка 1 «$ <команда> <аргументы>» (where.py или done.py), строка 2 «# код выхода N», дальше — stdout.
Команда зовётся с --root на испорченную копию и без git (where.py --no-git; done.py --no-git --no-live): признаки —
только из файлов.

Как прогнать (из корня репо):
  python -m pytest architecture/tools/tests/test_states.py -q
  python architecture/tools/tests/test_states.py --update   — переписать вывод в expect.txt; прочитать git diff
"""

from __future__ import annotations

import contextlib
import io
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "tests"))
import done  # noqa: E402
import where  # noqa: E402
from test_checks import spoiled  # noqa: E402

EXPECT = TOOLS / "samples" / "good" / "expect"
CASES = sorted(p for tool in ("where", "done") for p in (EXPECT / tool).glob("*/") if (p / "case.yaml").is_file())
OFFLINE = {"where.py": (where.main, ["--no-git"]), "done.py": (done.main, ["--no-git", "--no-live"])}


def run(case: Path) -> tuple[str, int, str]:
    cmd = (case / "expect.txt").read_text(encoding="utf-8").split("\n", 1)[0][2:]
    args = shlex.split(cmd)
    main, offline = OFFLINE[args[0]]
    tmp = Path(tempfile.mkdtemp(prefix="map-state-"))
    try:
        root = spoiled(case, tmp)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(offline + ["--root", str(root)] + args[1:])
        return cmd, rc, out.getvalue()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.parametrize("case", CASES, ids=[f"{c.parent.name}/{c.name}" for c in CASES])
def test_state(case: Path) -> None:
    text = (case / "expect.txt").read_text(encoding="utf-8")
    _, second, body = text.split("\n", 2)
    _, rc, out = run(case)
    assert out == body, f"{case.parent.name}/{case.name}: вывод разошёлся с expect.txt"
    assert rc == int(second.rsplit(" ", 1)[1]), f"{case.name}: код выхода {rc}"


if __name__ == "__main__":
    if "--update" in sys.argv:
        for c in CASES:
            cmd, rc, out = run(c)
            (c / "expect.txt").write_text(f"$ {cmd}\n# код выхода {rc}\n{out}", encoding="utf-8", newline="\n")
            print(f"{c.parent.name}/{c.name}: {rc}")
    else:
        print(__doc__)
