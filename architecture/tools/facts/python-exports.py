"""Часть фактов «python-exports»: что общий пакет на Python даёт наружу — имена из __all__ и их подписи.

Зачем. В exports.md у функции или класса — договор словами (что делает, аргументы со смыслом, ошибки). Есть ли имя
вообще, его подпись и строка объявления — отсюда; проверка находит имя без раздела и раздел без имени.

Что читает. __init__.py в папке package реестра: список __all__; для каждого имени — его объявление в самом
__init__.py или в модуле пакета, откуда оно импортировано (from .модуль import имя или from <пакет>.модуль import
имя). Ещё — открытые модули пакета (файлы *.py без «_» в начале имени) со своим __all__: имена оттуда, которых нет
в __all__ пакета, подключают из модуля (`from shared.auth.correlation_id import CorrelationIdMiddleware`).

Раздел .facts.json:
  all_ref      строка __all__ (пусто — __all__ нет: тогда наружу ничего не объявлено)
  exports[]    name; kind — function, class или value; signature — подпись функции или конструктора класса
               (аргументы с типами и умолчаниями, «-> тип» ответа); ref — строка объявления (пусто — не нашлось);
               module — только у имени из __all__ модуля, а не пакета: имя модуля, откуда его подключают

Чего не делает. Пакеты на других языках не разбирает (нужна своя часть).
"""

from __future__ import annotations

import ast
from pathlib import Path

from facts._base import Ctx, diff, parse


def _import_name(ctx: Ctx) -> str:
    """Имя пакета для импорта — как в части python-imports: путь после последней папки с дефисом, через точки."""
    tail: list[str] = []
    for part in reversed(ctx.rel(ctx.package).split("/")):
        if not part.isidentifier():
            break
        tail.insert(0, part)
    return ".".join(tail)


def _signature(fn: ast.FunctionDef | ast.AsyncFunctionDef, skip_self: bool = False) -> str:
    args = fn.args
    if skip_self and args.args and args.args[0].arg in ("self", "cls"):
        args = ast.arguments(posonlyargs=args.posonlyargs, args=args.args[1:], vararg=args.vararg,
                             kwonlyargs=args.kwonlyargs, kw_defaults=args.kw_defaults, kwarg=args.kwarg,
                             defaults=args.defaults)
    sig = f"({ast.unparse(args)})"
    return sig + (f" -> {ast.unparse(fn.returns)}" if fn.returns is not None else "")


def _find(tree: ast.Module, name: str) -> ast.AST | None:
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
            return n
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == name for t in n.targets):
            return n
        if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == name:
            return n
    return None


def _describe(ctx: Ctx, path: Path, node: ast.AST) -> dict:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return {"kind": "function", "signature": _signature(node), "ref": ctx.ref(path, node.lineno)}
    if isinstance(node, ast.ClassDef):
        init = next((n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
        return {"kind": "class", "signature": _signature(init, skip_self=True) if init else "",
                "ref": ctx.ref(path, node.lineno)}
    return {"kind": "value", "signature": "", "ref": ctx.ref(path, node.lineno)}


def extract(ctx: Ctx) -> dict:
    init = ctx.package / "__init__.py"
    tree = parse(init) if init.is_file() else None
    if not tree:
        return {"all_ref": "", "exports": []}
    names, all_ref = [], ""
    for n in tree.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            tgt = n.targets[0] if isinstance(n, ast.Assign) else n.target
            if getattr(tgt, "id", "") == "__all__" and isinstance(n.value, (ast.List, ast.Tuple)):
                names = [e.value for e in n.value.elts if isinstance(e, ast.Constant)]
                all_ref = ctx.ref(init, n.lineno)
    own = _import_name(ctx)
    imported: dict[str, str] = {}  # имя → модуль пакета, откуда импортировано
    for n in tree.body:
        if not isinstance(n, ast.ImportFrom) or not n.module:
            continue
        sub = n.module if n.level == 1 else (n.module[len(own) + 1:] if own and n.module.startswith(own + ".") else "")
        for a in n.names:
            if sub:
                imported[a.asname or a.name] = sub
    exports = []
    for name in names:
        node, path = _find(tree, name), init
        if node is None and name in imported:
            path = ctx.package / (imported[name].replace(".", "/") + ".py")
            sub = parse(path) if path.is_file() else None
            node = _find(sub, name) if sub else None
        exports.append({"name": name, **(_describe(ctx, path, node) if node else {"kind": "", "signature": "", "ref": ""})})
    for path in sorted(ctx.package.glob("*.py")):
        if path.name.startswith("_"):
            continue
        sub = parse(path)
        for name in _all(sub) if sub else []:
            node = _find(sub, name)
            if name not in names and node:
                exports.append({"name": name, **_describe(ctx, path, node), "module": path.stem})
    return {"all_ref": all_ref, "exports": exports}


def _all(tree: ast.Module) -> list[str]:
    """Имена из __all__ модуля (нет __all__ — пусто: модуль наружу ничего не объявил)."""
    for n in tree.body:
        tgt = n.targets[0] if isinstance(n, ast.Assign) else n.target if isinstance(n, ast.AnnAssign) else None
        if getattr(tgt, "id", "") == "__all__" and isinstance(n.value, (ast.List, ast.Tuple)):
            return [e.value for e in n.value.elts if isinstance(e, ast.Constant)]
    return []


def compare(old: dict, new: dict) -> list[str]:
    return diff(old, new, "python-exports", ids={"exports": "name"})
