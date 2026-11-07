"""Тесты одного пакета с потолком памяти — единственная команда тестов для шагов процесса изменений.

Зачем. Прогон тестов без потолка однажды занял 16+ ГБ и дважды уронил компьютер. Скрипт
запускает pytest в папке пакета с жёстким потолком памяти на него и всех его детей; адреса баз и прокси из
окружения убирает, чтобы тесты не дошли до живых баз; байткод и кэш pytest не пишет.

Кто зовёт. Основная сессия и агенты блоков — по разделу «Команды» PROJECT.md. Из корня репо:
  python scripts/test_limited.py src/orders                 tests/unit пакета
  python scripts/test_limited.py src/orders tests/unit/test_x.py -k name   свои пути и ключи pytest
  python scripts/test_limited.py shared/auth tests --env PYTHONPATH=.                добавить переменную
  --mem 4        потолок, ГБ (по умолчанию 4)
  --timeout 900  предел времени, с
  --map <папка>  карта, где лежат инструменты (по умолчанию architecture)
Без путей — tests/unit, а если её нет — tests. DATABASE_URL — заглушка: настройкам сервиса он нужен, в базу тесты
без базы не ходят. Тесты с тестовой базой гоняются тоже этим скриптом: адрес базы им дают явно через --env — и только
адрес отдельной тестовой базы, не живой. Точная команда проекта — PROJECT.md, «Команды»; вид:
  python scripts/test_limited.py src/orders tests/integration --env "ORDERS_TEST_DB=postgresql+asyncpg://orders:${PW}@127.0.0.1:5438/orders_test"
PW — пароль базы, его берут из файла настроек окружения в той же строке; в команду и в вывод он не вписывается.

Что читает и пишет: ничего, кроме вывода pytest; потолок берёт из инструментов карты (tools/facts/_base.py).

Коды выхода: код pytest; 3 — упёрся в потолок памяти; 2 — неверный вызов.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANITIZE = re.compile(r"REDIS|DATABASE|_DB_|DB_URL|POSTGRES|AUTH_DB|^TEST_|PROXY", re.I)
STUB_DB = "postgresql+asyncpg://x:x@localhost:1/x"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Тесты пакета с потолком памяти")
    ap.add_argument("package", help="папка пакета от корня репо: src/<сервис> или shared/<пакет>")
    ap.add_argument("--mem", type=float, default=4.0)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--map", default="architecture")
    ap.add_argument("--env", action="append", default=[], help="ИМЯ=значение — добавить в окружение")
    a, a.args = ap.parse_known_args()  # всё, чего скрипт не знает, — пути и ключи pytest
    pkg = ROOT / a.package
    if not pkg.is_dir():
        print(f"нет папки {a.package}", file=sys.stderr)
        return 2
    sys.path.insert(0, str(ROOT / a.map / "tools"))
    try:
        from facts._base import run_limited
    except ImportError:
        print(f"нет инструментов карты: {a.map}/tools/facts/_base.py", file=sys.stderr)
        return 2
    args = a.args or [("tests/unit" if (pkg / "tests/unit").is_dir() else "tests")]
    env = {k: v for k, v in os.environ.items() if not SANITIZE.search(k)}
    env.update(DATABASE_URL=STUB_DB, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    for pair in a.env:
        k, _, v = pair.partition("=")
        env[k] = v
    cmd = [sys.executable, "-m", "pytest", *args, "-q", "-p", "no:cacheprovider", "--no-cov"]
    code, out, hit = run_limited(cmd, pkg, env, a.timeout, a.mem)
    if "unrecognized arguments: --no-cov" in out:
        code, out, hit = run_limited(cmd[:-1], pkg, env, a.timeout, a.mem)
    print(out[-6000:])
    print(f"код {code} · упёрся в потолок {a.mem:g} ГБ: {'да' if hit else 'нет'}")
    return 3 if hit else code


if __name__ == "__main__":
    sys.exit(main())
