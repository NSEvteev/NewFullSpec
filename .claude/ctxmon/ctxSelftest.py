"""Самопроверка монитора контекста на подставленных журналах — до включения и после каждой правки скриптов монитора.

Всё — во временной папке (CTXMON_HOME): настоящие состояния сессий и передачи не трогаются. Журналы разговора —
придуманные: ответы с usage, сообщения Никиты (и из очереди), вызовы скиллов и правки файлов, сводка сжатия.

Проверяет: пороги срабатывают по одному разу, перескок — один сигнал; ход держится до вопроса о сжатии и отпускается
после трёх раз; с 85 % скилл не начинается без вопроса; передача — копия шаблона с машинной частью, незаполненная
ловится, ручное сжатие с ней не начинается; после сжатия передача подкладывается (и сессии с новым номером — по папке);
чтение целиком засчитывается, кусками — нет; ход держится, пока не прочитано всё; после сводки сжатия прежнее число
не берётся; автономная не спрашивает, а пишет передачу; агентам — ничего; порченый вход хука не роняет; строка
состояния. Последней — проверка самого протокола: хук запускается командой, JSON на входе, JSON на выходе.

  PYTHONIOENCODING=utf-8 python ~/.claude/ctxmon/ctxSelftest.py        итог — «Самопроверка: всё сходится.»
  ... -v                                                               и что вернул каждый хук
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix='ctxmon-selftest-'))
os.environ['CTXMON_HOME'] = str(TMP / 'home')
os.environ['CTXMON_NO_OPEN'] = '1'                     # передачи в самопроверке у Никиты не открывать
os.environ.pop('CTXMON_AUTONOMOUS', None)
(TMP / 'home').mkdir()
shutil.copy(HERE / 'handoff-template.md', TMP / 'home' / 'handoff-template.md')
sys.path.insert(0, str(HERE))
import ctxCore as C  # noqa: E402 — после CTXMON_HOME: папка состояний — временная
import ctxHandoff as H  # noqa: E402
import ctxHooks as K  # noqa: E402
import ctxStatus as S  # noqa: E402

VERBOSE = '-v' in sys.argv[1:]
FAILS = []
WIN = 1_000_000


def check(ok, what, more=''):
    print(f'  {"да " if ok else "НЕТ"}  {what}' + (f' — {more}' if more and (VERBOSE or not ok) else ''))
    if not ok:
        FAILS.append(what)


# ── придуманный журнал ──

def asst(tokens, tool=None, inp=None, ts='2026-10-24T10:00:00Z', tid='t1'):
    content = [{'type': 'text', 'text': 'ответ'}]
    if tool:
        content.append({'type': 'tool_use', 'id': tid, 'name': tool, 'input': inp or {}})
    return {'type': 'assistant', 'timestamp': ts, 'message': {'model': 'claude-opus-5-5', 'content': content, 'usage': {
        'input_tokens': 2, 'cache_read_input_tokens': tokens - 1002, 'cache_creation_input_tokens': 1000}}}


def user(text, ts='2026-10-24T09:59:00Z'):
    return {'type': 'user', 'timestamp': ts, 'message': {'role': 'user', 'content': text}}


def queued(text, ts='2026-10-24T10:01:00Z'):
    return {'type': 'attachment', 'timestamp': ts, 'attachment': {
        'type': 'queued_command', 'prompt': text, 'origin': {'kind': 'human'}, 'timestamp': ts}}


SUMMARY = {'type': 'user', 'isCompactSummary': True, 'message': {'content': 'This session is being continued …'}}


class Session:
    """Придуманная сессия: журнал, ввод хуков, состояние."""

    def __init__(self, sid, cwd=None):
        self.sid, self.cwd = sid, str(cwd or TMP / 'repo')
        self.path = TMP / f'{sid}.jsonl'
        self.path.write_text('', encoding='utf-8')
        self.scratch = TMP / f'{sid}-scratchpad'
        self.scratch.mkdir(exist_ok=True)
        C.save_status(sid, {'window': WIN})

    def add(self, *es):
        with open(self.path, 'a', encoding='utf-8') as f:
            for e in es:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')

    def at(self, pct, tool=None, inp=None):
        self.add(asst(int(pct * WIN / 100), tool, inp))

    def hook(self, event, marks=C.MARKS, **extra):
        data = {'session_id': self.sid, 'transcript_path': str(self.path), 'cwd': self.cwd,
                'scratchpad_dir': str(self.scratch), 'hook_event_name': event, **extra}
        with quiet():
            out, code = K.run(event, data, marks)
        if VERBOSE:
            print(f'        {event}: код {code}, {json.dumps(out, ensure_ascii=False)[:220]}')
        return out, code

    @property
    def st(self):
        return C.load(self.sid)


def ctx(out):
    return (out.get('hookSpecificOutput') or {}).get('additionalContext', '')


def quiet():
    """Печать скриптов (передача, отказ в сжатии) — только с -v: на глаза — только названия проверок."""
    if VERBOSE:
        return contextlib.nullcontext()
    stack = contextlib.ExitStack()
    sink = io.StringIO()
    stack.enter_context(contextlib.redirect_stdout(sink))
    stack.enter_context(contextlib.redirect_stderr(sink))
    return stack


def new_handoff(sid):
    with quiet():
        return H.new(sid)


def main():
    (TMP / 'repo').mkdir()
    a_md, b_md = TMP / 'repo' / 'a.md', TMP / 'repo' / 'b.md'
    a_md.write_text('a', encoding='utf-8')
    b_md.write_text('b', encoding='utf-8')

    print('Пороги: только сообщение в чат, ход не держится:')
    s = Session('s1')
    s.hook('start', source='startup')
    s.add(user('Начинаем шаг 2'), queued('и проверь отрезок'))
    s.at(40, 'Skill', {'skill': 'research-proof', 'args': '0001 02'})
    out, _ = s.hook('post', tool_name='Skill', tool_input={'skill': 'research-proof'})
    check(not out, '40 % — сигнала нет')
    s.at(51)
    out, _ = s.hook('post', tool_name='Bash', tool_input={})
    check('50 %' in out.get('systemMessage', '') or '51 %' in out.get('systemMessage', ''), '51 % — Никите сообщение в чат', out.get('systemMessage', ''))
    check(not ctx(out), '51 % — сессии никаких указаний')
    s.at(52)
    out, _ = s.hook('post', tool_name='Bash', tool_input={})
    check(not out, '52 % — порог 50 не повторяется')
    out, _ = s.hook('stop', stop_hook_active=False)
    check('decision' not in out, '50 % — ход не держится')
    s.at(76, 'Edit', {'file_path': str(a_md)})
    out, _ = s.hook('post', tool_name='Edit', tool_input={'file_path': str(a_md)})
    check('Можно сжать' in out.get('systemMessage', ''), '76 % — Никите в чат предложение сжать', out.get('systemMessage', ''))
    check(not ctx(out), '76 % — сессии никаких указаний')
    out, _ = s.hook('stop', stop_hook_active=False)
    check('decision' not in out, '76 %, никто не спрашивал — ход кончается')
    s.at(86)
    out, _ = s.hook('post', tool_name='Bash', tool_input={})
    check('Можно сжать' in out.get('systemMessage', '') and not ctx(out), '86 % — снова только сообщение в чат')
    out, _ = s.hook('skill', tool_name='Skill', tool_input={'skill': 'research-final'})
    check(not out, '86 % — новый скилл начинается без вопроса')
    out, _ = s.hook('stop', stop_hook_active=False)
    check('decision' not in out, '86 % — ход кончается')

    j = Session('s2')
    j.at(40)
    j.hook('post', tool_name='Bash', tool_input={})
    j.at(91)
    out, _ = j.hook('post', tool_name='Bash', tool_input={})
    check('Можно сжать' in out.get('systemMessage', '') and j.st['fired'] == [50, 75, 85, 90],
          'перескок 40 → 91 % — один сигнал о старшем пороге, все пороги отмечены', str(j.st['fired']))

    s.add(asst(int(0.87 * WIN), 'Skill', {'skill': 'research-final', 'args': 'отклонён'}, tid='denied'),
          {'type': 'user', 'toolUseResult': 'Error', 'message': {'role': 'user', 'content': [
              {'type': 'tool_result', 'tool_use_id': 'denied', 'is_error': True, 'content': 'PreToolUse:Skill hook error'}]}})

    q = Session('s2b')
    q.at(45, 'Read', {'file_path': 'большой.md'})
    big = 'ж' * int(0.06 * WIN * C.CHARS_PER_TOKEN)        # результат чтения ~60 тыс. токенов — модель его ещё не посчитала
    q.add({'type': 'user', 'toolUseResult': {}, 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 't1', 'content': big}]}})
    out, _ = q.hook('post', tool_name='Read', tool_input={'file_path': 'большой.md'}, tool_use_id='t1',
                    tool_response={'file': {'content': big}})
    check(q.st['fired'] == [50] and 50 <= q.st['pct'] < 52, 'чтение файла после ответа считается: 45 % + ~6 % — порог 50, '
          'и ответ инструмента не посчитан дважды', str(q.st.get('pct')))
    r2 = Session('s2c')
    r2.at(45, 'Read', {'file_path': 'другой.md'})
    out, _ = r2.hook('post', tool_name='Read', tool_input={'file_path': 'другой.md'}, tool_use_id='t1',
                     tool_response={'file': {'content': big}})
    check(r2.st['fired'] == [50], 'ответа инструмента ещё нет в журнале — берётся из входа хука', str(r2.st.get('pct')))

    im = Session('s2d')                                  # Read картинки: в хук она приходит base64-текстом
    im.at(45, 'Read', {'file_path': 'снимок.png'})
    pic = {'type': 'image', 'file': {'base64': 'A' * 600_000, 'type': 'image/png', 'originalSize': 450_000}}
    im.hook('post', tool_name='Read', tool_input={'file_path': 'снимок.png'}, tool_use_id='t1', tool_response=pic)
    check(im.st['fired'] == [] and im.st['pct'] < 46, 'Read картинки — ~1,6 тыс., а не длина base64: на 45 % сигнала нет',
          str(im.st.get('pct')))
    fa = Session('s2e')                                  # ложный порог по оценке снова взводится, когда число настоящее
    fa.at(60, 'Read', {'file_path': 'огромный.md'})
    huge = 'ж' * int(0.17 * WIN * C.CHARS_PER_TOKEN)
    fa.hook('post', tool_name='Read', tool_input={'file_path': 'огромный.md'}, tool_use_id='t1',
            tool_response={'file': {'content': huge}})
    fired_false = list(fa.st['fired'])                 # оценка: 60 % + ~17 % ещё не посчитанного чтения
    fa.hook('post', tool_name='AskUserQuestion', tool_input={'questions': [{'question': 'Сжать разговор?'}]})
    fa.at(62)
    fa.hook('post', tool_name='Bash', tool_input={})
    check(fired_false == [50, 75] and fa.st['fired'] == [50] and fa.st['asked'] <= 50,
          'оценка 77 %, настоящее 62 % — порог 75 снова взведён, вопрос на ложном пороге не засчитан',
          f'{fired_false} → {fa.st["fired"]}, asked {fa.st["asked"]}')
    fa.at(76)
    out, _ = fa.hook('post', tool_name='Bash', tool_input={})
    check('Можно сжать' in out.get('systemMessage', ''), 'настоящие 76 % — порог 75 срабатывает снова')

    print('\nПередача и сжатие:')
    rc = new_handoff('s1')
    path = s.st.get('handoff')
    text = Path(path).read_text(encoding='utf-8') if path else ''
    check(rc == 0 and path and Path(path).parent == s.scratch, 'передача — копия шаблона в папке сессии', path or '')
    check('Начинаем шаг 2' in text and '[в очереди] и проверь отрезок' in text, 'машинная часть: слова Никиты дословно, и из очереди')
    check('/research-proof 0001 02' in text and str(a_md) in text, 'машинная часть: вызванные скиллы и правленые файлы')
    check('отклонён' not in text, 'скилл, который монитор не пустил, в «Вызванные скиллы» не попадает')
    bad = H.check(text, s.cwd)
    check(len(bad) >= 7, 'незаполненная передача ловится — по разделу', f'{len(bad)}: {bad[:2]}')
    out, code = s.hook('precompact', trigger='manual', custom_instructions=f'Передача — {path} . ещё')
    check(code == 0, 'ручное сжатие с незаполненной передачей не останавливается')
    filled = text
    for name in H.HUMAN:
        val = '- `a.md` — вход\n- `' + str(b_md) + '` — второй' if name == 'Прочитать целиком' else f'текст: {name}'
        filled = filled.replace(f'## {name}\n', f'## {name}\n@@{name}@@\n', 1)
        head, _, rest = filled.partition(f'@@{name}@@\n')
        rest = rest.replace('…', val, 1)
        filled = head + rest
    Path(path).write_text(filled, encoding='utf-8')
    check(not H.check(filled, s.cwd), 'заполненная передача проходит проверку', str(H.check(filled, s.cwd)))
    no_read = re.sub(r'(## Прочитать целиком\n(?:<!--.*?-->\n)?\n).*?(?=\n## )', r'\1нет — после сжатия читать нечего\n',
                     filled, count=1, flags=re.S)
    check(not H.check(no_read, s.cwd), '«Прочитать целиком»: «нет» с пояснением проходит', str(H.check(no_read, s.cwd)))
    broken = filled.replace('`a.md`', '`нет-такого.md`')
    check(any('файла нет' in b for b in H.check(broken, s.cwd)), 'путь «Прочитать целиком», которого нет на диске, ловится')
    s.add(user('сжимаем, го компакт'))
    out, code = s.hook('precompact', trigger='manual', custom_instructions=f'Передача — {path} . ещё')
    pend = s.st.get('pending')
    check(code == 0 and pend and Path(pend).is_file() and Path(pend).parent == C.HANDOFFS,
          'ручное сжатие с заполненной передачей — копия в handoffs/')
    check('сжимаем, го компакт' in Path(pend).read_text(encoding='utf-8'), 'перед сжатием машинная часть освежена')
    s.add(SUMMARY)
    out, _ = s.hook('post', tool_name='Bash', tool_input={})
    check(not out, 'после сводки сжатия прежнее число не берётся — сигналов нет')
    out, _ = s.hook('start', source='compact')
    check('текст: Где мы' in ctx(out), 'после сжатия передача подложена сессии')
    check(str(C.HANDOFFS.name) in out.get('systemMessage', ''), 'Никите — путь к передаче')
    check(s.st['fired'] == [] and s.st['must_read'] == {}, 'пороги снова взведены, требований прочитать нет', str(s.st['must_read']))
    text, code = K.wake({'session_id': 's1', 'source': 'compact'})
    check(code == 2 and 'вручную' in text and s.st['restored'].split('/')[-1] in text and '«Прочитать целиком»' in text,
          'после ручного сжатия монитор будит сессию: путь передачи и что прочитать', text)
    text, code = K.wake({'session_id': 's1', 'source': 'compact', 'agent_id': 'a1'})
    check(code == 0 and not text, 'агента после сжатия не будить')
    text, code = K.wake({'session_id': 'никто', 'source': 'compact'}, wait=0.3)
    check(code == 2 and 'не подложил' in text, 'хук start не отметился — всё равно будить, по сводке', text)
    s.at(20, 'Read', {'file_path': str(a_md)})
    out, _ = s.hook('stop', stop_hook_active=False)
    check('decision' not in out, 'после сжатия ход не держится')

    print('\nСтраховка и новая сессия после сжатия:')
    t = Session('s3')
    t.add(user('считаем 5 лет'), asst(500_000, 'Write', {'file_path': str(b_md)}))
    out, code = t.hook('precompact', trigger='auto', custom_instructions=None)
    pend = t.st.get('pending')
    text = Path(pend).read_text(encoding='utf-8') if pend else ''
    check(code == 0 and 'собрана машиной' in text and 'считаем 5 лет' in text,
          'автосжатие без передачи — машинная передача: слова Никиты, правленые файлы')
    u = Session('s3-new', cwd=t.cwd)
    out, _ = u.hook('start', source='compact')
    check('считаем 5 лет' in ctx(out), 'у сессии после сжатия новый номер — передача найдена по папке')
    text, code = K.wake({'session_id': 's3-new', 'source': 'compact'})
    check(code == 2 and 'автоматически' in text and 'Прочитай целиком' in text,
          'после автосжатия монитор тоже будит сессию — и с новым номером', text)

    print('\nЗапуск с CTXMON_AUTONOMOUS:')
    os.environ['CTXMON_AUTONOMOUS'] = '1'
    v = Session('s4')
    v.at(86)
    out, _ = v.hook('post', tool_name='Bash', tool_input={})
    check(not ctx(out), '86 % — сессии никаких указаний')
    out, _ = v.hook('stop', stop_hook_active=False)
    check('decision' not in out, 'ход не держится')
    os.environ.pop('CTXMON_AUTONOMOUS')

    print('\nПорченый вход:')
    w = Session('s5')
    w.at(80)
    out, code = K.run('post', {'session_id': 's5', 'agent_id': 'a1', 'transcript_path': str(w.path), 'tool_name': 'Bash'})
    check(not out and code == 0 and not w.st['fired'], 'агенту — ничего')
    out, code = K.run('post', {'session_id': 's6', 'transcript_path': str(TMP / 'нет.jsonl'), 'tool_name': 'Bash'})
    check(not out and code == 0, 'журнала нет — ничего, без падения')
    try:
        C.marks_from('1,2,3')
        check(False, '--marks из трёх чисел ловится')
    except ValueError:
        check(True, '--marks из трёх чисел ловится')
    check(C.marks_from('1,2,3,4') == (1, 2, 3, 4), '--marks 1,2,3,4 — пороги пробной сессии')
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    r = subprocess.run([sys.executable, str(HERE / 'ctxHooks.py'), 'post'], input=b'{oops', capture_output=True, env=env)
    check(r.returncode == 0 and not r.stdout and 'ctxHooks post' in (C.LOG.read_text(encoding='utf-8') if C.LOG.exists() else ''),
          'испорченный JSON на входе — код 0, вывода нет, запись в журнал монитора')

    target = C.STATE / 'busy.status.json'
    C._write_json(target, {'n': 1})
    held = open(target, encoding='utf-8')                # другой процесс читает файл — подмена на Windows не проходит
    threading.Timer(0.1, held.close).start()
    try:
        C._write_json(target, {'n': 2})
        ok = json.loads(target.read_text(encoding='utf-8')).get('n') == 2
    except OSError:
        ok = False
    check(ok, 'файл сессии занят чтением — запись проходит со второй попытки, без ошибки')

    print('\nСтрока состояния и протокол хука:')
    S_line = S.line({'session_id': 's7', 'context_window': {'used_percentage': 54, 'total_input_tokens': 540_000,
                                                             'context_window_size': 1_000_000}})
    check('контекст 54 % · 540 тыс. из 1 млн' in S_line and C.load_status('s7').get('window') == 1_000_000,
          'строка «контекст 54 % · 540 тыс. из 1 млн», окно — в файл сессии', S_line)
    check('контекст —' in S.line({'session_id': 's8', 'context_window': {'context_window_size': 200_000}}),
          'в начале сессии чисел ещё нет — строка без них, без падения')
    x = Session('s9')
    x.at(60)
    data = {'session_id': 's9', 'transcript_path': str(x.path), 'cwd': x.cwd, 'tool_name': 'Bash', 'tool_input': {}}
    r = subprocess.run([sys.executable, str(HERE / 'ctxHooks.py'), 'post'], input=json.dumps(data).encode('utf-8'),
                       capture_output=True, env=env)
    try:
        got = json.loads(r.stdout.decode('utf-8'))
    except ValueError:
        got = {}
    check(r.returncode == 0 and 'systemMessage' in got and 'hookSpecificOutput' not in got, 'хук командой: JSON на входе — один объект JSON на выходе', r.stdout[:120])

    shutil.rmtree(TMP, ignore_errors=True)
    print('\nСамопроверка: ' + ('всё сходится.' if not FAILS else f'НЕ сходится — {len(FAILS)}: ' + '; '.join(FAILS)))
    return 1 if FAILS else 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())
