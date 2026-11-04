"""Часть фактов «compose»: как сервис запускается контейнером — порт, тома, переменные, команда, проверка здоровья.

Зачем. Страница сервиса показывает запуск (порт, команду, проверку здоровья, тома), а часть pydantic-settings
узнаёт отсюда, откуда у настройки значение: из environment сервиса или из env_file. Поэтому compose — первой.

Что читает. Ключ compose в project/settings.yaml: file — compose-файл, env — его файл переменных для подстановки
${VAR}, project — имя проекта (контейнер — <проект>-<сервис>-1). Имя сервиса в compose — поле compose реестра.

Раздел .facts.json:
  service, container, ref       имя в compose, имя контейнера, строка описания сервиса
  ports[]                       host, container, bind (адрес, к которому привязан порт; пусто — все), ref
  volumes[]                     kind (bind — папка с диска, volume — том docker, anon — безымянный), host — у bind
                                путь от корня репо (вне репо — через ../), container, mode (ro/rw), code (bind
                                папки кода сервиса из реестра — правка кода видна в контейнере сразу), raw, ref
  env_files[]                   path — от корня репо, ref
  environment[]                 name, raw — как в compose (умолчание секрета скрыто), value — после подстановки
                                (секрет — ‹секрет›, пароль в адресе — ***), ref
  depends_on[], depends_on_ref  от каких сервисов compose зависит запуск
  command                       text, ref — команда запуска
  healthcheck                   url (адрес проверки или начало команды), ref

Чего не делает. Не запускает docker и не смотрит, поднят ли контейнер: только файл compose.
"""

from __future__ import annotations

import re
from pathlib import Path

from facts._base import Ctx, compose_paths, diff, interpolate, line_of, load_compose, load_env_file, val


def _is_code(ctx: Ctx, host: Path) -> bool:
    """Папка кода: корень сервиса из реестра или папка внутри него (код того, кто её монтирует или подключает)."""
    for info in ctx.registry.values():
        root = (ctx.repo / info["root"]).resolve()
        if host == root or host.is_relative_to(root):
            return True
    return False


def extract(ctx: Ctx) -> dict:
    file, env_file, project = compose_paths(ctx)
    name = ctx.info.get("compose")
    if not file or not name:
        return {"error": "нет compose-файла в project/settings.yaml или имени сервиса в реестре"}
    env = load_env_file(ctx.repo, env_file) if env_file else {}
    compose = load_compose(file)
    node = compose["services"].get(name)
    if node is None:
        return {"error": f"сервиса {name} нет в {ctx.rel(file)}"}
    cref = lambda n: ctx.ref(file, line_of(n))  # noqa: E731
    out: dict = {"service": name, "container": f"{project}-{name}-1", "ref": cref(node)}

    ports = []
    for p in node.get("ports", []):
        parts = interpolate(val(p), env).split(":")
        bind = parts[0] if len(parts) == 3 else ""
        host, cont = (parts[-2], parts[-1]) if len(parts) >= 2 else ("", parts[0])
        ports.append({"host": host, "container": cont, "bind": bind, "ref": cref(p)})
    out["ports"] = ports

    vols = []
    for v in node.get("volumes", []):
        raw = val(v)
        segs = interpolate(raw, env).split(":")
        mode = "rw"
        if len(segs) >= 3 and segs[-1] in ("ro", "rw"):
            mode = segs[-1]
            segs = segs[:-1]
        if len(segs) == 1:
            vols.append({"kind": "anon", "container": segs[0], "host": "", "mode": mode, "raw": raw, "ref": cref(v)})
            continue
        src, dst = ":".join(segs[:-1]), segs[-1]
        if src.startswith((".", "/", "~")) or re.match(r"^[A-Za-z]:", src):
            hp = Path(src).expanduser()
            hp = (hp if hp.is_absolute() else file.parent / hp).resolve()
            vols.append(
                {
                    "kind": "bind",
                    "host": ctx.rel(hp),
                    "container": dst,
                    "mode": mode,
                    "code": _is_code(ctx, hp),
                    "raw": raw,
                    "ref": cref(v),
                }
            )
        else:
            vols.append({"kind": "volume", "host": src, "container": dst, "mode": mode, "raw": raw, "ref": cref(v)})
    out["volumes"] = vols

    ef = node.get("env_file", [])
    out["env_files"] = [
        {"path": ctx.rel((file.parent / val(e)).resolve()), "ref": cref(e)} for e in (ef if isinstance(ef, list) else [ef])
    ]

    environment = []
    envn = node.get("environment", [])
    if isinstance(envn, list):
        for e in envn:
            k, _, v = val(e).partition("=")
            environment.append({"name": k, "raw": v, "ref": cref(e)})
    elif isinstance(envn, dict):
        for k, v in envn.items():
            if k != "__line__":
                environment.append({"name": k, "raw": val(v), "ref": cref(v)})
    for e in environment:
        e["value"] = ctx.mask(e["name"], interpolate(e["raw"], env))
        # умолчание секретной переменной в ${ПАРОЛЬ:-…} — тоже секрет
        e["raw"] = re.sub(
            r"\$\{(\w+)(:?[-?])([^}]*)\}",
            lambda m: f"${{{m[1]}{m[2]}‹секрет›}}" if ctx.is_secret(m[1]) and m[3] else m[0],
            e["raw"],
        )
    out["environment"] = environment

    dep = node.get("depends_on", {})
    out["depends_on"] = [k for k in (dep.keys() if isinstance(dep, dict) else [val(x) for x in dep]) if k != "__line__"]
    if dep:
        out["depends_on_ref"] = cref(dep if isinstance(dep, dict) else dep[0])
    cmd = node.get("command")
    if cmd is not None:
        text = " ".join(val(x) for x in cmd) if isinstance(cmd, list) else val(cmd)
        out["command"] = {"text": text, "ref": cref(cmd[0] if isinstance(cmd, list) and cmd else cmd)}
    hc = node.get("healthcheck")
    if isinstance(hc, dict) and "test" in hc:
        t = hc["test"]
        text = " ".join(val(x) for x in t) if isinstance(t, list) else val(t)
        m = re.search(r"https?://localhost:\d+[^\s\"')\\]*", text)
        out["healthcheck"] = {"url": m[0] if m else text[:120], "ref": cref(t[0] if isinstance(t, list) and t else hc)}
    return out


def compare(old: dict, new: dict) -> list[str]:
    return diff(old, new, "compose", ids={"ports": "container", "volumes": "container", "environment": "name"})
