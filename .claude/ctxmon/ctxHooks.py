"""Хуки монитора контекста — один файл, событие первым аргументом (~/.claude/settings.json, раздел hooks).

Не зависит от /context и /usage: контекст — usage последнего ответа в журнале разговора (Claude Code пишет его после
каждого ответа сам), окно — из файла строки состояния (ctxStatus.py). Агентам (agent_id во входе) хуки ничего не делают.

  prompt, post, stop  — порог пройден: сообщение Никите в чат с предложением сжать; ход не держат
  skill               — ничего
  start               SessionStart — запоминает журнал и папку; после сжатия подкладывает передачу
  wake                SessionStart после сжатия, в фоне (asyncRewake) — будит сессию: после ручного и автоматического сжатия
  precompact          PreCompact — собирает передачу; сжатие не останавливает
  --marks a,b,c,d — пороги вместо 50, 75, 85, 90 (пробная сессия)

Никита, 2026-11-05: монитор показывает контекст и предлагает сжать сообщением в чат; вопросов через AskUserQuestion, удержания хода и запрета скиллов нет.
Никита, 2026-11-06: «очевидно пробуждение должно работать и после автоматического и после ручного сжатия».

Сигнал порога — один раз за жизнь окна (после сжатия пороги снова взведены).
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ctxCore as C  # noqa: E402
import ctxHandoff as H  # noqa: E402

AUTO = 0.967                                       # автосжатие у окна 1 млн — около 967 тыс.
STOP_CAP = 3                                       # держать ход не больше стольких раз подряд
CTX_MAX = 9500                                     # подложенная передача целиком, если не длиннее (предел — 10 000)
PENDING = C.HOME / 'pending.json'                  # передача по папке сессии — если после сжатия у сессии новый номер
# Правки файлов: их ответ во входе PostToolUse несёт весь файл, в контекст он не идёт. 2026-10-27 правка макета в 4,3 МБ
# дала «занято 183 %» при настоящих 42 % (Никита: «Галлюционируешь чутка, контекста ещё 550 тысяч свободно»)
EDIT_TOOLS = ('Edit', 'MultiEdit', 'Write', 'NotebookEdit')


def handoff_cmd(sid: str) -> str:
    return f'PYTHONIOENCODING=utf-8 python ~/.claude/ctxmon/ctxHandoff.py --session {sid}'


def texts(level: int, pct: float, tok: int, win: int, sid: str, marks: tuple) -> tuple[str, str]:
    """Сигнал порога: только сообщение Никите в чат. Сессии монитор ничего не указывает (Никита, 2026-11-05)."""
    return (f'Контекст занят на {pct:.0f} % ({C.fmt_tokens(tok)} из {C.fmt_tokens(win)}). Можно сжать разговор: /compact.', '')


def check_marks(data: dict, st: dict, marks: tuple):
    """Новый порог: (уровень, Никите, сессии) или None. Число — usage последнего ответа журнала."""
    sid = data.get('session_id') or ''
    resp = data.get('tool_response')
    if resp is not None and data.get('tool_name') in EDIT_TOOLS:
        resp = ''     # во входе хука у правки — весь файл (originalFile, content), а модель видит одну строку «updated»
    pending = (data.get('tool_use_id'), resp) if resp is not None else None
    tok = C.context_tokens(data.get('transcript_path') or st.get('transcript'), pending)
    if tok is None:
        return None
    win = C.window_of(sid)
    pct = tok * 100 / win
    st['tokens'], st['pct'] = tok, round(pct, 2)
    rearm(st, pct)
    new = [m for m in marks if pct >= m and m not in st['fired']]
    if not new:
        return None
    st['fired'] = sorted(set(st['fired']) | {m for m in marks if m <= max(new)})
    level = marks.index(max(new))
    return (level, *texts(level, pct, tok, win, sid, marks))


REARM = 3                                          # порог снова взведён, когда контекст ниже него на столько процентов


def rearm(st: dict, pct: float) -> None:
    """Порог, сработавший по завышенной оценке, снова взведён, когда контекст опустился ниже него на REARM: иначе один
    ложный сигнал гасит порог до конца окна, и на настоящих 85 и 90 % монитор молчит (2026-10-24: у сессии сработали
    все четыре порога при настоящих 75 %). Вопрос о сжатии, заданный на ложном пороге, тоже не засчитывается."""
    keep = [m for m in st['fired'] if pct >= m - REARM]
    if keep != st['fired']:
        st['fired'] = keep
        st['asked'] = min(st['asked'], max(keep, default=0))


def unread(st: dict) -> list[str]:
    return [v['show'] for v in st['must_read'].values() if not v.get('read')]


# ── события ──

def notice(data, st, marks):
    """Порог пройден — сообщение Никите в чат. Ход не держит, скиллы не запрещает, вопросов не требует."""
    st['stop_blocks'] = 0
    st.pop('note', None)
    fired = check_marks(data, st, marks)
    return ({'systemMessage': fired[1]} if fired else {}), 0


def on_prompt(data, st, marks):
    return notice(data, st, marks)


def on_post(data, st, marks):
    return notice(data, st, marks)


def on_skill(data, st, marks):
    return {}, 0


def on_stop(data, st, marks):
    return notice(data, st, marks)


def _pending_by_cwd() -> dict:
    try:
        return json.loads(PENDING.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def on_start(data, st, marks):
    sid, cwd = data.get('session_id') or '', data.get('cwd') or st.get('cwd') or ''
    st['transcript'] = data.get('transcript_path') or st.get('transcript')
    st['cwd'] = cwd
    st['scratchpad'] = data.get('scratchpad_dir') or st.get('scratchpad')
    src = data.get('source')
    if src == 'startup':
        C.prune()
    if src == 'clear':                                 # /clear — окно с нуля: пороги снова взведены, передачи нет
        st.update(fired=[], asked=0, stop_blocks=0, must_read={}, note=None, handoff=None, handoff_mark=0)
    if src != 'compact':
        return {}, 0
    pend = st.get('pending')
    if not pend:                                       # у сессии после сжатия может быть новый номер — по папке
        rec = _pending_by_cwd().get(C.norm(cwd)) if cwd else None
        if rec and time.time() - rec.get('time', 0) < 6 * 3600:
            pend = rec.get('path')
            st['last_trigger'] = rec.get('trigger') or st.get('last_trigger')   # для текста пробуждения
    st.update(fired=[], asked=0, stop_blocks=0, handoff=None, handoff_mark=0, pending=None,
              compactions=st.get('compactions', 0) + 1)
    if not pend or not os.path.isfile(pend):
        st.update(must_read={}, restored=None, restored_at=time.time())
        ctx = ('Монитор контекста: разговор сжат, а передачи монитор не нашёл. Перескажи Никите своими словами, где мы, '
               'по сводке, и спроси, верно ли, прежде чем продолжать.')
        return {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': ctx}}, 0
    text = Path(pend).read_text(encoding='utf-8')
    items = H.read_list(text, cwd)
    body = text
    if len(text) > CTX_MAX:
        items.append((pend, C.norm(pend)))
        body = text[:CTX_MAX] + f'\n\n… [передача длиннее — дочитай файл {pend} целиком]'
    st['must_read'] = {}
    st['restored'] = pend
    st['restored_at'] = time.time()
    head = 'Разговор сжат. Ниже — передача, собранная до сжатия (копия: ' + str(pend) + ').' + chr(10) + chr(10)
    return {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': head + body},
            'systemMessage': f'Разговор сжат, передача подложена: {C.long_path(pend)}.'}, 0


def on_precompact(data, st, marks):
    sid, cwd = data.get('session_id') or '', data.get('cwd') or st.get('cwd') or ''
    transcript = data.get('transcript_path') or st.get('transcript')
    st['last_trigger'] = data.get('trigger')           # ручное или автоматическое — слово в тексте пробуждения (wake)
    ci = data.get('custom_instructions') or ''
    path = next((p for p in C.HANDOFF_RE.findall(ci) if os.path.isfile(os.path.expanduser(p))), None)
    if path is None and st.get('handoff') and os.path.isfile(st['handoff']):
        path = st['handoff']
    part = H.machine_part(transcript, sid, st)
    if path:
        path = os.path.expanduser(path)
        text = Path(path).read_text(encoding='utf-8')
        text = H.set_machine(text, part)
        Path(path).write_text(text, encoding='utf-8', newline='\n')
    else:
        why = ('Сжатие автоматическое, передачи сессия не написала.' if data.get('trigger') == 'auto'
               else 'Сжатие без передачи: в тексте /compact нет пути к ней, и сессия её не делала.')
        text = H.auto_handoff(part, why, H.research_reads(transcript, cwd))
    C.HANDOFFS.mkdir(parents=True, exist_ok=True)
    copy = C.HANDOFFS / f'{C.safe_id(sid)}-{time.strftime("%Y%m%d-%H%M%S")}.md'
    copy.write_text(text, encoding='utf-8', newline='\n')
    shown = str(copy).replace('\\', '/')
    st['pending'] = shown
    reg = _pending_by_cwd()
    if cwd:
        reg[C.norm(cwd)] = {'path': shown, 'sid': sid, 'time': time.time(), 'trigger': data.get('trigger')}
        C._write_json(PENDING, reg)
    return {}, 0


WAKE_WAIT = 5.0                                    # сколько ждать отметки хука start, с
WAKE_FRESH = 60                                    # отметка start свежая, если поставлена не раньше стольких секунд до wake


def wake(data: dict, wait: float = WAKE_WAIT) -> tuple[str, int]:
    """SessionStart после сжатия, в фоне (asyncRewake): разбудить сессию, чтобы она сама начала с передачи. После
    /compact Claude Code хода не даёт — модель ждёт сообщения человека; фоновый хук с кодом 2 будит её сразу, его текст
    она получает напоминанием. Будит после ручного и после автоматического сжатия (Никита, 2026-11-06); если ход после
    автосжатия уже идёт, текст приходит в него напоминанием, и сессия просто продолжает. Ход не держится, вопросов не
    требует. Синхронный хук start подкладывает передачу параллельно — дождаться его отметки (не дольше wait секунд)."""
    if data.get('agent_id') or (data.get('source') or 'compact') != 'compact':
        return '', 0
    sid = data.get('session_id') or ''
    t0 = time.time()
    st = C.load(sid)
    while (st.get('restored_at') or 0) < t0 - WAKE_FRESH and time.time() - t0 < wait:
        time.sleep(0.1)
        st = C.load(sid)
    fresh = (st.get('restored_at') or 0) >= t0 - WAKE_FRESH
    how = {'manual': ' вручную', 'auto': ' автоматически'}.get(st.get('last_trigger') or '', '')
    head = f'Монитор контекста: разговор сжат{how}.'
    pend = st.get('restored') if fresh else None
    if pend:
        return (f'{head} Передача подложена в начало контекста, её копия — {C.long_path(pend)}. Прочитай целиком каждый '
                'файл из её раздела «Прочитать целиком» и продолжай с её первого шага. Если ход после сжатия уже идёт, '
                'это не новое задание: дочитай то, что ещё не прочитано, и продолжай.'), 2
    return (f'{head} Передачи монитор не подложил — продолжай по сводке сжатия и по указанию монитора в начале '
            'контекста, если оно есть.'), 2


HANDLERS = {'prompt': on_prompt, 'post': on_post, 'skill': on_skill, 'stop': on_stop,
            'start': on_start, 'precompact': on_precompact}


def run(event: str, data: dict, marks: tuple = C.MARKS) -> tuple[dict, int]:
    """Одно событие: (вывод JSON, код выхода). Агентам — ничего; ошибка — в журнал монитора, ход не трогается."""
    if data.get('agent_id') or event not in HANDLERS:
        return {}, 0
    sid = data.get('session_id') or ''
    with C.Lock(sid):
        st = C.load(sid)
        out, code = HANDLERS[event](data, st, marks)
        C.save(sid, st)
    return out, code


def main() -> int:
    args = sys.argv[1:]
    event = args[0] if args else ''
    try:
        marks = C.marks_from(args[args.index('--marks') + 1]) if '--marks' in args else C.MARKS
        data = json.loads(sys.stdin.buffer.read().decode('utf-8') or '{}')
        if event == 'wake':                            # фоновый: текст — в stderr, код 2 будит сессию
            text, code = wake(data)
            if text:
                sys.stderr.write(text + '\n')
            return code
        out, code = run(event, data, marks)
    except Exception as e:  # noqa: BLE001 — хук стоит во всех сессиях машины: сбой не должен мешать работе
        C.log(f'ctxHooks {event}: {type(e).__name__}: {e}')
        return 0
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return code


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())
