# hermes-telegram-widgets

A Telegram bot plugin that renders a **live task board inside the chat** using the HTML widget API introduced in Bot API 10.4 — one message that stays current instead of a stream of near-identical notifications.

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
```

`send` returns a `message_id`: keep it, it is the only handle for later updates.

### From the shell or cron

```bash
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

## Design notes

- **Fixed code, variable state.** The HTML never changes after sending, so the template is small and stable; only JSON changes.
- **Fingerprint before edit.** An identical state would return `message is not modified`; skipping the call entirely also avoids consuming the send rate limit.
- **No mtime gate in the watcher.** SQLite in WAL mode writes to `kanban.db-wal`, so the main file's mtime often does not move. The watcher re-reads a handful of rows every tick instead of trusting the file timestamp.
- **Graceful deletion.** If the message is gone, the widget is dropped from the registry instead of retrying forever.

## Not implemented (yet)

- interactive buttons: requires handling the `widget_query` update server-side and answering within 15 seconds
- shared widgets (`is_shared` + `sendSharedWidget`): one board mirrored in several chats with a single state

## License

MIT — see [LICENSE](LICENSE).
