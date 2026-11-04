"""Часть фактов «alembic»: миграции своей базы — папка, сколько их, какая применена в живой базе.

Зачем. Страница сервиса показывает миграции рядом с базой; живая проверка ловит, что код принёс миграцию, а база
её ещё не видела. Когда миграции идут и что сеют, пишется словами в первом абзаце storage.md.

Что читает. Папку versions в alembic/ или migrations/ — сначала в root реестра, потом в package; применённую
версию — select из таблицы alembic_version живой базы (куда ходить — раздел postgres). NEEDS: postgres.

Раздел .facts.json:
  dir        папка версий от корня репо (пусто — не нашлась)
  versions   сколько файлов миграций
  applied    версия, применённая в живой базе (пусто — база не прочитана или таблицы версий нет)
"""

from __future__ import annotations

from facts._base import Ctx, diff, psql

NEEDS = ("postgres",)


def extract(ctx: Ctx) -> dict:
    cands = [base / d / "versions" for base in (ctx.root, ctx.package) for d in ("alembic", "migrations")]
    mig = next((c for c in cands if c.is_dir()), None)
    out = {"dir": ctx.rel(mig) if mig else "",
           "versions": len([p for p in mig.glob("*.py") if not p.name.startswith("__")]) if mig else 0,
           "applied": ""}
    db = ctx.facts.get("postgres") or {}
    if db.get("live"):
        try:
            rows = psql(db["container"], db["user"], db["db"], "select version_num from alembic_version")
            out["applied"] = rows[0][0] if rows else ""
        except Exception:  # noqa: BLE001
            pass
    return out


def compare(old: dict, new: dict) -> list[str]:
    return diff(old, new, "alembic")
