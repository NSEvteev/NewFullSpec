"""Монитор контекста — общее для строки состояния (ctxStatus.py), хуков (ctxHooks.py) и передачи (ctxHandoff.py).

Зачем: сессия не видит, сколько контекста занято, и сама не предлагает сжатие (Никита, 2026-10-23: «он должен включаться
при старте любой сессии CLAUDE и отправлять в чат сообщения сколько контекста использовано»). Числа знает строка
состояния (context_window_size, used_percentage), а хукам они не приходят — хук берёт usage последнего ответа из журнала
разговора (input + cache_read + cache_creation, так же считает used_percentage), а размер окна — из файла строки состояния.

Состояние — по файлу на сессию в state/: <session_id>.json пишут хуки, <session_id>.status.json — строка состояния
(два файла, чтобы два процесса не затирали друг другу запись). Только стандартная библиотека Python.
"""
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

HOME = Path(os.environ.get('CTXMON_HOME') or Path(__file__).resolve().parent)   # CTXMON_HOME — самопроверке
STATE = HOME / 'state'
HANDOFFS = HOME / 'handoffs'                       # копии передач: их подкладывает SessionStart после сжатия
TEMPLATE = HOME / 'handoff-template.md'
LOG = HOME / 'ctxmon.log'
MARKS = (50, 75, 85, 90)                           # пороги, % окна (решение Никиты, 2026-10-23)
DEFAULT_WINDOW = 1_000_000                         # окно, пока строка состояния не сказала своё
TAIL = 1 << 20                                     # хвост журнала, где ищется последний ответ; не нашёлся — больше
TAIL_MAX = 16 << 20
ASK_RE = re.compile(r'сжат|сжим|сжать|компакт|compact', re.I)   # вопрос AskUserQuestion — о сжатии
HANDOFF_RE = re.compile(r'''[^\s"'«»`()]+?\.md''')                # путь передачи в тексте /compact


def autonomous() -> bool:
    """Автономная сессия — запущена с CTXMON_AUTONOMOUS=1: не спрашивает, на 85 % сама пишет передачу."""
    return os.environ.get('CTXMON_AUTONOMOUS', '').strip() not in ('', '0', 'no', 'false')


def marks_from(arg: str | None) -> tuple:
    """Пороги из аргумента «--marks 1,2,3,4» (пробная сессия) или обычные 50, 75, 85, 90."""
    if not arg:
        return MARKS
    vals = tuple(sorted(float(x) for x in arg.split(',') if x.strip()))
    if len(vals) != 4 or not all(0 < v < 100 for v in vals):
        raise ValueError(f'--marks — четыре процента через запятую, по возрастанию: «{arg}»')
    return vals


def log(msg: str) -> None:
    """Ошибка хука — в журнал монитора, а не в чат: хук стоит во всех сессиях машины и не должен им мешать."""
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + msg.rstrip() + '\n')
    except OSError:
        pass


# ── состояние сессии ──

def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _write_json(p: Path, data: dict) -> None:
    """Запись через временный файл и подмену. На Windows подмена падает «Отказано в доступе», пока файл читает другой
    процесс (строка состояния и хук — в одну секунду): несколько попыток, потом запись поверх, а не ошибка."""
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    tmp = p.with_name(p.name + f'.{os.getpid()}.tmp')
    tmp.write_text(text, encoding='utf-8')
    for _ in range(10):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.03)
    try:
        p.write_text(text, encoding='utf-8')
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def safe_id(sid: str) -> str:
    return re.sub(r'[^\w.-]', '_', sid or 'unknown')


def load(sid: str) -> dict:
    """Состояние хуков сессии: fired — сработавшие пороги, asked — порог, на котором спросили о сжатии, must_read —
    что прочитать после сжатия, handoff — передача этой сессии, pending — передача, которую подложить после сжатия."""
    st = _read_json(STATE / f'{safe_id(sid)}.json')
    st.setdefault('fired', [])
    st.setdefault('asked', 0)
    st.setdefault('must_read', {})
    st.setdefault('stop_blocks', 0)
    return st


def save(sid: str, st: dict) -> None:
    st['updated'] = time.time()
    _write_json(STATE / f'{safe_id(sid)}.json', st)


class Lock:
    """Замок на состояние сессии: хуки параллельных вызовов инструментов идут разом и иначе затирают запись друг друга.
    Не дождался за секунду — работает без замка (хук не должен висеть); замок старше 5 с — брошенный, снимается."""

    def __init__(self, sid: str):
        self.p = STATE / f'{safe_id(sid)}.lock'
        self.fd = None

    def __enter__(self):
        STATE.mkdir(parents=True, exist_ok=True)
        for _ in range(50):
            try:
                self.fd = os.open(self.p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.p.stat().st_mtime > 5:
                        self.p.unlink()
                except OSError:
                    pass
                time.sleep(0.02)
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            try:
                self.p.unlink()
            except OSError:
                pass


def load_status(sid: str) -> dict:
    return _read_json(STATE / f'{safe_id(sid)}.status.json')


def save_status(sid: str, data: dict) -> None:
    _write_json(STATE / f'{safe_id(sid)}.status.json', data)


def prune(days: float = 14) -> None:
    """Старые файлы состояния и передач — прочь: монитор стоит на всей машине, файлы копятся."""
    edge = time.time() - days * 86400
    for d in (STATE, HANDOFFS):
        for p in d.glob('*') if d.is_dir() else []:
            try:
                if p.is_file() and p.stat().st_mtime < edge:
                    p.unlink()
            except OSError:
                pass


# ── журнал разговора ──

def _tail(path: str, size: int) -> tuple[list, bool]:
    """Записи журнала из последних size байт (первая строка куска — неполная, пропускается); второе — дошли ли до начала."""
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        start = max(0, end - size)
        f.seek(start)
        data = f.read()
    lines = data.split(b'\n')
    if start:
        lines = lines[1:]
    out = []
    for raw in lines:
        if raw.strip():
            try:
                out.append(json.loads(raw))
            except ValueError:
                pass
    return out, start == 0


def entries(path: str) -> list:
    """Весь журнал — для передачи (редко): сообщения Никиты, скиллы, правленые файлы."""
    return _tail(path, 1 << 40)[0]


def is_summary(e: dict) -> bool:
    return e.get('type') == 'user' and bool(e.get('isCompactSummary'))


def usage_tokens(e: dict) -> int | None:
    """Контекст по ответу: input + cache_read + cache_creation — как used_percentage строки состояния."""
    if e.get('type') != 'assistant' or e.get('isSidechain'):
        return None
    u = (e.get('message') or {}).get('usage')
    if not u:
        return None
    return int(u.get('input_tokens') or 0) + int(u.get('cache_read_input_tokens') or 0) \
        + int(u.get('cache_creation_input_tokens') or 0)


def last_tokens(path: str | None) -> int | None:
    """Контекст сейчас — usage последнего ответа. Сводка сжатия после него — None: ответа после сжатия ещё нет, а
    прежнее число — уже не про это окно."""
    if not path or not os.path.isfile(path):
        return None
    size = TAIL
    while True:
        es, whole = _tail(path, size)
        for e in reversed(es):
            if is_summary(e):
                return None
            t = usage_tokens(e)
            if t:
                return t
        if whole or size >= TAIL_MAX:
            return None
        size *= 4


CHARS_PER_TOKEN = 3.0                              # русский текст и код — около 3 знаков на токен: счёт с запасом
IMAGE_TOKENS = 1600                                # картинка в ответе инструмента


def _size(content) -> int:
    """Оценка токенов содержимого записи: текст — по знакам, картинки — по IMAGE_TOKENS."""
    if isinstance(content, str):
        return int(len(content) / CHARS_PER_TOKEN)
    if isinstance(content, list):
        return sum(IMAGE_TOKENS if isinstance(x, dict) and x.get('type') == 'image' else
                   _size(x.get('content') if isinstance(x, dict) and 'content' in x else
                         x.get('text', '') if isinstance(x, dict) else str(x)) for x in content)
    if isinstance(content, dict):
        if is_image(content):
            return IMAGE_TOKENS
        return int(len(json.dumps(content, ensure_ascii=False)) / CHARS_PER_TOKEN)
    return 0


def is_image(d: dict) -> bool:
    """Картинка в ответе инструмента — и так, как её пишет журнал, и так, как Read отдаёт её хуку: {"type": "image",
    "file": {"base64": …}}. Длина base64 — не токены: две картинки снимка давали оценку в 200 тыс. вместо ~9 тыс., и
    монитор слал ложные 76–93 % (2026-10-24)."""
    f = d.get('file')
    return d.get('type') == 'image' or 'base64' in d or (isinstance(f, dict) and 'base64' in f)


def context_tokens(path: str | None, pending: tuple | None = None) -> int | None:
    """Контекст сейчас — usage последнего ответа и оценка того, что пришло после него: результаты инструментов и
    сообщения ещё не посчитаны моделью (как добавляет /context). Иначе большое чтение файла видно только со следующим
    ответом: на 89 % чтение в 100 тыс. проскочило бы сигнал 90 % прямо в автосжатие. pending — (номер вызова, ответ
    инструмента) из входа хука PostToolUse: в журнале его ответа может ещё не быть. Сводка сжатия после ответа — None."""
    if not path or not os.path.isfile(path):
        return None
    size = TAIL
    while True:
        es, whole = _tail(path, size)
        extra, seen = 0, set()
        for e in reversed(es):
            if is_summary(e):
                return None
            t = usage_tokens(e)
            if t:
                if pending and pending[0] not in seen:
                    extra += _size(pending[1])
                return t + extra
            if e.get('type') == 'user':
                c = (e.get('message') or {}).get('content')
                extra += _size(c)
                for x in c if isinstance(c, list) else []:
                    if isinstance(x, dict) and x.get('type') == 'tool_result':
                        seen.add(x.get('tool_use_id'))
        if whole or size >= TAIL_MAX:
            return None
        size *= 4


def since_compact(es: list) -> list:
    """Записи после последней сводки сжатия — то, что было с прошлого сжатия."""
    k = max((i for i, e in enumerate(es) if is_summary(e)), default=-1)
    return es[k + 1:]


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(x.get('text', '') for x in content if isinstance(x, dict) and x.get('type') == 'text')
    return ''


def human_messages(es: list) -> list[tuple[str, str]]:
    """Сообщения Никиты по порядку: (время, текст) — реплики и сообщения из очереди (queued_command, их он пишет, пока
    сессия работает); служебные вставки, результаты инструментов и прерывания — мимо."""
    out = []
    for e in es:
        ts = e.get('timestamp', '')
        if e.get('type') == 'user' and not e.get('isMeta') and not e.get('isCompactSummary') \
                and not e.get('toolUseResult'):
            t = _text((e.get('message') or {}).get('content')).strip()
            if t and not t.startswith(('[Request interrupted', '<local-command', '<command-message>')) \
                    and not t.startswith('<command-name>/compact'):
                out.append((ts, t))
        elif e.get('type') == 'attachment':
            a = e.get('attachment') or {}
            if a.get('type') == 'queued_command' and (a.get('origin') or {}).get('kind', 'human') == 'human':
                t = (a.get('prompt') or '').strip() if isinstance(a.get('prompt'), str) else _text(a.get('prompt'))
                if t:
                    out.append((a.get('timestamp') or ts, '[в очереди] ' + t))
    return out


def failed_ids(es: list) -> set:
    """Номера вызовов, которые не исполнились: ответ инструмента — ошибка (так приходит и отказ хука, например запрет
    монитора начать скилл без вопроса о сжатии)."""
    out = set()
    for e in es:
        c = (e.get('message') or {}).get('content') if e.get('type') == 'user' else None
        for x in c if isinstance(c, list) else []:
            if isinstance(x, dict) and x.get('type') == 'tool_result' and x.get('is_error'):
                out.add(x.get('tool_use_id'))
    return out


def tool_uses(es: list, names: tuple) -> list[dict]:
    """Исполненные вызовы инструментов с этими именами по порядку: [{name, input, ts}]; отклонённые и упавшие — мимо."""
    failed = failed_ids(es)
    out = []
    for e in es:
        if e.get('type') != 'assistant' or e.get('isSidechain'):
            continue
        for x in (e.get('message') or {}).get('content') or []:
            if isinstance(x, dict) and x.get('type') == 'tool_use' and x.get('name') in names and x.get('id') not in failed:
                out.append({'name': x['name'], 'input': x.get('input') or {}, 'ts': e.get('timestamp', '')})
    return out


# ── числа и пути ──

def fmt_tokens(n: float) -> str:
    """540 000 → «540 тыс.», 1 000 000 → «1 млн»."""
    if n >= 1_000_000 and n % 100_000 == 0:
        m = n / 1_000_000
        return f'{m:g} млн'.replace('.', ',')
    return f'{round(n / 1000):d} тыс.'


def local_time(ts: str) -> str:
    """Время журнала (UTC, ISO) — местное «ЧЧ:ММ»."""
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone().strftime('%H:%M')
    except (ValueError, TypeError):
        return ts[11:16]


def norm(p: str, cwd: str | None = None) -> str:
    """Путь для сравнения «прочитан ли»: прямые слэши, /e/… Git Bash → e:/…, ~ → домашняя, относительный — от cwd,
    без регистра (Windows)."""
    p = str(p).strip().strip('`"\'').replace('\\', '/')
    m = re.match(r'^/([a-zA-Z])/(.*)$', p)
    if m:
        p = f'{m.group(1)}:/{m.group(2)}'
    if p.startswith('~'):
        p = str(Path.home()).replace('\\', '/') + p[1:]
    if not re.match(r'^[a-zA-Z]:/', p) and not p.startswith('/') and cwd:
        p = norm(cwd) + '/' + p
    return os.path.normpath(p).replace('\\', '/').lower()


def long_path(p: str) -> str:
    """Путь, как его читает Никита: короткое имя Windows (843E~1) → полное (Никита), прямые слэши → обратные."""
    s = str(p).replace('/', '\\') if os.name == 'nt' else str(p)
    if os.name == 'nt':
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetLongPathNameW(s, buf, 1024):
                return buf.value
        except (OSError, AttributeError):
            pass
    return s


def show(p: str) -> str:
    """Открыть файл Никите — в VS Code (окно, где он работает: code -r), нет его — программой по умолчанию; ответ —
    что сделано. CTXMON_NO_OPEN=1 — не открывать (самопроверка)."""
    path = long_path(p)
    if os.environ.get('CTXMON_NO_OPEN'):
        return f'не открыт (CTXMON_NO_OPEN): {path}'
    import shutil
    import subprocess
    code = shutil.which('code')
    try:
        if code:
            subprocess.Popen([code, '-r', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f'открыт у Никиты в VS Code: {path}'
        os.startfile(path)                                 # noqa: S606 — только Windows
        return f'открыт у Никиты: {path}'
    except (OSError, AttributeError) as e:
        return f'НЕ открыт ({type(e).__name__}) — открыть самому: {path}'


def window_of(sid: str) -> int:
    """Окно сессии — из файла строки состояния; нет — DEFAULT_WINDOW."""
    w = load_status(sid).get('window')
    return int(w) if isinstance(w, (int, float)) and w > 0 else DEFAULT_WINDOW
