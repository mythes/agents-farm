# agents-farm

Термінальний дашборд для агентів Claude Code: хто зараз працює, що робить, скільки контексту з'їв і скільки лишилось лімітів по моделях.

Прототип: варіант **A** (список | деталі | ліміти) з [docs/tui-design.md](docs/tui-design.md), джерело даних — **сесії Claude Code** (спостерігач).

## Запуск

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

```bash
.venv/bin/agents-farm            # живі сесії з ~/.claude/projects
.venv/bin/agents-farm --demo     # фейкові дані, щоб помацати UI
.venv/bin/agents-farm --since 24 # показувати сесії за останні 24 год
```

Однорядковий статус (для tmux / statusline) і JSON для скриптів:

```bash
.venv/bin/agents-farm status          # ?1 ●2 │ sonnet 25% │ opus 7%
.venv/bin/agents-farm status --json
```

## Клавіші

| Клавіша | Дія |
|---|---|
| `↑↓` / `j k` | рух по агентах |
| `enter` / `z` | zoom: деталі на весь екран, `esc` — назад |
| `1` `2` `3` | згорнути/розгорнути Context / Activity / Plan |
| `e` | розгорнути / згорнути все |
| `/` | фільтр: текст, `status:waiting`, `model:opus`, `project:api` |
| `h` | показати / сховати idle-сесії та завершені субагенти |
| `y` | скопіювати `cd … && claude --resume <id>` (OSC 52, працює і через ssh) |
| `o` | повний лог агента в `$PAGER` |
| `?` | довідка |

Агенти, що **чекають на тебе** (`?`) і з **помилкою** (`!`), завжди вгорі. При переході в ці стани — сповіщення + дзвіночок. Субагенти показуються під батьківською сесією (`└`).

## Звідки дані

1. **Транскрипти** `~/.claude/projects/**/*.jsonl` — читаються інкрементально (лише дописане). З них: промпт, кроки (tool calls), файли, план (TodoWrite / update_plan), токени, модель, контекст.
2. **Hooks** (рекомендовано) — без них статус «чекає дозволу» лише вгадується (`⏸ stalled`). З хуками — точний `? waiting`.

### Встановити hooks

Згенерувати блок для `~/.claude/settings.json`:

```bash
.venv/bin/agents-farm hooks-snippet
```

Додай вміст `"hooks"` у свій `~/.claude/settings.json` (злий з наявними хуками, якщо вони є). Хук дописує один рядок у `~/.agents-farm/events.jsonl` (~140 мс на виклик), ніколи не падає і завжди повертає 0. Після цього в шапці буде `hooks ✓`.

## Ліміти — важливо

Claude Code не пише залишок квоти підписки на диск, тому ліміти — **оцінка**: сума токенів (input + output + cache write) по моделі за поточне 5-годинне вікно проти бюджету з конфігу. Бюджети за замовчуванням — **заглушки**, підлаштуй під свій план у `~/.agents-farm/config.json`:

```json
{
  "limits": {"opus": 4000000, "sonnet": 8000000, "haiku": 20000000},
  "window_hours": 5,
  "count_cache_read": false,
  "warn": 0.7,
  "crit": 0.9,
  "since_hours": 12,
  "notify": true
}
```

`0` для моделі = ліміт невідомий, показуються лише токени.

## Безпека і тести

Дані з транскриптів і hooks вважаються недовіреними (prompt injection): див. [SECURITY.md](SECURITY.md).

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/bandit -r agents_farm
```

## Структура

```
agents_farm/
  transcripts.py  інкрементальний парсер JSONL-транскриптів
  events.py       hook-обробник + читач events.jsonl
  store.py        збирає все в Snapshot, виводить статуси
  limits.py       використання по моделях у 5-год вікні
  render.py       Rich-рендер рядків, деталей, лімітів (без Textual)
  app.py          Textual UI
  demo.py         фейкові дані
  cli.py          CLI
```
