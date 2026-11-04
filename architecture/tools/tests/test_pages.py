"""Тест генератора на страницах образца: свежая сборка даёт те же страницы, что лежат в карте, кроме штампа.

Зачем. Страницы образца — первый сервис реестра и первый процесс карты — человек посмотрел и утвердил их вид. Если правка
генератора меняет такую страницу, тест падает и называет её: изменение вида становится видно до коммита, а не
после того, как его заметит человек. Задуманная правка вида — пересобрать карту (build.py) и закоммитить страницы
вместе с правкой генератора; разницу страниц читать в git diff.

Что сравнивает. Сборку всей карты в памяти (build.py, ничего не пишется) с файлами на диске — страницы из списка
PAGES; штамп (коммит и даты фактов) не сравнивается, как в build.py --check. Пока md образца правятся, тест падает
и тогда, когда страницы просто не пересобраны: это и есть его работа. В новом проекте сервисов ещё нет: страниц образца
нет, и тест пропускается сам.

Как прогнать (из корня репо):  python -m pytest architecture/tools/tests/test_pages.py -q
"""

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))

from build import STAMP_RE, Site  # noqa: E402
from mapmodel import MapModel  # noqa: E402

ROOT = TOOLS.parent  # корень карты, в которой лежат инструменты


def sample_pages() -> list[str]:
    """Образец сервиса и образец процесса (срезы всех участников) — первые в карте; карта пуста — ничего."""
    m = MapModel(ROOT)
    pages = [f"ASIS/{s}/index.html" for s in m.services[:1]]
    return pages + [f"ASIS/_processes/{p}.html" for p in list(m.processes)[:1]]


PAGES = sample_pages()


@pytest.fixture(scope="module")
def built() -> dict[str, str]:
    site = Site(MapModel(ROOT))
    site.build_all()
    return site.pages


@pytest.mark.parametrize("rel", PAGES)
def test_sample_page_unchanged(built: dict[str, str], rel: str) -> None:
    on_disk = (ROOT / rel).read_text(encoding="utf-8")
    assert rel in built, f"{rel}: генератор эту страницу больше не собирает"
    fresh, old = STAMP_RE.sub("", built[rel]).split("\n"), STAMP_RE.sub("", on_disk).split("\n")
    if fresh != old:  # без разницы pytest: на строках по сотне тысяч знаков она считается минутами
        n = next((i for i, (a, b) in enumerate(zip(fresh, old)) if a != b), min(len(fresh), len(old)))
        pytest.fail(
            f"{rel}: свежая сборка не совпала со страницей в карте со строки {n + 1} — правка генератора "
            f"поменяла вид или страница не пересобрана (build.py)"
        )
