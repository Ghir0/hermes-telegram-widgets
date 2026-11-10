# hermes-telegram-widgets

A Telegram bot plugin that renders **live boards inside the chat** using the HTML widget API introduced in Bot API 10.4 — one message that stays current instead of a stream of near-identical notifications.

Four widgets:

- **task board** — what is running, what is queued, what closed
- **agent roster** — which agents exist, who is busy, what each one is doing, and the command to put one to work
- **weather card** — current conditions and a four-day forecast for a place you configure
- **dice** — a d20 (or d4/d6/d8/d10/d12/d100) in fantasy dress, rolled with a CSPRNG

Built as a [Hermes Agent](https://hermes-agent.nousresearch.com/docs) plugin; the rendering and API layer is framework-agnostic and can be reused by any bot.

```
┌──────────────────────────────────┐
│ AGENTI                    17:08  │
├──────────────────────────────────┤
│ ● Bottoni riprova/annulla   1m   │
│ ● Pubblicare il plugin      3m   │
│ ● Widget: agganciare il…    5m   │
│ ○ Documentare i limiti   2h 30m  │
└──────────────────────────────────┘
```

## Why widgets

A widget is **fixed code plus changeable state**. The HTML is sent once and never changes; what changes is `chat_data`, which the bot rewrites with `editMessageWidgetData`. Every update is silent: no "edited" mark, no notification, the chat does not jump. That is the difference between a message that says "3 tasks running" and a card that keeps showing which ones.

## What it does

- reads tasks from the Hermes Kanban SQLite database (`tasks` table)
- sends them as an HTML widget in a private chat
- **refreshes automatically** when the board changes, via a small watcher service
- never sends an identical state twice, so it stays clear of the bot's send rate limit
- derives each agent's state from the Kanban (`running` → busy, `queued` → waiting, otherwise idle) instead of inventing a second source of truth
- activates an agent by queueing a task for it, so the Kanban dispatcher starts the worker as usual

## Installation (Hermes Agent)

```bash
git clone https://github.com/Ghir0/hermes-telegram-widgets.git
cp -r hermes-telegram-widgets ~/.hermes/plugins/telegram-widgets
```

Add the plugin to `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - telegram-widgets
```

Restart the gateway so the plugin's tool is registered.

Requirements: Python 3.10+, no third-party packages. `TELEGRAM_BOT_TOKEN` must be available in the environment or in `~/.hermes/.env`.

## Usage

### As an agent tool

```
widget_board(action="send", caption="Agent board")
widget_board(action="refresh", message_id=5525)

agents_board(action="send")
agents_board(action="show")                                   # roster as JSON
agents_board(action="activate", agent="coder", task="...")     # queue a task

weather_board(action="send")
weather_board(action="show")                                  # data as JSON

dice_board(action="roll", sides=20)                           # roll and send
```

`send` returns a `message_id`: keep it, it is the only handle for later updates.

### Commands

```
hermes widget-board show [--limit 20] [--agent coder]   # print the Kanban in the terminal
hermes widget-board send [--chat ID] [--caption ...]    # task board in chat
hermes widget-board agents [--chat ID]                  # agent roster in chat
hermes widget-board weather [--chat ID] [--force]      # weather card in chat
hermes widget-board dice [--sides 20] [--chat ID]      # roll a die in chat
hermes widget dado|meteo|kanban|agenti                 # one command for every widget
hermes widget-board refresh --message ID                # update a widget now
hermes widget-board drop --message ID                   # delete it and stop tracking
```

The same commands exist as a standalone script, for cron or when the gateway is down:

```bash
python3 cli.py show                       # Kanban in the terminal
python3 cli.py agents --chat ID           # agent roster in chat
python3 cli.py activate --agent coder --task "..."   # queue a task for an agent
python3 cli.py size                       # bytes, raw and compressed
python3 cli.py send --chat 123456789
python3 cli.py refresh --chat 123456789 --message 5525
python3 cli.py drop --chat 123456789 --message 5525   # delete it and stop tracking
python3 watcher.py --once                 # single pass, cron-friendly
```

### Automatic refresh

`watcher.py` polls the Kanban database every 2 seconds, compares a fingerprint of the rendered board and edits the widget only when it differs.

```bash
sudo cp "systemd/widget-board-watcher@.service" /etc/systemd/system/
sudo systemctl enable --now "widget-board-watcher@$USER"
```

It is a systemd template unit: the instance name is the user that owns the plugin, so `@root` reads `/root/.hermes/plugins/telegram-widgets`. Adjust `WorkingDirectory` if you installed elsewhere.

## The agent roster

```
AGENTI                        18:32
─────────────────────────────────────
● coder        Landing page      attiva coder
● assistant    in coda: ricerca  attiva assistant
○ scientist    libero            attiva scientist
attiva: chiedi «attiva <agente> con <istruzione>»
```

Status codes: `running` (green), `queued` or `blocked` (blue), idle (grey), failed (red). "Activation" is deliberately not a second scheduler: it inserts a `queued` row in `tasks` with that assignee, and the existing Kanban dispatcher does the rest.

## The weather card

```
Pesaro                        18:34
12°                          ☁
nuvoloso
H:13°  L:11°  ·  percepiti 10° · vento 8 km/h
┌────┬────┬────┬────┬────┬────┐
│ora │ 20 │ 21 │ 22 │ 23 │ 00 │
│ ☁  │ ☁  │ ☁  │ ☁  │ ☁  │ ☁  │
│12° │12° │11° │11° │11° │11° │
└────┴────┴────┴────┴────┴────┘
MER  🌦  13° / 11°          93%
GIO  🌦  21° / 15°          75%
VEN  🌧  20° / 11°          82%
chiudi: chiedi «chiudi il meteo»
```

The first hourly column is the current hour, highlighted. Layout follows Telegram's own weather widget: large light-weight temperature, condition line, H/L, then a six-column hour strip.

Data from [Open-Meteo](https://open-meteo.com): free, no API key, no account. The widget has no network access of its own — the bot fetches the numbers and writes them into `chat_data`; the widget only draws them.

Configuration:

| Variable | Default | Meaning |
|---|---|---|
| `WEATHER_LAT` | `43.9102` | latitude |
| `WEATHER_LON` | `12.9136` | longitude |
| `WEATHER_PLACE` | `Pesaro` | label shown in the header |
| `WEATHER_TTL` | `900` | seconds before the data is fetched again |

The watcher refreshes the card only when the published numbers change, so a stable forecast costs no messages. If Open-Meteo is unreachable the last good payload is reused rather than blanking the card.

## The dice

```
D20                            19:52
⬡  16 / 20
   colpo netto
chiudi: «chiudi il dado»
```

The d20 is drawn as inline SVG (hexagon, inner triangle, facet lines) and the result animates on every change. A natural 20 becomes a gold badge — `colpo critico` — and a 1 reads `fallimento critico`.

The roll runs server-side on `secrets.randbelow`, not `random`: a die that can be predicted is not a die. Supported faces: 4, 6, 8, 10, 12, 20, 100; anything else is rejected rather than rounded.

**Tap the card to roll.** The tumble animation and the new number happen inside the widget, with no round trip: a plain DOM click needs no `widget_query`. The small faces row (`d4` … `d100`) switches the die and rolls it at the same time.

Two RNGs, on purpose: the value in the message the bot sends comes from `secrets.randbelow` (CSPRNG); taps roll locally with `crypto.getRandomValues`, falling back to `Math.random` if the sandbox hides it.

If `chat_data` arrives without a usable result the widget rolls locally instead of printing `NaN` — which is exactly what happened when an older watcher refreshed a dice message with the task-board state.

## Configuration

All optional except the token:

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | bot token from @BotFather |
| `TELEGRAM_HOME_CHANNEL` | — | default chat when `--chat` is omitted |
| `HERMES_KANBAN_DB` | `~/.hermes/kanban.db` | Kanban database to read |
| `HERMES_WIDGET_STATE` | `~/.hermes/state/telegram-widgets` | registry of live widgets |
| `HERMES_HOME` | `~/.hermes` | where to look for `.env` |

## API limits that matter

Measured against the live API, not estimated:

| Limit | Value | Consequence |
|---|---|---|
| HTML, raw | 32,768 bytes | rarely the binding constraint |
| **HTML after zlib level 9** | **4,096 bytes** | the real cap; minified markup and short class names |
| `chat_data` / `public_data` | 1,024 bytes each | the board fits 6 rows in 155–226 bytes |
| Bubble | 200–600 px wide, 50–600 px tall | no scrolling: overflow is clipped |
| JS engine | QuickJS | no `fetch`, no external assets, no navigation |
| Chats | private only (production) | widgets cannot be sent to groups |
| Edits | 1 per second per shared widget | the watcher throttles itself |
| Query answer | 15 seconds | only relevant if you enable `allow_queries` |

Check the size before sending:

```bash
python3 -c 'import sys,zlib; print(len(zlib.compress(sys.stdin.buffer.read(),9)))' < widget.html
```

Use Python's zlib: `gzip -9 -n` counts about 12 bytes more and can reject a widget that would have passed.

## Privacy note

Telegram automatically marks sent widgets as **protected content**. Clients therefore refuse screenshots and forwarding for those messages — if a chat suddenly "cannot be screenshotted", a widget in it is the reason. Deleting the widget message restores normal behaviour.

This plugin sends nothing anywhere except `api.telegram.org`, and reads only the local Kanban database. It stores no message text; the registry keeps chat id, message id and a fingerprint of the board.

## Closing a widget

There is no close button, and the reason is structural: a widget can only ask the bot with `TelegramWidget.request()`, which needs `allow_queries=True` **and** a bot that handles the `widget_query` update within 15 seconds. python-telegram-bot does not model that update yet, so it never reaches the handler.

Widgets can expire on their own. The weather card and the agent roster are created with a **120-second lifetime**: the watcher deletes them when the clock runs out, so the chat does not fill with stale cards. The task board is the exception — it has no expiry, because it is meant to stay current, and it is closed when you ask.

The lifetime counts from when the widget is **sent**, not from when it is read: Telegram gives bots no read receipts, and the only "viewed" signal available to a widget (`request()` firing when it appears on screen) needs the `widget_query` update that the gateway cannot handle yet. So a widget you open after two minutes is already gone; refresh it again or set a longer `ttl`.

Instead every widget carries the instruction in its footer:

```
chiudi: chiedi «chiudi il meteo»
```

Say it to the agent and it calls the `drop` action: the message is deleted and the watcher stops tracking it.

```
widget_board(action="drop", message_id=5549)
hermes widget-board drop --message 5549
```

## Design notes

- **Fixed code, variable state.** The HTML never changes after sending, so the template is small and stable; only JSON changes.
- **Fingerprint before edit.** An identical state would return `message is not modified`; skipping the call entirely also avoids consuming the send rate limit.
- **No mtime gate in the watcher.** SQLite in WAL mode writes to `kanban.db-wal`, so the main file's mtime often does not move. The watcher re-reads a handful of rows every tick instead of trusting the file timestamp.
- **State is time-invariant.** Rows carry the absolute minute, not the age: an age changes every minute and would make an unchanged board look changed, so Telegram would repaint the widget once a minute for nothing.
- **One writer at a time.** The registry is read-modify-written under `flock`, and the watcher merges only the fingerprints it computed instead of saving its whole in-memory copy — otherwise a widget sent from the CLI could be erased by the next tick.
- **Graceful deletion.** If the message is gone, the widget is dropped from the registry instead of retrying forever.

## Not implemented (yet)

- interactive buttons: requires handling the `widget_query` update server-side and answering within 15 seconds
- shared widgets (`is_shared` + `sendSharedWidget`): one board mirrored in several chats with a single state

## License

MIT — see [LICENSE](LICENSE).
