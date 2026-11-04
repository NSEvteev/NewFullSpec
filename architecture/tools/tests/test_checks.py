"""Тест проверок карты: на чистой проверочной карте все молчат, на каждой испорченной срабатывает своя.

Зачем. Проверка, которая перестала срабатывать, молчит так же, как проверка, которой не на что ругаться, — разницу
видно только на порче. А проверка, которая начала срабатывать зря, видна на чистой карте. Две стороны держат
проверки честными.

Испорченная карта — папка tools/samples/bad/<номер>-<что>/ с двумя файлами:
  case.yaml   — что испортить в копии чистой карты tools/samples/good/: replace — замены «old → new» в файлах (old
                должен встретиться ровно один раз), add — новые файлы целиком, remove — файлы, которые удалить;
                пути — от good/. Шапка-комментарий — что портится и какая проверка обязана сработать;
  expect.txt  — все сообщения проверок на этой карте, по строке: «ошибка: …» и «предупреждение: …».
Тест собирает копию во временной папке, портит, запускает модель (mapmodel.py) и проверки (checks.py) и сравнивает
сообщения с expect.txt строка в строку: лишнее сообщение — тоже расхождение.

Как прогнать (из корня репо):
  python -m pytest architecture/tools/tests/test_checks.py -q
  python architecture/tools/tests/test_checks.py --update   — переписать все expect.txt текущими сообщениями;
                                                                   потом прочитать git diff глазами
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import checks  # noqa: E402
import tobe_checks  # noqa: E402
from mapmodel import ChangeModel, MapModel, world_lines  # noqa: E402

GOOD = TOOLS / "samples" / "good"
BAD = TOOLS / "samples" / "bad"
CASES = sorted(p for p in BAD.glob("*/") if (p / "case.yaml").is_file())


def messages(root: Path, tobe: bool = False) -> list[str]:
    """Сообщения проверок карты; с tobe — ещё «как будет» (№25: карты 25-*). Порча «как есть» в других картах
    иначе дала бы в каждой лишнее «копия разошлась»."""
    m = MapModel(root)
    r = checks.run(m)
    out = [f"ошибка: {e}" for e in m.errors + r.errors]
    if tobe:
        chg = ChangeModel(root, m)
        out += [f"ошибка «как будет»: {e}" for e in chg.errors + tobe_checks.run(m, chg).errors]
    return out + [f"предупреждение: {w}" for w in m.warnings + r.warnings]


def spoiled(case: Path, tmp: Path) -> Path:
    """Копия чистой карты, испорченная по case.yaml; возвращает корень карты."""
    dst = tmp / "good"
    shutil.copytree(GOOD, dst, ignore=shutil.ignore_patterns("*.html", "keys.js", "_shared", "expect"))
    spec = yaml.safe_load((case / "case.yaml").read_text(encoding="utf-8")) or {}
    for rel in spec.get("remove") or []:  # путь или шаблон: architecture/TOBE/**/*.md
        hits = [p for p in dst.glob(rel) if p.is_file()]
        assert hits, f"{case.name}: удалять нечего — {rel}"
        for p in hits:
            p.unlink()
    for ch in spec.get("replace") or []:  # all: true — все вхождения во всех файлах по шаблону file
        total = 0
        for p in sorted(p for p in dst.glob(ch["file"]) if p.is_file()):
            text = p.read_text(encoding="utf-8")
            n = text.count(ch["old"])
            if not ch.get("all"):
                assert n == 1, f"{case.name}: в {ch['file']} «old» встречается {n} раз"
            total += n
            p.write_text(text.replace(ch["old"], ch["new"]), encoding="utf-8", newline="\n")
        assert total, f"{case.name}: «{ch['old'][:40]}» нет в {ch['file']}"
    for rel, content in (spec.get("add") or {}).items():
        p = dst / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
    if spec.get("close"):  # «закрыто»: копии «как будет» без пометок — на место «как есть»
        tobe = dst / "architecture" / "TOBE"
        for p in sorted(tobe.rglob("*.md")):
            rel = p.relative_to(tobe).as_posix()
            if rel in ("README.md", "blocks.md") or rel.endswith("tasks.md"):
                continue
            world, _ = world_lines(p.read_text(encoding="utf-8").split("\n"))
            out = dst / "architecture" / "ASIS" / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(world), encoding="utf-8", newline="\n")
    return dst / "architecture"


def run_case(case: Path) -> list[str]:
    tmp = Path(tempfile.mkdtemp(prefix="map-bad-"))
    try:
        return messages(spoiled(case, tmp), tobe=case.name.startswith("25-"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_good_map_is_silent() -> None:
    assert messages(GOOD / "architecture", tobe=True) == []


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_bad_map_fires(case: Path) -> None:
    expected = (case / "expect.txt").read_text(encoding="utf-8").splitlines()
    got = run_case(case)
    assert got, f"{case.name}: ни одна проверка не сработала"
    assert got == expected, f"{case.name}: сообщения разошлись с expect.txt"


def test_every_rule_has_a_bad_map() -> None:
    covered = {int(c.name.split("-", 1)[0]) for c in CASES}
    missing = sorted({1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 25} - covered)
    assert not missing, f"нет испорченной карты для проверок: {missing}"


if __name__ == "__main__":
    if "--update" in sys.argv:
        for c in CASES:
            got = run_case(c)
            (c / "expect.txt").write_text("\n".join(got) + "\n", encoding="utf-8", newline="\n")
            print(f"{c.name}: {len(got)}")
    else:
        print(__doc__)
