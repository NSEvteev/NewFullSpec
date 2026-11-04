"""Часть фактов «fastapi-openapi»: методы сервиса на FastAPI — из живой схемы /openapi.json и обработчиков в коде.

Зачем. В methods.md у метода — договор словами (что делает, ошибки, доступ). Есть ли метод вообще, его обработчик
и строка, нужен ли вход, поля запроса и ответа — отсюда; генератор ставит их на страницу, проверка находит метод
без раздела и раздел без метода.

Что читает. Живую схему по адресу из поля openapi реестра (сервис должен быть поднят; без прокси) и код: функции с
декораторами в папке package и в папках общих пакетов реестра (вид package) — обработчик ищется по operationId.

Раздел .facts.json:
  url, live          адрес схемы; удалось ли её взять (нет — reason: почему)
  count              сколько методов
  methods[]          method, path — ключ метода «METHOD путь»; function, ref — обработчик и строка его объявления;
                     summary — краткое описание из схемы; auth — нужен ли вход (у метода есть security);
                     in_schema — есть ли метод в живой схеме (сейчас все методы берутся из неё — всегда true);
                     request[] — name, type, required, in (path, query, body); response[] — name, type
                     (ответ-список — имена полей его записи с приставкой «[].»)
  Тип поля — как в схеме: string, integer, number, boolean, object, array<…>, имя схемы; формат — в скобках
  (string(date-time)); «или» — через « | ».

Чего не делает. Методы, которых нет в живой схеме, не ищет; не зовёт сами методы.
"""

from __future__ import annotations

import ast
import re

from facts._base import Ctx, diff, http_json, iter_files, parse

HTTP = ("get", "post", "put", "patch", "delete")


def _function_index(ctx: Ctx) -> dict[str, list[dict]]:
    dirs = [ctx.package] + [
        (ctx.repo / i["package"]).resolve() for k, i in ctx.registry.items() if i.get("kind") == "package" and k != ctx.service
    ]
    idx: dict[str, list[dict]] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for p in iter_files(d, (".py",)):
            tree = parse(p)
            if not tree:
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    decos = [ast.get_source_segment(src, x) or "" for x in n.decorator_list]
                    line = n.decorator_list[0].lineno if n.decorator_list else n.lineno
                    idx.setdefault(n.name, []).append({"ref": ctx.ref(p, line), "decos": decos})
    return idx


class _Schema:
    def __init__(self, spec: dict):
        self.comp = (spec.get("components") or {}).get("schemas") or {}

    def resolve(self, s: dict, depth: int = 0) -> dict:
        while isinstance(s, dict) and "$ref" in s and depth < 20:
            s = self.comp.get(s["$ref"].rsplit("/", 1)[-1], {})
            depth += 1
        return s or {}

    def tname(self, s: dict, depth: int = 0) -> str:
        if not isinstance(s, dict) or depth > 6:
            return "any"
        if "$ref" in s:
            return s["$ref"].rsplit("/", 1)[-1]
        for k in ("anyOf", "oneOf"):
            if k in s:
                return " | ".join(self.tname(x, depth + 1) for x in s[k])
        if "allOf" in s and len(s["allOf"]) == 1:
            return self.tname(s["allOf"][0], depth + 1)
        t = s.get("type", "any")
        if t == "array":
            return f"array<{self.tname(s.get('items') or {}, depth + 1)}>"
        return f"{t}({s['format']})" if s.get("format") else t

    def fields(self, s: dict, prefix: str = "", required: bool = True) -> list[dict]:
        """Поля объекта: имя, тип, обязательность; у списка объектов — поля записи с приставкой «[].»."""
        s = self.resolve(s)
        if "anyOf" in s:  # «объект или null» — поля объекта
            objs = [self.resolve(x) for x in s["anyOf"] if self.resolve(x).get("properties")]
            if len(objs) == 1:
                s = objs[0]
        if s.get("type") == "array":
            item = self.resolve(s.get("items") or {})
            if item.get("properties"):
                return self.fields(item, prefix + "[].", required)
            return [{"name": prefix + "[]", "type": self.tname(s), "required": required}] if prefix == "" else []
        props = s.get("properties") or {}
        req = set(s.get("required") or [])
        return [{"name": prefix + k, "type": self.tname(v), "required": k in req} for k, v in props.items()]


def _io(sch: _Schema, op: dict) -> tuple[list[dict], list[dict]]:
    request = []
    for p in op.get("parameters", []):
        p = sch.resolve(p)
        if p.get("in") in ("path", "query"):
            request.append({"name": p["name"], "type": sch.tname(p.get("schema") or {}), "required": bool(p.get("required")),
                            "in": p["in"]})
    body = ((op.get("requestBody") or {}).get("content") or {})
    js = body.get("application/json") or next(iter(body.values()), None)
    if js:
        for f in sch.fields(js.get("schema") or {}):
            request.append({**f, "in": "body"})
    response = []
    for code, r in sorted((op.get("responses") or {}).items()):
        if not str(code).startswith("2"):
            continue
        content = (sch.resolve(r).get("content") or {})
        js = content.get("application/json") or next(iter(content.values()), None)
        if js:
            response = [{"name": f["name"], "type": f["type"]} for f in sch.fields(js.get("schema") or {})]
        break
    return request, response


def extract(ctx: Ctx) -> dict:
    url = ctx.info.get("openapi")
    if not url:
        return {"live": False, "reason": "у сервиса в реестре нет адреса openapi"}
    try:
        spec = http_json(url)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "live": False, "reason": f"живая схема недоступна: {e}"}
    idx = _function_index(ctx)
    sch = _Schema(spec)
    methods = []
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            if method not in HTTP:
                continue
            opid = op.get("operationId", "")
            suffix = re.sub(r"\W", "_", path) + "_" + method
            fname = opid[: -len(suffix)] if opid.endswith(suffix) else opid
            cands = idx.get(fname, [])
            tail = path.rstrip("/").rsplit("/", 1)[-1]
            best = (
                next((c for c in cands if any(f".{method}(" in d and tail in d for d in c["decos"])), None)
                or next((c for c in cands if any(f".{method}(" in d for d in c["decos"])), None)
                or (cands[0] if cands else None)
            )
            request, response = _io(sch, op)
            methods.append({"method": method.upper(), "path": path, "function": fname, "ref": best["ref"] if best else "",
                            "summary": op.get("summary", ""), "auth": bool(op.get("security")), "in_schema": True,
                            "request": request, "response": response})
    return {"url": url, "live": True, "count": len(methods), "methods": methods}


def compare(old: dict, new: dict) -> list[str]:
    return diff(old, new, "fastapi-openapi", ids={"methods": "method path", "request": "name", "response": "name"})
