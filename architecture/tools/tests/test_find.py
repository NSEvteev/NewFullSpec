"""Тест find.py: ответы на проверочной карте good сверяются с ожидаемыми файлами строка в строку.

Зачем. Поиск должен отвечать одинаково и полно: правка find.py или общего разбора карты (mapmodel.py), которая
поменяла ответ, видна сразу — тест называет файл ответа, который разошёлся, и показывает разницу.

Что сверяет. Каждый файл tools/samples/good/expect/find/*.txt: в строке 1 — команда, в строке 2 — код выхода,
дальше — ожидаемый stdout. Строение файла, как добавить случай и что делать, если разошлись многие ответы, —
tools/samples/good/expect/README.md. find.py зовётся с --root на проверочную карту good.

Как прогнать (из корня репо):
  python -m pytest architecture/tools/tests/test_find.py -q          все случаи; один — -k 01-key-method
  python architecture/tools/tests/test_find.py --update               переписать ВСЕ файлы текущим выводом;
                                                                          потом прочитать git diff глазами
"""

from __future__ import annotations

import contextlib
import io
import shlex
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import find  # noqa: E402

MAP = TOOLS / "samples" / "good" / "architecture"
EXPECT = TOOLS / "samples" / "good" / "expect" / "find"


def run(cmd: str) -> tuple[int, str]:
    args = shlex.split(cmd)
    assert args[0] == "find.py", cmd
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = find.main(["--root", str(MAP)] + args[1:])
    return rc, out.getvalue()


def read_case(p: Path) -> tuple[str, int, str]:
    text = p.read_text(encoding="utf-8")
    first, second, body = text.split("\n", 2)
    assert first.startswith("$ "), f"{p.name}: первая строка — «$ find.py …»"
    assert second.startswith("# код выхода "), (
        f"{p.name}: вторая строка — «# код выхода N»"
    )
    return first[2:], int(second.rsplit(" ", 1)[1]), body


CASES = sorted(EXPECT.glob("*.txt"))


@pytest.mark.parametrize("case", CASES, ids=[p.stem for p in CASES])
def test_answer(case: Path) -> None:
    cmd, rc_expected, body = read_case(case)
    rc, out = run(cmd)
    assert out == body, f"{case.name}: ответ разошёлся с ожидаемым"
    assert rc == rc_expected, f"{case.name}: код выхода {rc}, ожидался {rc_expected}"


def test_cases_exist() -> None:
    assert len(CASES) >= 20, "ожидаемых ответов меньше, чем режимов и случаев find.py"


def update() -> None:
    for p in CASES:
        cmd, _, _ = read_case(p)
        rc, out = run(cmd)
        p.write_text(
            f"$ {cmd}\n# код выхода {rc}\n{out}", encoding="utf-8", newline="\n"
        )
        print(f"{p.name}: {rc}")


if __name__ == "__main__":
    if "--update" in sys.argv:
        update()
    else:
        print(__doc__)
