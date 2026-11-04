"""Общее двух частей настроек — pydantic-settings и vite-env: откуда у настройки значение и где её читают.

Зачем. Код на Python и интерфейс на Vite читают окружение по-разному, но ответ нужен один: какие у сервиса
настройки, откуда значение (environment в compose, env_file compose, свой .env в папке кода, умолчание кода) и где
настройку читают. Часть находит имена в коде, а запись настройки собирает этот модуль.

Кто зовёт. Только части pydantic-settings и vite-env.

Запись настройки (раздел части, список settings):
  name         имя настройки
  kind         field — поле класса настроек; environ — чтение окружения прямо в коде; runtime — переменная среды
               запуска из compose (PYTHONPATH и подобные); compose-only — задана в compose, код её не читает
  ref          где объявлена или прочитана — строка кода; у compose-only — пусто
  default      умолчание в коде (секрет — ‹секрет›)
  required     обязательна ли (у поля без умолчания)
  source       откуда значение: compose · env_file <путь> · .env в папке кода <путь> · умолчание в коде · не задана
  source_ref   строка, где значение задано
  value        значение (секрет — ‹секрет›, пароль в адресе — ***)
  secret       секрет ли — по шаблонам secret_names проекта
  used, used_refs  читает ли код настройку и где (до трёх мест)
Рядом со списком: env_file_unused — переменные env_file, которые код не читает; env_file_interp_only — только для
подстановки ${…} в compose; local_env_files — свои .env в папке кода.
"""

from __future__ import annotations

import re

from facts._base import RUNTIME_VARS, Ctx, compose_paths, load_env_file


def settings_section(ctx: Ctx, fields: list[dict], environ_reads: dict[str, str], local_env: list[str],
                     uses: dict[str, list[str]]) -> dict:
    """fields — поля классов настроек (name, default, required, ref); environ_reads — имя → строка чтения окружения;
    local_env — имена своих .env из настроек класса; uses — где в коде читается атрибут с таким именем."""
    comp = ctx.facts.get("compose") or {}
    compose_env_map = {e["name"]: e for e in comp.get("environment", [])}
    env_files = [(ef["path"], load_env_file(ctx.repo, ctx.repo / ef["path"])) for ef in comp.get("env_files", [])]
    local_files = []
    cmd = (comp.get("command") or {}).get("text", "")
    m = re.search(r"cd\s+/app/(\S+?)(?:\s|&&|;|$)", cmd)
    for name in local_env:
        base = (ctx.repo / m[1]) if m else ctx.root
        f = base / name
        local_files.append((ctx.rel(f) if f.exists() else f"{ctx.rel(base)}/{name} (нет файла)", load_env_file(ctx.repo, f)))

    def source_of(name: str) -> tuple[str, str, str]:
        if name in compose_env_map:
            e = compose_env_map[name]
            return "compose", e["ref"], e["value"]
        for path, vars_ in env_files:
            if name in vars_:
                v = vars_[name]
                return f"env_file {path}", f"{v.file}:{v.line}", ctx.mask(name, v.value)
        for path, vars_ in local_files:
            if name in vars_:
                v = vars_[name]
                return f".env в папке кода {path}", f"{v.file}:{v.line}", ctx.mask(name, v.value)
        return "", "", ""

    res, seen = [], set()
    for f in fields:
        name = f["name"]
        seen.add(name)
        src, sref, value = source_of(name)
        if not src:
            src, value = ("умолчание в коде", ctx.mask(name, f["default"].strip("'\""))) if not f["required"] else ("не задана", "")
        used = [u for u in uses.get(name, []) if u != f["ref"]][:3]
        if name in environ_reads:
            used = [environ_reads[name], *used][:3]
        res.append({"name": name, "kind": "field", "ref": f["ref"], "default": ctx.mask(name, f["default"]),
                    "required": f["required"], "source": src, "source_ref": sref, "value": value,
                    "secret": ctx.is_secret(name), "used": bool(used), "used_refs": used})
    for name, r in sorted(environ_reads.items()):
        if name in seen:
            continue
        seen.add(name)
        src, sref, value = source_of(name)
        res.append({"name": name, "kind": "environ", "ref": r, "default": "", "required": False,
                    "source": src or "не задана", "source_ref": sref, "value": value,
                    "secret": ctx.is_secret(name), "used": True, "used_refs": [r]})
    for name, e in compose_env_map.items():
        if name in seen:
            continue
        seen.add(name)
        res.append({"name": name, "kind": "runtime" if name in RUNTIME_VARS else "compose-only", "ref": "",
                    "default": "", "required": False, "source": "compose", "source_ref": e["ref"], "value": e["value"],
                    "secret": ctx.is_secret(name), "used": False, "used_refs": []})
    file, _, _ = compose_paths(ctx)
    compose_text = file.read_text(encoding="utf-8") if file and file.is_file() else ""
    unused, interp_only = [], []
    for _, vars_ in env_files:
        for name in vars_:
            if name in seen:
                continue
            (interp_only if re.search(rf"\$\{{{name}\b", compose_text) else unused).append(name)
    return {"settings": res, "env_file_unused": sorted(set(unused)), "env_file_interp_only": sorted(set(interp_only)),
            "local_env_files": [p for p, _ in local_files]}
