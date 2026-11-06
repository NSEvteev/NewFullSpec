"""Передача после сжатия — копия шаблона handoff-template.md, машинная часть и проверка, что передача заполнена.

Сессия зовёт скрипт, когда Никита согласился сжать разговор (сигнал монитора называет команду с номером сессии):
скрипт копирует шаблон в папку сессии (scratchpad — правка там без вопросов о доступе), сам заполняет «Машинную часть»
(последние слова Никиты дословно, и из очереди; вызванные скиллы; правленые файлы) и печатает строку /compact. Сессия
дописывает разделы через Edit, проверяет --check, всегда вычитывает передачу глазами новой сессии (вопросы печатает
--check, READ_THROUGH) и даёт Никите строку. Перед сжатием хук PreCompact находит передачу
по пути в тексте /compact, освежает машинную часть и кладёт копию в handoffs/; после сжатия SessionStart её подкладывает.

  PYTHONIOENCODING=utf-8 python ~/.claude/ctxmon/ctxHandoff.py --session <session_id>    новая передача
  PYTHONIOENCODING=utf-8 python ~/.claude/ctxmon/ctxHandoff.py --check <путь>            заполнена ли
"""
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ctxCore as C  # noqa: E402

HUMAN = ('Где мы', 'Что сделано с прошлого сжатия', 'Что сейчас и первый шаг после сжатия',
         'Решения Никиты, ещё не внесённые в файлы', 'Что ждём', 'Прочитать целиком', 'Чего не делать')
MACHINE = 'Машинная часть'                         # её пишет скрипт и перед сжатием — хук заново: руками не править
COMMENT = re.compile(r'<!--.*?-->', re.S)
MSG_MAX, MSGS_TOTAL, MSGS_N = 2500, 9000, 15      # сообщение Никиты, все сообщения, сколько последних


def sections(text: str) -> dict:
    """Разделы «## Заголовок» → тело (как в файле, с комментариями)."""
    out, key, buf = {}, '', []
    for ln in text.splitlines():
        m = re.match(r'^## (.+?)\s*$', ln)
        if m:
            out[key] = '\n'.join(buf)
            key, buf = m.group(1), []
        else:
            buf.append(ln)
    out[key] = '\n'.join(buf)
    return out


def read_list(text: str, cwd: str | None) -> list[tuple[str, str]]:
    """«Прочитать целиком» → [(как написано, путь для сравнения)]: путь — в `кавычках` или первым словом пункта."""
    body = COMMENT.sub('', sections(text).get('Прочитать целиком', ''))
    out = []
    for ln in body.splitlines():
        m = re.match(r'^\s*[-*]\s+(.+)$', ln)
        if not m:
            continue
        q = re.search(r'`([^`]+)`', m.group(1))
        raw = q.group(1) if q else m.group(1).split(' — ')[0].split()[0]
        out.append((raw, C.norm(raw, cwd)))
    return out


def check(text: str, cwd: str | None) -> list[str]:
    """Что в передаче не так: нет раздела, «…» вместо текста, пустой список «Прочитать целиком», файла нет на диске."""
    secs = sections(text)
    bad = []
    for name in HUMAN:
        if name not in secs:
            bad.append(f'нет раздела «## {name}»')
            continue
        body = COMMENT.sub('', secs[name]).strip()
        if not body or any(ln.strip() == '…' for ln in body.splitlines()):
            bad.append(f'«{name}»: не заполнен — текст вместо «…» (нечего сказать — «нет»)')
    if 'Прочитать целиком' in secs:
        body = COMMENT.sub('', secs['Прочитать целиком']).strip()
        items = read_list(text, cwd)
        if not items and not re.match(r'^нет\b', body.lower()):
            bad.append('«Прочитать целиком»: ни одного пути — пунктами «- `путь` — зачем» (или «нет», можно с пояснением)')
        for raw, key in items:
            if not os.path.isfile(key):
                bad.append(f'«Прочитать целиком»: файла нет — {raw}')
    return bad


def machine_part(transcript: str | None, sid: str, st: dict) -> str:
    """Машинная часть: время и контекст; сообщения Никиты с прошлого сжатия дословно; скиллы; правленые файлы."""
    es = C.since_compact(C.entries(transcript)) if transcript and os.path.isfile(transcript) else []
    win = C.window_of(sid)
    tok = C.last_tokens(transcript) if transcript else None
    lines = [f'- собрано: {time.strftime("%Y-%m-%d %H:%M")}; сессия `{sid}`; журнал `{transcript or "неизвестен"}`',
             f'- контекст: ' + (f'{tok * 100 / win:.0f} % · {C.fmt_tokens(tok)} из {C.fmt_tokens(win)}' if tok else 'неизвестен'),
             f'- сработавшие пороги монитора: {", ".join(f"{m:g} %" for m in st.get("fired") or []) or "нет"}', '']
    msgs = C.human_messages(es)[-MSGS_N:]
    kept, total = [], 0
    for ts, t in reversed(msgs):                       # последние — важнее: место кончилось — отрезаются ранние
        t = t if len(t) <= MSG_MAX else t[:MSG_MAX] + f' … [ещё {len(t) - MSG_MAX} знаков]'
        if total + len(t) > MSGS_TOTAL and kept:
            break
        kept.append((ts, t))
        total += len(t)
    lines.append(f'**Сообщения Никиты с прошлого сжатия — последние {len(kept)} из {len(C.human_messages(es))}, дословно:**')
    lines.append('')
    for ts, t in reversed(kept):
        lines.append(f'- {C.local_time(ts)} — ' + t.replace('\n', '\n  '))
    if not kept:
        lines.append('- нет')
    skills = C.tool_uses(es, ('Skill',))
    lines += ['', '**Вызванные скиллы:** ' + ('; '.join(
        f'{C.local_time(s["ts"])} /{s["input"].get("skill", "?")}' + (f' {s["input"]["args"]}' if s['input'].get('args') else '')
        for s in skills) or 'нет')]
    files = list(dict.fromkeys(u['input'].get('file_path') or u['input'].get('notebook_path') or ''
                               for u in C.tool_uses(es, ('Write', 'Edit', 'NotebookEdit'))))
    lines += ['', '**Правленые файлы:** ' + (', '.join(f'`{f}`' for f in files if f) or 'нет')]
    return '\n'.join(lines)


def set_machine(text: str, part: str) -> str:
    """Раздел «Машинная часть» — заново: комментарий-подсказка остаётся, тело — part."""
    m = re.search(rf'^## {MACHINE}[ \t]*\n(?:\s*<!--.*?-->\n)?', text, re.M | re.S)
    if not m:
        return text.rstrip() + f'\n\n## {MACHINE}\n\n{part}\n'
    return text[:m.end()] + '\n' + part + '\n'


def research_reads(transcript: str | None, cwd: str | None) -> list[str]:
    """Входы идущего исследования для автоматической передачи: номер — из последнего вызова скилла /research-* с
    номером NNNN, список — `researchWhere.py NNNN --inputs` репо сессии (AveLabCode, research/PROCESS.md, раздел 8):
    после сжатия сессия перечитывает и выводы-входы, а не только файлы своего исследования. Нет research/ или вызова —
    пусто."""
    if not cwd or not transcript or not os.path.isfile(transcript):
        return []
    script = Path(cwd) / 'research' / '.scripts' / 'researchWhere.py'
    if not script.exists():
        return []
    nums = [m.group(1) for s in C.tool_uses(C.since_compact(C.entries(transcript)) or C.entries(transcript), ('Skill',))
            if str(s['input'].get('skill', '')).startswith('research')
            for m in [re.match(r'\s*(\d{4})\b', str(s['input'].get('args') or ''))] if m]
    if not nums:
        return []
    import subprocess
    try:
        r = subprocess.run([sys.executable, str(script), nums[-1], '--inputs'], cwd=cwd, capture_output=True, text=True,
                           encoding='utf-8', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, timeout=60)
    except Exception:
        return []
    return [ln for ln in r.stdout.splitlines() if ln.startswith('- `') and not ln.rstrip().endswith('НЕТ')]


def auto_handoff(part: str, why: str, reads: list[str] | None = None) -> str:
    """Передача без слов сессии — только машинная часть (страховка: сжатие без передачи); reads — пункты «Прочитать
    целиком», если монитор их знает (входы идущего исследования)."""
    return (f'# Передача после сжатия — собрана машиной\n\n{why} Ниже — только то, что монитор достал из журнала. '
            f'Первым делом перескажи Никите своими словами, где мы, по сводке и этим сообщениям, и спроси, верно ли.\n\n'
            f'## Прочитать целиком\n\n{chr(10).join(reads) if reads else "нет"}\n\n## {MACHINE}\n\n{part}\n')


def compact_line(path: str) -> str:
    return (f'/compact Передача — {path} . В сводке — дословно последние решения Никиты и с какого шага продолжать.')


def new(sid: str) -> int:
    with C.Lock(sid):
        st = C.load(sid)
        status = C.load_status(sid)
        transcript = st.get('transcript') or status.get('transcript')
        folder = Path(st.get('scratchpad') or C.HANDOFFS)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'handoff-{time.strftime("%Y%m%d-%H%M%S")}.md'
        text = set_machine(C.TEMPLATE.read_text(encoding='utf-8'), machine_part(transcript, sid, st))
        path.write_text(text, encoding='utf-8', newline='\n')
        shown = str(path).replace('\\', '/')
        st['handoff'] = shown
        st['handoff_mark'] = max(st.get('fired') or [0])
        C.save(sid, st)
    print(f'передача: {shown}')
    print('Заполни через Edit каждый раздел с «…» (машинную часть не трогай), затем проверь:')
    print(f'  PYTHONIOENCODING=utf-8 python ~/.claude/ctxmon/ctxHandoff.py --check {shown}')
    print('Проверка смотрит только форму; понятна ли передача — вычитка глазами новой сессии, её вопросы напечатает --check.')
    print('Когда проверка скажет «передача заполнена» (она же откроет передачу Никите) и вычитка пройдёт, дай Никите путь к передаче и '
          'эту строку — пусть вставит её в чат целиком; после сжатия монитор сам разбудит сессию:')
    print(f'  {compact_line(shown)}')
    return 0


# Вычитка — всегда после --check: проверка видит только, что разделы заполнены и файлы есть, а хватит ли передачи, чтобы
# продолжить, — нет (Никита, 2026-10-26: «Ты делал проверку передачи? Ей хватит чтобы подгрузить весь контекст по 0003 и
# продолжить?»; «Добавь в этот скрипт указание, чтобы ты ВСЕГДА читала, насколько понятна передача»). В тот раз в передаче
# стояло «развилка … с двумя доводами Никиты», а сами доводы нашлись только поиском по файлам.
READ_THROUGH = '''ОБЯЗАТЕЛЬНО — вычитка: прочитай передачу целиком глазами новой сессии, у которой кроме неё и сводки ничего нет.
Ответь себе на каждый вопрос; чего-то нет — допиши через Edit и снова --check:
  1. Первый шаг после сжатия: понятно, что именно делать и какой командой, — без памяти этого разговора?
  2. Каждое решение и довод Никиты, на котором стоит работа, — дословно здесь или с местом, где записан (файл, строка
     или раздел)? Ссылку вида «с доводами Никиты» без самих доводов и без места не оставлять.
  3. «Прочитать целиком» — всё, без чего первый шаг не сделать, и ничего лишнего?
  4. Слова, ярлыки и сокращения, которые знает только этот разговор, объяснены?'''


def main() -> int:
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == '--session':
        return new(a[1])
    if len(a) == 2 and a[0] == '--check':
        p = Path(os.path.expanduser(a[1]))
        if not p.is_file():
            print(f'передачи нет: {a[1]}')
            return 1
        bad = check(p.read_text(encoding='utf-8'), os.getcwd())
        if bad:
            print('передача НЕ заполнена:')
            print('\n'.join(f'  - {b}' for b in bad))
            return 1
        print(f'передача заполнена: {a[1]}; прочитать после сжатия — '
              f'{len(read_list(p.read_text(encoding="utf-8"), os.getcwd()))} файлов')
        print(C.show(str(p)))
        print(READ_THROUGH)
        print('В сообщении Никите — этот путь к передаче (он смотрит её сам, а не пересказ), что показала вычитка по '
              'четырём вопросам, и строка /compact. Скажи ему: после сжатия монитор сам разбудит сессию, писать «продолжай» не нужно.')
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.exit(main())
