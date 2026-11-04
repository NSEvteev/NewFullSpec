"""Тест инструментов на пустой карте: новый проект из шаблона и его первое изменение.

Зачем. В новом проекте реестр сервисов пуст, а первый сервис приходит первым изменением. Инструменты, написанные на живой
карте, легко считают это невозможным: однажды find.py и where.py отказывались работать с открытым изменением на пустой карте,
extract.py --all падал на пустом реестре, а map.py портил доску, дописывая узел под «nodes: {}».

Что проверяет. Команды на временной карте, собранной из настроек проверочной карты и пустых реестра и доски.

Как прогнать (из корня репо):  python -m pytest architecture/tools/tests/test_new_project.py -q
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

TOOLS = Path(__file__).resolve().parent.parent
GOOD = TOOLS / "samples" / "good" / "architecture"
sys.path.insert(0, str(TOOLS))

from map import board_with_node  # noqa: E402

COVER = "# Первый сервис\n\nСервиса ещё нет.\n\nВетка: change/first\n\n## Решения\n"


def run(tool: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOLS / tool), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


@pytest.fixture
def empty_map(tmp_path: Path) -> Path:
    root = tmp_path / "architecture"
    (root / "project").mkdir(parents=True)
    (root / "TOBE").mkdir()
    shutil.copy(GOOD / "project" / "settings.yaml", root / "project" / "settings.yaml")
    (root / "project" / "services.yaml").write_text("# пусто\n", encoding="utf-8")
    (root / "project" / "board.yaml").write_text("# пусто\nnodes: {}\n", encoding="utf-8")
    return root


def test_map_builds_and_checks_empty(empty_map: Path) -> None:
    built = run("build.py", "--root", str(empty_map))
    assert built.returncode == 0, built.stdout + built.stderr
    assert (empty_map / "ASIS" / "README.md").is_file()
    assert run("build.py", "--check", "--root", str(empty_map)).returncode == 0


def test_facts_on_empty_registry_are_not_an_error(empty_map: Path) -> None:
    res = run("extract.py", "--all", "--check", "--root", str(empty_map))
    assert res.returncode == 0, res.stdout + res.stderr


def test_live_check_on_empty_registry(empty_map: Path) -> None:
    run("build.py", "--root", str(empty_map))
    res = run("live.py", "--root", str(empty_map))
    assert res.returncode == 0, res.stdout + res.stderr


def test_first_change_opens_on_empty_map(empty_map: Path) -> None:
    run("build.py", "--root", str(empty_map))  # шаблон приходит с собранной пустой картой
    (empty_map / "TOBE" / "README.md").write_text(COVER, encoding="utf-8")
    where = run("where.py", "--root", str(empty_map), "--no-git")
    assert where.returncode == 0, where.stdout + where.stderr
    assert "пуста" not in where.stdout + where.stderr
    find = run("find.py", "--list", "--root", str(empty_map))
    assert "пуста" not in find.stdout + find.stderr


@pytest.mark.parametrize("board", ["# шапка\nnodes: {}\n", "# шапка\nnodes:\n", "nodes:\n  web: [1, 2]\n"])
def test_first_node_keeps_board_readable(board: str) -> None:
    text = board_with_node(board, "orders", [2, 2])
    nodes = yaml.safe_load(text)["nodes"]
    assert nodes["orders"] == [2, 2]
    if "web" in board:
        assert nodes["web"] == [1, 2]
    assert text.startswith(board.split("\n")[0])
