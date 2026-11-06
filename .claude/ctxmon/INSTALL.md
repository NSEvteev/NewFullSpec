# Монитор контекста — установка на машину

Эта папка — копия монитора контекста Claude Code, чтобы поставить его на другую машину. Сам монитор живёт не в репо, а в папке машины `~/.claude/ctxmon/`, и работает для всех сессий на ней. Он показывает в строке состояния, сколько контекста занято, и на порогах предлагает человеку, который работает в сессии, сжать разговор сообщением в чат. Перед сжатием он собирает передачу следующей сессии, а после любого сжатия, ручного и автоматического, сам будит сессию: она читает файлы из передачи и продолжает с её первого шага. Как он устроен — [README.md](README.md). Передачу пишет скилл `/handoff`: он лежит в `.claude/skills/` каждого репо, сделанного из этого шаблона.

**Источник — `~/.claude/ctxmon/` основной машины, здесь его копия.** Монитор правят там, а после правки копируют файлы сюда и коммитят в шаблон (раздел «Обновить копию»). Правка, сделанная только здесь, пропадёт при следующем копировании.

## Что нужно на машине

- Claude Code. Команды хуков идут через bash, на Windows — через Git Bash.
- `python` в PATH — 3.12, на нём монитор проверен.
- VS Code с командой `code` — по желанию: проверка передачи (`ctxHandoff.py --check`, шаг 6 `/handoff`) открывает передачу там, а без него — программой по умолчанию.

## Установить

Команды — из корня любого репо, сделанного из шаблона, в Bash. Настройки шага 2 сразу задевают все сессии Claude Code на машине. Сначала посмотреть монитор, не трогая настройки машины, можно пробной сессией после шага 1: `claude --settings ~/.claude/ctxmon/trial-settings.json` — пороги в ней 7, 8, 9 и 10 %.

### 1. Файлы монитора — в папку машины

Папки `state/`, `handoffs/` и файлы `pending.json`, `ctxmon.log` монитор создаст сам.

```bash
mkdir -p ~/.claude/ctxmon && cd .claude/ctxmon && cp ctxCore.py ctxStatus.py ctxHooks.py ctxHandoff.py ctxSelftest.py README.md handoff-template.md trial-settings.json ~/.claude/ctxmon/ && cd -
```

### 2. Строка состояния и хуки — в `~/.claude/settings.json`

Команда берёт разделы `statusLine` и `hooks` из [machine-settings.json](machine-settings.json). Свою строку состояния, если она была, монитор заменяет: прежний `settings.json` целиком команда один раз сохраняет рядом, в `settings.json.before-ctxmon`, и при повторном запуске его не перезаписывает. В `hooks` команда заменяет только записи монитора (команды с `/ctxmon/`): чужие хуки и остальные настройки остаются как были, повторный запуск ничего не удваивает.

```bash
PYTHONIOENCODING=utf-8 python - <<'EOF'
import json, os, shutil
src = json.load(open('.claude/ctxmon/machine-settings.json', encoding='utf-8'))
p = os.path.expanduser('~/.claude/settings.json')
d = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
if os.path.exists(p) and not os.path.exists(p + '.before-ctxmon'):
    shutil.copyfile(p, p + '.before-ctxmon')
d['statusLine'] = src['statusLine']
hooks = d.setdefault('hooks', {})
for event, items in src['hooks'].items():
    hooks[event] = [h for h in hooks.get(event, []) if '/ctxmon/' not in json.dumps(h)] + items
os.makedirs(os.path.dirname(p), exist_ok=True)
with open(p, 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
print('записано:', p)
EOF
```

**Пробуждение после сжатия** — второй элемент `SessionStart`: `"matcher": "compact"`, команда `ctxHooks.py wake` и `"asyncRewake": true`. Без `asyncRewake` хук выполняется вместе со стартом сессии, и разбудить её ему нечем. Рядом нужны первый элемент `SessionStart` — `ctxHooks.py start`, он подкладывает передачу, — и `PreCompact` — `ctxHooks.py precompact`, он её собирает.

### 3. Проверить

```bash
PYTHONIOENCODING=utf-8 python ~/.claude/ctxmon/ctxSelftest.py
echo '{"session_id":"probe","source":"compact"}' | PYTHONIOENCODING=utf-8 python ~/.claude/ctxmon/ctxHooks.py wake; echo $?
```

Самопроверка — «Самопроверка: всё сходится.» Проба пробуждения около 5 секунд ждёт отметку старта сессии, затем печатает «Монитор контекста: разговор сжат. Передачи монитор не подложил — продолжай по сводке сжатия…» и код 2. В пробе передачи нет, так и должно быть: важны текст и код 2 — ими хук будит сессию.

## Выключить

Убрать из `~/.claude/settings.json` раздел `statusLine` и записи `hooks` с командами `~/.claude/ctxmon/`. Прежние настройки целиком — в `settings.json.before-ctxmon`.

## Обновить копию

На основной машине, из корня репо шаблона (не проекта, сделанного из него), после правки монитора и его самопроверки:

```bash
cp ~/.claude/ctxmon/{ctxCore,ctxStatus,ctxHooks,ctxHandoff,ctxSelftest}.py ~/.claude/ctxmon/{README,handoff-template}.md ~/.claude/ctxmon/trial-settings.json .claude/ctxmon/
python architecture/tools/kit.py check
```

`kit.py check` должен дать «находок: 0»: в копии не должно быть абсолютных путей машины. `machine-settings.json` и этот файл живут только здесь, на машину их не копируют. Поменялись хуки в `trial-settings.json` — поправить и `machine-settings.json`: там те же хуки без `--marks 7,8,9,10`.
