"""Тест хука pre-shell: встроенный Python не пишет md карты, а читать карту и писать в $S ему можно.

Зачем. Хук живой у всех сессий: правило, которое перестало ловить, пропустит запись md мимо проверки и с CRLF, а
правило, которое ловит лишнее, остановит обычный разбор карты скриптом. Тест держит обе стороны на проверочной карте
tools/samples/good/ (корень репо магазина — good/, карта — good/architecture/).

Как прогнать (из корня репо):
  python -m pytest architecture/tools/tests/test_hook.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))
import hook  # noqa: E402

GOOD = TOOLS / "samples" / "good"

DENY = {
    "write_text по пути md": """python -c "from pathlib import Path; Path('architecture/TOBE/orders/README.md').write_text('x')" """,
    "цикл по TOBE с записью назад": """python - <<'EOF'
from pathlib import Path
for f in Path("architecture/TOBE").rglob("*.md"):
    f.write_text(f.read_text(encoding="utf-8").replace("a", "b"), encoding="utf-8")
EOF""",
    "open(p, 'w') через имя": """python -c "p = 'architecture/ASIS/orders/README.md'; open(p, 'w').write('x')" """,
    "shutil.copy в md": """python - <<EOF
import shutil
shutil.copy('x.md', 'architecture/ASIS/orders/problems.md')
EOF""",
    "Path.open('w')": """python -c "from pathlib import Path; Path('architecture/ASIS/orders/methods.md').open('w').write('x')" """,
    "цель не видна, скрипт трогает карту": """python - architecture/ASIS/orders/README.md <<'EOF'
import sys
open(sys.argv[1], "w").write("x")
EOF""",
}

ALLOW = {
    "чтение карты, запись в $S": """python - <<'EOF'
import os
from pathlib import Path
S = Path(os.environ["S"])
text = Path("architecture/ASIS/orders/README.md").read_text(encoding="utf-8")
out = S / "out.txt"
out.write_text(text, encoding="utf-8")
EOF""",
    "копии md карты в $S по имени": """python - <<'EOF'
import os
from pathlib import Path
for f in Path("architecture/TOBE").rglob("*.md"):
    (Path(os.environ["S"]) / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
EOF""",
    "чтение open без режима": """python -c "print(open('architecture/ASIS/orders/README.md', encoding='utf-8').read())" """,
    "запись не в карту": """python -c "from pathlib import Path; Path('src/orders/app.py').write_text('x')" """,
    "запись в tools/ карты": """python -c "from pathlib import Path; Path('architecture/tools/x.py').write_text('x')" """,
    "grep по тексту записи": """grep -n "write_text" architecture/tools/hook.py""",
    "скрипт карты": "python architecture/tools/build.py",
}


def run(cmd: str) -> int:
    return hook.pre_shell({"tool_input": {"command": cmd}, "cwd": str(GOOD)})


@pytest.mark.parametrize("name", DENY)
def test_deny(name: str) -> None:
    assert run(DENY[name]) == 2


@pytest.mark.parametrize("name", ALLOW)
def test_allow(name: str) -> None:
    assert run(ALLOW[name]) == 0
