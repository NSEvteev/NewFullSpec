"""Часть фактов «pydantic-settings»: настройки сервиса на Python — поля классов BaseSettings и чтения os.environ.

Зачем. В справочнике settings.md у каждой настройки раздел со смыслом, а значение, умолчание, откуда значение и
секрет ли — отсюда (на странице их ставит генератор). Настройку без раздела проверка находит по этому списку.

Что читает. Код в папке package реестра (без тестов и миграций): классы, чьё основание кончается на Settings, их
поля и model_config с env_file; чтения os.environ.get / os.getenv / os.environ[…]; раздел compose — откуда значение.
NEEDS: compose (может не быть у сервиса — тогда источники только .env и умолчания).

Раздел .facts.json — список settings и поля рядом; что в записи — tools/facts/_settings.py.
"""

from __future__ import annotations

import ast
import re

from facts._base import COMMENT_LINE, Ctx, code_files, diff, parse, ref_key
from facts._settings import settings_section

NEEDS = ("compose",)
CODE_EXTS = (".py",)
ENV_READ = re.compile(r"os\.(?:environ\.get|getenv)\(\s*[\"'](\w+)[\"']|os\.environ\[\s*[\"'](\w+)[\"']\s*\]")


def _literal(node: ast.AST | None, src: str) -> tuple[str, bool]:
    """(умолчание текстом, обязательна ли)."""
    if node is None:
        return "", True
    if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "Field":
        d = next((k.value for k in node.keywords if k.arg == "default"), None)
        if d is None and node.args:
            d = node.args[0]
        if d is None or (isinstance(d, ast.Constant) and d.value is Ellipsis):
            return "", True
        node = d
    if isinstance(node, ast.Constant):
        return repr(node.value) if isinstance(node.value, str) else str(node.value), False
    seg = " ".join((ast.get_source_segment(src, node) or "…").split())  # многострочное умолчание — в одну строку
    return (seg if len(seg) <= 160 else seg[:159] + "…"), False


def _fields(ctx: Ctx, files) -> tuple[list[dict], list[str]]:
    fields, local_env_files = [], []
    for p in files:
        src = p.read_text(encoding="utf-8", errors="replace")
        tree = parse(p)
        if not tree:
            continue
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            bases = [getattr(b, "id", getattr(b, "attr", "")) for b in cls.bases]
            if not any(b.endswith("Settings") for b in bases):
                continue
            for st in cls.body:
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.target.id != "model_config":
                    default, required = _literal(st.value, src)
                    fields.append({"name": st.target.id, "default": default, "required": required, "ref": ctx.ref(p, st.lineno)})
                if isinstance(st, (ast.Assign, ast.AnnAssign)):
                    tgt = st.targets[0] if isinstance(st, ast.Assign) else st.target
                    if getattr(tgt, "id", "") == "model_config":
                        m = re.search(r"env_file\W+[\"']([^\"']+)[\"']", ast.get_source_segment(src, st) or "")
                        if m:
                            local_env_files.append(m[1])
    return fields, local_env_files


def _attribute_uses(ctx: Ctx, files) -> dict[str, list[str]]:
    """Где в коде читается атрибут: имя → ссылки (по разбору кода, без комментариев и описаний)."""
    uses: dict[str, list[str]] = {}
    for p in files:
        tree = parse(p)
        if not tree:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
                uses.setdefault(n.attr, []).append(ctx.ref(p, n.lineno))
            elif (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "getattr" and len(n.args) >= 2
                  and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str)):
                uses.setdefault(n.args[1].value, []).append(ctx.ref(p, n.lineno))
    return {k: sorted(set(v), key=ref_key) for k, v in uses.items()}


def extract(ctx: Ctx) -> dict:
    files = code_files(ctx.package, CODE_EXTS)
    fields, local_env = _fields(ctx, files)
    reads: dict[str, str] = {}
    for p in files:
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if COMMENT_LINE.match(line):
                continue
            for m in ENV_READ.finditer(line):
                reads.setdefault(m[1] or m[2], ctx.ref(p, i))
    return settings_section(ctx, fields, reads, local_env, _attribute_uses(ctx, files))


def compare(old: dict, new: dict) -> list[str]:
    return diff(old, new, "pydantic-settings", ignore=frozenset({"used_refs"}), ids={"settings": "name"})
