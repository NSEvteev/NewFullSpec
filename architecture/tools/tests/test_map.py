"""Тесты модели карты и генератора на чистой проверочной карте tools/samples/good/.

Зачем. Модель и генератор должны видеть карту одинаково и собирать её одинаково на любой машине. Чистая карта —
эталон: на ней ошибок разбора нет, производное (кто вызывает, кто пишет и читает) известно заранее,
обзор системы совпадает с ожидаемым файлом, а две сборки подряд дают байт в байт одно и то же.
Испорченная копия карты должна давать ошибки — иначе проверка «ослепла».

Как прогнать (из корня репо):  python -m pytest architecture/tools/tests -q
Ничего не пишет в репо: сборка идёт в памяти, порча — во временной копии.
"""

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))

import map as map_cmd  # noqa: E402
from build import STAMP_RE, Site  # noqa: E402
from mapmodel import ChangeModel, MapModel, code_gaps  # noqa: E402

GOOD = TOOLS / "samples" / "good"
ROOT = GOOD / "architecture"


def model() -> MapModel:
    return MapModel(ROOT)


def test_clean_map_has_no_errors():
    assert model().errors == []


def test_entities_and_links():
    m = model()
    assert m.services == ["web", "orders"]
    assert m.get("orders", "POST /api/v1/orders").kind == "метод"
    assert m.get("orders", "orders.status").kind == "колонка"
    assert m.get("orders", "orders.created_at").extra.get(
        "facts_only"
    )  # колонка без раздела — ключ из фактов
    assert m.get("orders", "p-no-retry").kind == "проблема"
    assert [a.number for a in m.arrows["order-create"]] == [
        "1.1",
        "1.2",
        "1.3",
        "2.1",
        "2.2",
        "2.3",
    ]


def test_derived_callers_steps_writers():
    m = model()
    callers = m.callers("orders", "POST /api/v1/orders")
    assert [c["who"] for c in callers] == ["web"]
    assert [c["via"] for c in m.callers("orders", "GET /api/v1/orders/{order_id}")] == [
        "вручную"
    ]
    assert [s.anchor for s in m.steps_handling("orders", "POST /api/v1/orders")] == [
        "accept",
        "row",
        "charge",
    ]
    wr = m.writers_readers("orders", "orders.status")
    assert {ln.src for ln in wr["пишет"]} == {
        "orders/order-create#charge",
        "orders/own#stale",
    }
    assert {ln.src for ln in wr["через таблицу"]} == {
        "orders/order-create#row",
        "GET /api/v1/orders/{order_id}",
    }


def test_overview_matches_expected_file():
    site = Site(model())
    site.build_overview()
    assert site.pages["ASIS/README.md"] == (ROOT / "ASIS" / "README.md").read_text(
        encoding="utf-8"
    )


def test_build_is_deterministic():
    a, b = Site(model()), Site(model())
    a.build_all()
    b.build_all()
    assert set(a.pages) == set(b.pages)
    for k in a.pages:
        assert STAMP_RE.sub("", a.pages[k]) == STAMP_RE.sub("", b.pages[k]), k


def test_change_world_and_pages():
    """«Как будет» проверочной карты: правки разобраны, мир «как будет» чист, нумерация стрелок новая, уходящее ушло;
    генератор собирает обложку, доску и страницы задетых сервисов и процесса в TOBE/."""
    c = ChangeModel(ROOT)
    assert c.open and c.errors == [] and c.world.errors == []
    kinds = {}
    for b in c.blocks:
        kinds[b.kind] = kinds.get(b.kind, 0) + 1
    assert kinds == {"новое": 10, "меняется": 9, "уходит": 4}
    assert [(a.number, a.id) for a in c.world.arrows["order-create"]] == [
        ("1.1", "click"),
        ("1.2", "submit"),
        ("1.3", "row"),
        ("2.1", "charge"),
        ("2.2", "paid"),
        ("3.1", "poll"),
        ("3.2", "status"),
    ]
    assert c.world.get("orders", "p-no-retry") is None
    assert c.world.get("web", "web/order-create#show") is None
    assert c.world.get("web", "web/order-create#poll").kind == "шаг"
    assert c.services() == ["web", "orders"] and c.processes() == ["order-create"]
    site = Site(model())
    site.build_all()
    assert {p for p in site.pages if p.startswith("TOBE/")} == {
        "TOBE/index.html",
        "TOBE/01_service-map.html",
        "TOBE/web/index.html",
        "TOBE/orders/index.html",
        "TOBE/_processes/order-create.html",
    }
    page = site.pages["TOBE/_processes/order-create.html"]
    assert 'id="a-show"' in page and "chg-gone" in page  # уходящая стрелка — на месте, зачёркнута


def test_broken_copy_gives_errors(tmp_path):
    copy = tmp_path / "good"
    shutil.copytree(GOOD, copy)
    asis = copy / "architecture" / "ASIS"
    sl = asis / "orders" / "processes" / "order-create.md"
    sl.write_text(
        sl.read_text(encoding="utf-8")
        .replace("пишет [[orders]]", "пишет [[order]]")
        .replace("service.py:18`", "service.py:99`"),
        encoding="utf-8",
    )
    pr = asis / "_processes" / "order-create.md"
    pr.write_text(
        pr.read_text(encoding="utf-8").replace(
            "| база | orders#row |", "| запросик | orders#row |"
        ),
        encoding="utf-8",
    )
    errs = "\n".join(MapModel(copy / "architecture").errors)
    assert "ключ [[order]] у orders не найден" in errs
    assert "нет строки 99" in errs
    assert "вид стрелки «запросик» не из списка" in errs


def test_new_file_in_change(tmp_path):
    """Новый файл «как будет»: первая строка «Правка: c-… · статус», вторая «Почему:» — правка «новое» на весь
    файл; в мире «как будет» этих строк нет. Без строки «Правка:» — ошибка."""
    copy = tmp_path / "good"
    shutil.copytree(GOOD, copy, ignore=shutil.ignore_patterns("*.html", "keys.js", "_shared", "expect"))
    root = copy / "architecture"
    new = root / "TOBE" / "web" / "own.md"
    new.write_text(
        "Правка: c-web-own · предложено\nПочему: [[d-poll]]\n\n"
        "Что страница делает сама: при открытии проверяет незавершённый заказ.\n\n"
        "## Проверяет незавершённый заказ {#pending}\n\n"
        "При открытии страницы смотрит, есть ли номер в [[pending-order]].\n"
        "Справочник: читает [[pending-order]]\n",
        encoding="utf-8",
    )
    c = ChangeModel(root)
    b = next(b for b in c.blocks if b.number == "c-web-own")
    assert (b.kind, b.status, b.what, b.why) == ("новое", "предложено", "файл", "[[d-poll]]")
    assert c.errors == [] and c.world.errors == []
    own = c.world.own["web"]
    assert own.text[0].startswith("Что страница делает сама") and "Правка" not in " ".join(own.text)
    new.write_text("Что страница делает сама.\n", encoding="utf-8")
    assert any("без первой строки «Правка:" in e for e in ChangeModel(root).errors)


def test_gone_in_world(tmp_path):
    """«Уходит» в мире «как будет»: метод, чей раздел ушёл целиком, снят и с фактов мира (код его удалит, а факты
    ещё сняты с кода «как есть»); срез, ушедший целиком, в мире отсутствует, а не пустой файл."""
    copy = tmp_path / "good"
    shutil.copytree(GOOD, copy, ignore=shutil.ignore_patterns("*.html", "keys.js", "_shared", "expect"))
    root = copy / "architecture"
    methods = root / "TOBE" / "orders" / "methods.md"
    text = methods.read_text(encoding="utf-8")
    head = "## GET /api/v1/orders/{order_id}"
    start = text.index(head)
    end = text.find("\n## ", start + 1)
    end = len(text) if end < 0 else end + 1
    section = text[start:end].rstrip("\n")
    methods.write_text(
        text[:start] + f"::: уходит c-ord-get-gone · предложено\n{section}\nПочему: [[d-poll]]\n:::\n" + text[end:],
        encoding="utf-8",
    )
    sl = root / "TOBE" / "orders" / "processes" / "order-create.md"
    body = (root / "ASIS" / "orders" / "processes" / "order-create.md").read_text(encoding="utf-8").rstrip("\n")
    sl.write_text(f"::: уходит c-ord-slice-gone · предложено\n{body}\nПочему: [[d-poll]]\n:::\n", encoding="utf-8")
    c = ChangeModel(root)
    world_methods = [f"{x['method']} {x['path']}" for x in c.world.facts["orders"]["fastapi-openapi"]["methods"]]
    assert "GET /api/v1/orders/{order_id}" not in world_methods and "POST /api/v1/orders" in world_methods
    assert ("orders", "order-create") not in c.world.slices
    assert not any("order-create.md:1 — нет первого абзаца" in e for e in c.world.errors)
    proc = root / "TOBE" / "_processes" / "order-create.md"
    body = (root / "ASIS" / "_processes" / "order-create.md").read_text(encoding="utf-8").rstrip("\n")
    proc.write_text(f"::: уходит c-oc-gone · предложено\n{body}\nПочему: [[d-poll]]\n:::\n", encoding="utf-8")
    c = ChangeModel(root)
    assert not (c.world.root / "ASIS" / "_processes" / "order-create.md").exists()
    assert not any("_processes/order-create.md" in e for e in c.world.errors)


def test_gone_command(tmp_path):
    """map.py gone: раздел «как есть» — блоком «уходит» в копии, байт в байт, со статусом самого слабого решения;
    ушедшая настройка снята с фактов мира; весь файл — из чистой копии, которую команда делает сама; занятый номер,
    решение не с обложки, разделы не подряд и раздел внутри чужой правки — отказ."""
    copy = tmp_path / "good"
    shutil.copytree(GOOD, copy, ignore=shutil.ignore_patterns("*.html", "keys.js", "_shared", "expect"))
    root = copy / "architecture"
    out = map_cmd.gone(root, [("c-ord-get-gone", "d-retry,d-poll", "ASIS/orders/methods.md#GET /api/v1/orders/{order_id}"),
                              ("c-ord-db-gone", "d-retry", "ASIS/orders/settings.md#DATABASE_URL"),
                              ("c-web-p-gone", "d-poll", "ASIS/web/problems.md")])
    assert len(out) == 4 and out[0].startswith("уходит: TOBE/orders/methods.md:") and out[2].startswith("копия: TOBE/web/")
    text = (root / "TOBE" / "orders" / "methods.md").read_text(encoding="utf-8")
    asis = (root / "ASIS" / "orders" / "methods.md").read_text(encoding="utf-8")
    start = asis.index("## GET /api/v1/orders/{order_id}")
    end = asis.find("\n## ", start + 1)
    section = asis[start:len(asis) if end < 0 else end].rstrip("\n")
    assert f"::: уходит c-ord-get-gone · предложено\n{section}\nПочему: [[d-retry]] · [[d-poll]]\n:::" in text
    assert "::: уходит c-ord-db-gone · решено владельцем\n### DATABASE_URL" in (root / "TOBE" / "orders" / "settings.md").read_text(encoding="utf-8")
    whole = (root / "TOBE" / "web" / "problems.md").read_text(encoding="utf-8")
    assert whole.startswith("::: уходит c-web-p-gone · предложено\n") and whole.rstrip("\n").endswith("Почему: [[d-poll]]\n:::")
    c = ChangeModel(root)
    assert not [e for e in c.errors if "methods.md" in e or "settings.md" in e or "web/problems.md" in e]
    names = [s["name"] for s in c.world.facts["orders"]["pydantic-settings"]["settings"]]
    assert "DATABASE_URL" not in names and "PAYMENTS_URL" in names
    for item, why in [(("c-ord-get-gone", "d-retry", "ASIS/orders/methods.md#POST /api/v1/orders"), "номер"),
                      (("c-ord-x", "d-nope", "ASIS/orders/methods.md#POST /api/v1/orders"), "нет в требованиях"),
                      (("c-ord-y", "d-retry", "ASIS/orders/settings.md#PAYMENTS_API_KEY|MAX_ITEMS"), "не подряд"),
                      (("c-ord-z", "d-retry", "ASIS/orders/settings.md#PAYMENTS_RETRIES"), "задевают правку")]:
        with pytest.raises(map_cmd.Fail, match=why):
            map_cmd.gone(root, [item])


def test_mv_service(tmp_path):
    """map.py mv-service: папки ASIS/ и TOBE/ переименованы, имя заменено в md, реестре и фактах — карта и мир
    «как будет» разбираются без ошибок; занятое имя — отказ."""
    copy = tmp_path / "good"
    shutil.copytree(GOOD, copy, ignore=shutil.ignore_patterns("*.html", "keys.js", "_shared", "expect"))
    root = copy / "architecture"
    before = MapModel(root)
    shutil.move(str(copy / "src" / "web"), str(copy / "src" / "site"))  # код переименовал блок — до закрытия
    out = map_cmd.mv_service(root, "web", "site", [], True)
    assert out[0] == "переименую: ASIS/web → ASIS/site" and out[-1].startswith("сделано")
    assert (root / "ASIS" / "site").is_dir() and not (root / "ASIS" / "web").exists() and (root / "TOBE" / "site").is_dir()
    m = MapModel(root)
    assert "site" in m.registry and "web" not in m.registry
    assert len(m.errors) == len(before.errors)
    assert not ChangeModel(root).errors
    with pytest.raises(map_cmd.Fail, match="нет"):
        map_cmd.mv_service(root, "web", "site", [], True)


def _done_copy(tmp_path) -> Path:
    """Копия проверочной карты, где у всех блоков есть «Сделано:» — как на закрытии."""
    copy = tmp_path / "good"
    shutil.copytree(GOOD, copy, ignore=shutil.ignore_patterns("*.html", "keys.js", "_shared", "expect"))
    blocks = copy / "architecture" / "TOBE" / "blocks.md"
    text = blocks.read_text(encoding="utf-8")
    blocks.write_text(re.sub(r"(Готово, когда:[^\n]*\n)", r"\1\nСделано: 2026-10-20 · проба\n", text), encoding="utf-8")
    return copy / "architecture"


def test_code_into_change(tmp_path):
    """map.py code: «Код:» — последней строкой раздела правки (перед «Почему:»), повтор заменяет строку, текст строк
    кода — в TOBE/.anchors.json; раздел вне правок — «пропущено», несуществующая строка кода — «нельзя»."""
    root = _done_copy(tmp_path)
    out = map_cmd.code(root, [("TOBE/orders/own.md#settle", ["src/orders/orders/api.py:13"])])
    assert out and "own.md" in out[0]
    out = map_cmd.code(root, [("orders/own.md#Доводит оплату", ["src/orders/orders/payments.py:14"])])
    lines = (root / "TOBE" / "orders" / "own.md").read_text(encoding="utf-8").split("\n")
    k = lines.index("Код: `src/orders/orders/payments.py:14`")
    assert lines[k + 1].startswith("Почему:") and "Код: `src/orders/orders/api.py:13`" not in lines
    saved = json.loads((root / "TOBE" / ".anchors.json").read_text(encoding="utf-8"))
    assert saved["src/orders/orders/payments.py:14"].startswith("async def charge(")
    out = map_cmd.code(root, [("TOBE/orders/own.md#Закрывает брошенные заказы", ["src/orders/orders/api.py:13"])])
    assert out[0].startswith("пропущено:") and "вне правок" in out[0]
    out = map_cmd.code(root, [("TOBE/orders/own.md#settle", ["src/orders/orders/api.py:9999"])])
    assert out[0].startswith("нельзя:") and "строки кода нет" in out[0]
    assert map_cmd.code_items("TOBE/web/storage.md#Память браузера: pending-order → `a.py:1` · `b.py:2`\n") == [
        ("TOBE/web/storage.md#Память браузера: pending-order", ["a.py:1", "b.py:2"])]


def test_block_done(tmp_path):
    """map.py block-done: «Сделано:» последним полем у блока и задач, имя теста — перед «Проверяет:»; повтор и чужой
    ключ — отказ, при отказе файлы не меняются."""
    root = _done_copy(tmp_path)
    tasks_p, blocks_p = root / "TOBE" / "orders" / "tasks.md", root / "TOBE" / "blocks.md"
    for p in (tasks_p, blocks_p):
        p.write_text("\n".join(x for x in p.read_text(encoding="utf-8").split("\n") if not x.startswith("Сделано:")),
                     encoding="utf-8", newline="\n")
    names = tmp_path / "names.txt"
    names.write_text("t-ord-retry = test_retry_same_key\nt-ord-refused = test_refused\n", encoding="utf-8")
    before = tasks_p.read_text(encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text("t-нет-такого = test_x\n", encoding="utf-8")
    with pytest.raises(map_cmd.Fail, match="t-нет-такого"):
        map_cmd.block_done(root, "b1", "abc1234", "тесты 16", str(bad), None, False)
    assert tasks_p.read_text(encoding="utf-8") == before
    with pytest.raises(map_cmd.Fail, match="--commits"):
        map_cmd.block_done(root, "b1", "", "", None, None, False)
    with pytest.raises(map_cmd.Fail, match="блока b9"):
        map_cmd.block_done(root, "b9", "abc1234", "тесты 16", None, None, False)
    out = map_cmd.block_done(root, "b1", "abc1234 def5678", "тесты 16; вживую 202", str(names), None, False)
    assert "k-ord-retry" in out[0]
    tasks = tasks_p.read_text(encoding="utf-8").split("\n")
    head = tasks.index("### Повтор с одним ключом {#t-ord-retry}")
    block = tasks[head:tasks.index("### 202 вместо 502 {#t-ord-202}")]
    assert block.index("Тест: test_retry_same_key") + 1 == block.index(next(x for x in block if x.startswith("Проверяет:")))
    assert "Тест: test_refused" in tasks and "Тест: test_gateway_down_gives_502" not in tasks
    head = tasks.index("### Повтор списания с ключом повтора {#k-ord-retry}")
    task = tasks[head:tasks.index("### Ответ 202, если шлюз не ответил {#k-ord-202}")]
    assert [x for x in task if x.strip()][-1].startswith("Сделано: ") and task[-1] == ""
    blocks = blocks_p.read_text(encoding="utf-8").split("\n")
    field = next(x for x in blocks if x.startswith("Сделано:"))
    assert "коммиты abc1234 def5678; тесты 16; вживую 202" in field
    assert blocks.index(field) < blocks.index(next(x for x in blocks if x.endswith("{#b2}")))
    with pytest.raises(map_cmd.Fail, match="уже стоит"):
        map_cmd.block_done(root, "b1", "abc1234", "тесты 16", None, None, False)


def test_start_and_blank(tmp_path):
    """map.py start: обложка и лист из шаблонов, «как будет» читается; вторая обложка и готовый файл — отказ."""
    root = _done_copy(tmp_path)
    shutil.rmtree(root / "TOBE")
    out = map_cmd.start(root, "order-cancel", "Отмена заказа", "order-cancel", True, False)
    assert "обложка" in out[-1]
    cover = (root / "TOBE" / "README.md").read_text(encoding="utf-8")
    assert cover.startswith("# Отмена заказа\n") and "<!--" not in cover
    assert "Ветка: change/order-cancel\n" in cover and "Размер: маленькое\n" in cover
    assert "_backlog/promt-order-cancel.md" in cover and "_backlog/order-cancel/" in cover
    assert (root.parent / "_backlog" / "promt-order-cancel.md").is_file()
    assert (root.parent / "_backlog" / "order-cancel" / ".gitkeep").is_file()
    assert "в работе: ветка `change/order-cancel`" in (root.parent / "_backlog" / "CLAUDE.md").read_text(encoding="utf-8")
    assert ChangeModel(root).cover.get("Размер") == "маленькое"
    with pytest.raises(map_cmd.Fail, match="обложка уже есть"):
        map_cmd.start(root, "other", "Другое", "other", False, False)
    assert map_cmd.blank(root, "blocks", None)[0].startswith("TOBE/blocks.md")
    assert map_cmd.blank(root, "tasks", "orders")[0].startswith("TOBE/orders/tasks.md")
    with pytest.raises(map_cmd.Fail, match="уже есть"):
        map_cmd.blank(root, "blocks", None)
    with pytest.raises(map_cmd.Fail, match="ждёт сервис"):
        map_cmd.blank(root, "tasks", None)


def test_code_list_one_pass(tmp_path):
    """map.py code --from: отказ одной строки не останавливает список — годные после него записаны, отказы — в конце
    одним видом «нельзя: <копия>#<раздел>: …»."""
    root = _done_copy(tmp_path)
    out = map_cmd.code(root, [("TOBE/orders/own.md#нет такого раздела", ["src/orders/orders/api.py:13"]),
                              ("TOBE/orders/own.md#settle", ["src/orders/orders/payments.py:14"])])
    assert "own.md" in out[0] and out[-1].startswith("нельзя: TOBE/orders/own.md#нет такого раздела:")
    assert "Код: `src/orders/orders/payments.py:14`" in (root / "TOBE" / "orders" / "own.md").read_text(encoding="utf-8")


def test_code_relocate_by_text(tmp_path):
    """map.py code --relocate: следующий блок дописал строки выше — ссылка правки «как будет» переходит на строку с
    тем же текстом; повтор ничего не меняет."""
    root = _done_copy(tmp_path)
    map_cmd.code(root, [("TOBE/orders/own.md#settle", ["src/orders/orders/payments.py:14"])])
    src = root.parent / "src" / "orders" / "orders" / "payments.py"
    src.write_text("# первая вставка\n# вторая вставка\n" + src.read_text(encoding="utf-8"), encoding="utf-8")
    out = map_cmd.code_relocate(root)
    assert any("payments.py:14 → :16" in x for x in out) and out[-1].startswith("перенос ссылок «как будет»: перенесено 1")
    assert "Код: `src/orders/orders/payments.py:16`" in (root / "TOBE" / "orders" / "own.md").read_text(encoding="utf-8")
    assert map_cmd.code_relocate(root)[-1].startswith("перенос ссылок «как будет»: перенесено 0, вручную 0")


def test_code_gaps_limiter(tmp_path):
    """map.py code --gaps: ограничитель ({#lim-…}) в правке без «Код:» — пробел, как в «как есть», хотя «Значение:»
    у него нет (настройку без «Значение:» пробелом не считают — её место в фактах)."""
    root = _done_copy(tmp_path)
    p = root / "TOBE" / "orders" / "settings.md"
    p.write_text(p.read_text(encoding="utf-8").rstrip("\n") + "\n\n::: новое c-ord-lim-probe · решено владельцем\n"
                 "### заказов в минуту {#lim-probe}\nСколько: 10\nГде действует: весь сервис\nГде хранится: в памяти\n"
                 "При превышении: отказ\nПочему: [[d-retry]]\n:::\n", encoding="utf-8")
    gaps = code_gaps(ChangeModel(root))
    assert any("c-ord-lim-probe" in g and "заказов в минуту" in g for g in gaps)


def test_apply_change_to_asis(tmp_path):
    """map.py apply: рано, пока блок без «Сделано:»; без --yes — только список; с --yes — копии без пометок в «как
    есть», пустой справочник — строкой пустого файла, запомненные строки правок — в .anchors.json «как есть»;
    «как есть», разошедшийся с копией вне правок, — отказ (сначала sync)."""
    root = _done_copy(tmp_path)
    map_cmd.code(root, [("TOBE/orders/own.md#settle", ["src/orders/orders/payments.py:14"])])
    asis_own = (root / "ASIS" / "orders" / "own.md").read_text(encoding="utf-8")
    out = map_cmd.apply(root, yes=False)
    assert "перенесу: ASIS/orders/own.md" in out and (root / "ASIS" / "orders" / "own.md").read_text(encoding="utf-8") == asis_own
    out = map_cmd.apply(root, yes=True)
    assert "перенесено: ASIS/orders/own.md" in out
    for p in (root / "ASIS").rglob("*.md"):
        text = p.read_text(encoding="utf-8")
        assert ":::" not in text and "Почему:" not in text, p
    own = (root / "ASIS" / "orders" / "own.md").read_text(encoding="utf-8")
    assert "## Доводит оплату {#settle}" in own and "Код: `src/orders/orders/payments.py:14`" in own
    assert (root / "ASIS" / "orders" / "problems.md").read_text(encoding="utf-8").strip() == "проблем нет"
    remembered = json.loads((root / "ASIS" / "orders" / ".anchors.json").read_text(encoding="utf-8"))
    assert "src/orders/orders/payments.py:14" in remembered
    again = map_cmd.apply(root, yes=False)  # повтор после перерыва — переносить нечего, без «сначала sync»
    assert not any(x.startswith("перенесу") for x in again) and any(x.startswith("уже перенесено") for x in again)

    root2 = _done_copy(tmp_path / "2")
    readme = root2 / "ASIS" / "orders" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8").replace("\n\n", "\n\nНовый абзац мимо копии.\n\n", 1),
                      encoding="utf-8")
    with pytest.raises(map_cmd.Fail, match="map.py sync: ASIS/orders/README.md"):
        map_cmd.apply(root2, yes=True)

    root3 = tmp_path / "3" / "good" / "architecture"
    shutil.copytree(GOOD, root3.parent, ignore=shutil.ignore_patterns("*.html", "keys.js", "_shared", "expect"))
    with pytest.raises(map_cmd.Fail, match="без «Сделано:»"):
        map_cmd.apply(root3, yes=False)


def test_rm_change_copy(tmp_path):
    """map.py rm на путь TOBE/… удаляет копию «как будет», а «как есть» не трогает."""
    root = _done_copy(tmp_path)
    assert map_cmd.main(["rm", "TOBE/web/pages.md", "--yes", "--root", str(root)]) == 0
    assert not (root / "TOBE" / "web" / "pages.md").exists() and (root / "ASIS" / "web" / "pages.md").is_file()
