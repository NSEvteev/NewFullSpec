"""Часть фактов «postgres»: своя база сервиса — таблицы, колонки, типы, описания колонок, уникальные ключи, строки.

Зачем. В storage.md у таблицы — что она хранит словами, у колонки — раздел, только если описания в базе мало. Сами
колонки, их типы, обязательность, умолчание, описание и число строк — отсюда; генератор ставит их на страницу,
проверка находит таблицу без раздела и числовую колонку без единицы.

Что читает.
  - адрес базы — настройка DATABASE_URL сервиса (другое имя — поле database реестра) из раздела pydantic-settings:
    пользователь, хост, имя базы; контейнер базы — <проект compose>-<хост>-1;
  - живую базу — через psql в контейнере, только select: колонки (information_schema), уникальные индексы
    (pg_indexes), число строк каждой таблицы;
  - модели в коде (SQLAlchemy: __tablename__, mapped_column / Column с comment) — строка таблицы и колонки в коде и
    описание колонки, если в базе его нет.
NEEDS: pydantic-settings (адрес базы).

Раздел .facts.json:
  setting, setting_ref        какая настройка дала адрес и где её значение
  user, host, db, container   куда ходили (пароль не пишется)
  live                        удалось ли прочитать живую базу (нет — reason: почему; тогда колонки — только из кода)
  rows_at                     дата, на которую посчитаны строки
  tables[]                    name, ref — строка модели; in_db, in_code — есть ли в базе и в коде; rows — строк на
                              rows_at; uniques — уникальные индексы, кроме индекса по одному id (как в базе: CREATE
                              UNIQUE INDEX …); columns[] — name, type (короткое имя типа), nullable, default, comment
                              (описание в модели, comment=), db_comment (описание в самой базе; пусто — его там нет),
                              ref — строка колонки в модели
  Служебная таблица миграций alembic_version сюда не входит — её применённая версия в разделе alembic.

Чего не делает. Ничего не пишет в базу; базы, которую читают через общий пакет, не описывает (её описывает хозяин).
"""

from __future__ import annotations

import ast
import datetime as dt
import re

from facts._base import CODE_EXTS_PY, Ctx, code_files, compose_paths, diff, parse, psql

NEEDS = ("pydantic-settings",)
DB_URL = re.compile(r"postgres(?:ql)?(?:\+\w+)?://(?P<user>[^:@/]+)(?::[^@]*)?@(?P<host>[\w.-]+)(?::\d+)?/(?P<db>\w+)")
TYPE_SHORT = {"character varying": "varchar", "timestamp with time zone": "timestamptz",
              "timestamp without time zone": "timestamp", "double precision": "float8", "USER-DEFINED": "enum"}


def coords(ctx: Ctx) -> dict | None:
    """Куда ходить за базой: из значения настройки адреса базы."""
    name = ctx.info.get("database", "DATABASE_URL")
    items = (ctx.facts.get("pydantic-settings") or {}).get("settings", [])
    item = next((s for s in items if s["name"] == name), None)
    if not item or not item["value"]:
        return None
    m = DB_URL.search(item["value"])
    if not m:
        return None
    _, _, project = compose_paths(ctx)
    return {"setting": name, "setting_ref": item["source_ref"] or item["ref"], "user": m["user"], "host": m["host"],
            "db": m["db"], "container": f"{project}-{m['host']}-1"}


def model_index(ctx: Ctx) -> dict[str, dict]:
    """Таблицы моделей: __tablename__ и колонки, в том числе унаследованные от примесей."""
    classes: dict[str, dict] = {}
    for p in code_files(ctx.package, CODE_EXTS_PY):
        tree = parse(p)
        if not tree:
            continue
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            tname, tref, cols = None, None, {}
            for st in cls.body:
                if isinstance(st, ast.FunctionDef) and any(
                    getattr(d, "id", getattr(d, "attr", "")) == "declared_attr" for d in st.decorator_list
                ):
                    call = next((n for n in ast.walk(st) if isinstance(n, ast.Call)
                                 and getattr(n.func, "id", getattr(n.func, "attr", "")) in ("mapped_column", "Column")), None)
                    if call is not None:
                        c = {k.arg: k.value for k in call.keywords}.get("comment")
                        cols[st.name] = {"comment": c.value if isinstance(c, ast.Constant) else "", "ref": ctx.ref(p, st.lineno)}
                    continue
                if isinstance(st, ast.Assign) and getattr(st.targets[0], "id", "") == "__tablename__" \
                        and isinstance(st.value, ast.Constant):
                    tname, tref = st.value.value, ctx.ref(p, st.lineno)
                target, value = None, None
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    target, value = st.target.id, st.value
                elif isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name):
                    target, value = st.targets[0].id, st.value
                if target and isinstance(value, ast.Call) and \
                        getattr(value.func, "id", getattr(value.func, "attr", "")) in ("mapped_column", "Column"):
                    cname = target
                    if value.args and isinstance(value.args[0], ast.Constant) and isinstance(value.args[0].value, str):
                        cname = value.args[0].value
                    c = {k.arg: k.value for k in value.keywords}.get("comment")
                    cols[cname] = {"comment": c.value if isinstance(c, ast.Constant) else "", "ref": ctx.ref(p, st.lineno)}
            classes[cls.name] = {"table": tname, "ref": tref, "columns": cols,
                                 "bases": [getattr(b, "id", getattr(b, "attr", "")) for b in cls.bases]}

    def all_cols(name: str, seen: set) -> dict:
        c = classes.get(name)
        if not c or name in seen:
            return {}
        seen.add(name)
        out: dict = {}
        for b in c["bases"]:
            out.update(all_cols(b, seen))
        out.update(c["columns"])
        return out

    return {c["table"]: {"ref": c["ref"], "columns": all_cols(n, set())} for n, c in classes.items() if c["table"]}


def extract(ctx: Ctx) -> dict:
    co = coords(ctx)
    if not co:
        return {"live": False, "reason": "нет адреса базы Postgres в настройках сервиса"}
    out = dict(co)
    models = model_index(ctx)
    c, u, d = co["container"], co["user"], co["db"]
    try:
        cols = psql(c, u, d, "select table_name, column_name, data_type, is_nullable, coalesce(column_default,'') "
                             "from information_schema.columns c where table_schema='public' and exists (select 1 from "
                             "information_schema.tables t where t.table_schema='public' and t.table_name=c.table_name "
                             "and t.table_type='BASE TABLE') order by table_name, ordinal_position")
        idx = psql(c, u, d, "select tablename, indexdef from pg_indexes where schemaname='public' "
                            "and indexdef like 'CREATE UNIQUE%'")
        db_comments = {(t, col): text for t, col, text in (
            r + [""] * (3 - len(r)) for r in psql(c, u, d,
                "select cl.relname, a.attname, d.description from pg_description d "
                "join pg_class cl on cl.oid = d.objoid join pg_namespace n on n.oid = cl.relnamespace "
                "join pg_attribute a on a.attrelid = cl.oid and a.attnum = d.objsubid "
                "where n.nspname = 'public' and d.objsubid > 0"))}
        out["live"] = True
    except Exception as e:  # noqa: BLE001
        out["live"] = False
        out["reason"] = f"живая база недоступна: {e}"
        cols, idx, db_comments = [], [], {}
    out["rows_at"] = dt.date.today().isoformat()
    live: dict[str, list] = {}
    for t, col, typ, nul, dflt in (r + [""] * (5 - len(r)) for r in cols):
        live.setdefault(t, []).append((col, typ, nul, dflt))
    tables = []
    for t in sorted((set(live) | set(models)) - {"alembic_version"}):
        m = models.get(t, {"ref": "", "columns": {}})
        rows = None
        if t in live:
            try:
                rows = int(psql(c, u, d, f'select count(*) from "{t}"')[0][0])
            except Exception:  # noqa: BLE001
                rows = None
        columns = []
        for col, typ, nul, dflt in live.get(t, []):
            mc = m["columns"].get(col, {"comment": "", "ref": ""})
            columns.append({"name": col, "type": TYPE_SHORT.get(typ, typ), "nullable": nul == "YES",
                            "default": dflt.replace("::character varying", "").replace("::text", ""),
                            "comment": mc["comment"], "db_comment": db_comments.get((t, col), ""), "ref": mc["ref"]})
        if t not in live:  # только в коде: база не поднята или таблицы в ней нет
            columns = [{"name": k, "type": "", "nullable": None, "default": "", "comment": v["comment"], "ref": v["ref"]}
                       for k, v in m["columns"].items()]
        uniques = [r[1] for r in idx if r and r[0] == t and not r[1].endswith("(id)")]
        tables.append({"name": t, "ref": m["ref"], "in_db": t in live, "in_code": t in models, "rows": rows,
                       "uniques": uniques, "columns": columns})
    out["tables"] = tables
    return out


def compare(old: dict, new: dict) -> list[str]:
    return diff(old, new, "postgres", ignore=frozenset({"rows", "rows_at"}), ids={"tables": "name", "columns": "name"})
