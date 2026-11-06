"""Строка состояния Claude Code — датчик монитора контекста: «контекст 54 % · 540 тыс. из 1 млн» всегда на экране.

Claude Code зовёт команду после каждого ответа, после /compact и при старте сессии; на вход — JSON сессии
(context_window.used_percentage, total_input_tokens, context_window_size, session_id, transcript_path, cwd, model).
Кроме строки, команда пишет числа в state/<session_id>.status.json: размер окна оттуда берут хуки (им он не приходит).
Цвет — по порогам монитора: до 50 % обычный, 50 … 75 жёлтый, 75 … 85 оранжевый, от 85 — красный.

Настройка (~/.claude/settings.json):
  "statusLine": {"type": "command", "command": "PYTHONIOENCODING=utf-8 python ~/.claude/ctxmon/ctxStatus.py"}
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ctxCore as C  # noqa: E402

COLORS = ('\033[31m', '\033[38;5;208m', '\033[33m')     # красный, оранжевый, жёлтый
RESET = '\033[0m'


def line(data: dict, marks: tuple = C.MARKS) -> str:
    """Текст строки по входу строки состояния; заодно — числа в файл сессии."""
    cw = data.get('context_window') or {}
    size = cw.get('context_window_size') or C.DEFAULT_WINDOW
    pct = cw.get('used_percentage')
    tokens = cw.get('total_input_tokens')
    if tokens is None and isinstance(pct, (int, float)):
        tokens = pct / 100 * size
    sid = data.get('session_id') or ''
    if sid:
        try:                                               # не записалось — строка на экране всё равно нужна
            C.save_status(sid, {'window': size, 'pct': pct, 'tokens': tokens, 'time': time.time(),
                                'transcript': data.get('transcript_path'), 'cwd': data.get('cwd'),
                                'model': (data.get('model') or {}).get('id')})
        except OSError as e:
            C.log(f'ctxStatus: файл сессии не записан — {type(e).__name__}: {e}')
    if pct is None or not tokens:                          # до первого ответа сессии и сразу после сжатия чисел нет
        text = f'контекст — до первого ответа · окно {C.fmt_tokens(size)}'
        color = ''
    else:
        text = f'контекст {pct:.0f} % · {C.fmt_tokens(tokens or 0)} из {C.fmt_tokens(size)}'
        lim = [m for m in marks if pct >= m]
        # цвет — по первым трём порогам: от третьего (85) красный, от второго (75) оранжевый, от первого (50) жёлтый
        color = next((c for m, c in zip((marks[2], marks[1], marks[0]), COLORS) if pct >= m), '')
        if lim:
            text += f' · порог {lim[-1]:g} %'
    if C.autonomous():
        text += ' · автономная'
    return f'{color}{text}{RESET if color else ""}'


def main() -> int:
    marks = C.marks_from(sys.argv[sys.argv.index('--marks') + 1]) if '--marks' in sys.argv else C.MARKS
    try:
        data = json.loads(sys.stdin.buffer.read().decode('utf-8') or '{}')
        print(line(data, marks))
    except Exception as e:  # noqa: BLE001 — строка состояния не должна падать на экране
        C.log(f'ctxStatus: {type(e).__name__}: {e}')
        print('контекст — (ошибка монитора, ~/.claude/ctxmon/ctxmon.log)')
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())
