"""telegram-widgets — HTML widgets in chat (Bot API 10.4).

Two tools and a CLI:

* ``widget_board``  — the task board: send it, refresh it in place.
* ``agents_board``  — who is on duty, what they are doing, and how to put one to work.

Both render into ``chat_data`` (1024 bytes), so a refresh repaints the bubble without an
"edited" mark, without a notification and without moving the chat.
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from . import agents, board, weather

logger = logging.getLogger(__name__)

WIDGET_BOARD_SCHEMA: dict[str, Any] = {
    "name": "widget_board",
    "description": (
        "Mostra i task degli agenti come widget HTML nella chat Telegram, oppure aggiorna "
        "un widget già inviato. Con action=send crea un nuovo messaggio widget e restituisce "
        "message_id; con action=refresh riscrive lo stato di quel messaggio (silenzioso, "
        "nessun 'modificato', nessuna notifica). Senza 'tasks' legge i task dal Kanban di Hermes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["send", "refresh"],
                       "description": "send = nuovo widget, refresh = aggiorna quello esistente"},
            "chat_id": {"type": "integer",
                        "description": "Chat di destinazione; se omesso usa la chat principale"},
            "message_id": {"type": "integer",
                           "description": "Obbligatorio con action=refresh"},
            "limit": {"type": "integer", "description": "Quanti task mostrare (default 6, max 6)"},
            "caption": {"type": "string", "description": "Didascalia opzionale sotto il widget"},
            "tasks": {
                "type": "array",
                "description": "Task espliciti in alternativa al Kanban",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "status": {"type": "string",
                                   "description": "running, queued, todo, done, blocked, failed"},
                        "assignee": {"type": "string"},
                        "ts": {"type": "integer", "description": "epoch di riferimento"},
                    },
                    "required": ["title"],
                },
            },
        },
        "required": ["action"],
    },
}

AGENTS_BOARD_SCHEMA: dict[str, Any] = {
    "name": "agents_board",
    "description": (
        "Widget con l'elenco degli agenti configurati: nome, stato (al lavoro, in coda, "
        "libero), task attuale e comando di attivazione. Con action=activate mette in coda "
        "un task per quell'agente, che il dispatcher Kanban avvierà."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["send", "refresh", "activate", "show"],
                       "description": "send/refresh il widget; activate mette in coda un task; "
                                      "show restituisce l'elenco in testo"},
            "chat_id": {"type": "integer", "description": "Chat di destinazione"},
            "message_id": {"type": "integer", "description": "Obbligatorio con action=refresh"},
            "agent": {"type": "string", "description": "Nome dell'agente da attivare"},
            "task": {"type": "string", "description": "Istruzione da assegnare all'agente"},
            "limit": {"type": "integer", "description": "Quanti agenti mostrare (default 8)"},
            "caption": {"type": "string", "description": "Didascalia opzionale"},
        },
        "required": ["action"],
    },
}


def handle_widget_board(action: str = "send", chat_id: int | None = None,
                        message_id: int | None = None, limit: int = 6,
                        caption: str | None = None,
                        tasks: list[dict] | None = None, **_: Any) -> str:
    limit = max(1, min(int(limit or 6), 6))
    target = chat_id or board.default_chat()
    if not target:
        return json.dumps({"ok": False, "error": "chat_id assente e TELEGRAM_HOME_CHANNEL non impostata"})

    try:
        if action == "refresh":
            if not message_id:
                return json.dumps({"ok": False, "error": "message_id richiesto per refresh"})
            return json.dumps(board.refresh_board(int(target), int(message_id), tasks, limit),
                              ensure_ascii=False)
        return json.dumps(board.send_board(int(target), tasks, limit, caption), ensure_ascii=False)
    except Exception as error:  # il tool non deve mai far cadere il turno
        logger.warning("widget_board failed: %s", error)
        return json.dumps({"ok": False, "error": str(error)[:300]}, ensure_ascii=False)


def handle_agents_board(action: str = "send", chat_id: int | None = None,
                        message_id: int | None = None, agent: str | None = None,
                        task: str | None = None, limit: int = 8,
                        caption: str | None = None, **_: Any) -> str:
    limit = max(1, min(int(limit or 8), 8))
    try:
        if action == "show":
            return json.dumps({"ok": True, "agents": agents.load_agents()}, ensure_ascii=False)
        if action == "activate":
            if not agent or not task:
                return json.dumps({"ok": False, "error": "servono agent e task"})
            return json.dumps(agents.activate(agent, task), ensure_ascii=False)

        target = chat_id or board.default_chat()
        if not target:
            return json.dumps({"ok": False, "error": "chat_id assente"})
        if action == "refresh":
            if not message_id:
                return json.dumps({"ok": False, "error": "message_id richiesto per refresh"})
            return json.dumps(agents.refresh_agents(int(target), int(message_id), limit),
                              ensure_ascii=False)
        return json.dumps(agents.send_agents(int(target), limit, caption), ensure_ascii=False)
    except Exception as error:
        logger.warning("agents_board failed: %s", error)
        return json.dumps({"ok": False, "error": str(error)[:300]}, ensure_ascii=False)


WEATHER_BOARD_SCHEMA: dict[str, Any] = {
    "name": "weather_board",
    "description": (
        "Invia in chat un widget con il meteo attuale e le previsioni dei prossimi giorni "
        "(Open-Meteo, nessuna chiave). action=send crea il messaggio e restituisce message_id; "
        "action=refresh aggiorna quel messaggio; action=show restituisce i dati in JSON."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["send", "refresh", "show"]},
            "chat_id": {"type": "integer", "description": "Chat di destinazione"},
            "message_id": {"type": "integer", "description": "Obbligatorio con action=refresh"},
            "caption": {"type": "string", "description": "Didascalia opzionale"},
            "force": {"type": "boolean",
                      "description": "Ignora la cache (15 minuti) e richiede subito i dati"},
        },
        "required": ["action"],
    },
}


def handle_weather_board(action: str = "send", chat_id: int | None = None,
                         message_id: int | None = None, caption: str | None = None,
                         force: bool = False, **_: Any) -> str:
    try:
        if action == "show":
            return json.dumps({"ok": True, "weather": json.loads(weather.weather_state(force))},
                              ensure_ascii=False)
        target = chat_id or board.default_chat()
        if not target:
            return json.dumps({"ok": False, "error": "chat_id assente"})
        if action == "refresh":
            if not message_id:
                return json.dumps({"ok": False, "error": "message_id richiesto per refresh"})
            return json.dumps(weather.refresh_weather(int(target), int(message_id)),
                              ensure_ascii=False)
        return json.dumps(weather.send_weather(int(target), caption), ensure_ascii=False)
    except Exception as error:
        logger.warning("weather_board failed: %s", error)
        return json.dumps({"ok": False, "error": str(error)[:300]}, ensure_ascii=False)


# ---------------------------------------------------------------- CLI

def _register_cli(subparser: argparse.ArgumentParser) -> None:
    """Costruisce ``hermes widget-board <sotto-comando>``."""
    subs = subparser.add_subparsers(dest="widget_command")
    show = subs.add_parser("show", help="Stampa il Kanban nel terminale")
    show.add_argument("--limit", type=int, default=20)
    show.add_argument("--agent", help="Filtra per agente")

    send = subs.add_parser("send", help="Invia la board dei task in chat")
    send.add_argument("--chat", type=int)
    send.add_argument("--limit", type=int, default=6)
    send.add_argument("--caption")

    agents_cmd = subs.add_parser("agents", help="Invia la board degli agenti in chat")
    agents_cmd.add_argument("--chat", type=int)
    agents_cmd.add_argument("--limit", type=int, default=8)
    agents_cmd.add_argument("--caption")

    weather_cmd = subs.add_parser("weather", help="Invia il meteo e le previsioni in chat")
    weather_cmd.add_argument("--chat", type=int)
    weather_cmd.add_argument("--caption")
    weather_cmd.add_argument("--force", action="store_true", help="Ignora la cache")

    refresh = subs.add_parser("refresh", help="Aggiorna un widget già inviato")
    refresh.add_argument("--chat", type=int)
    refresh.add_argument("--message", type=int, required=True)

    drop = subs.add_parser("drop", help="Elimina un widget e smette di seguirlo")
    drop.add_argument("--chat", type=int)
    drop.add_argument("--message", type=int, required=True)


def _cli(args: argparse.Namespace) -> int:
    command = getattr(args, "widget_command", None)
    if command == "show":
        rows = board.load_tasks(max(1, int(args.limit or 20)))
        if args.agent:
            rows = [r for r in rows if str(r.get("assignee")) == args.agent]
        if not rows:
            print("nessun task")
            return 0
        for task in rows:
            print(f"{task['status']:<8} {task['id']:<12} "
                  f"{str(task.get('assignee') or '-'):<12} {task['title']}")
        return 0

    chat = args.chat or board.default_chat()
    if not chat:
        print("chat assente: passa --chat o imposta TELEGRAM_HOME_CHANNEL")
        return 2

    if command == "send":
        result = board.send_board(chat, None, max(1, min(args.limit, 6)), args.caption)
    elif command == "agents":
        result = agents.send_agents(chat, max(1, min(args.limit, 8)), args.caption)
    elif command == "weather":
        if getattr(args, "force", False):
            weather.fetch(force=True)
        result = weather.send_weather(chat, args.caption)
    elif command == "refresh":
        result = board.refresh_board(chat, args.message, None, 6)
    elif command == "drop":
        answer = board.api("deleteMessage", {"chat_id": chat, "message_id": args.message})
        board.unregister_board(args.message)
        result = {"ok": bool(answer.get("ok")), "deleted": args.message,
                  "error": answer.get("description")}
    else:
        print("sotto-comando sconosciuto")
        return 2

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def register(ctx) -> None:
    ctx.register_tool(name="widget_board", toolset="telegram_widgets",
                      schema=WIDGET_BOARD_SCHEMA, handler=handle_widget_board, emoji="🗂")
    ctx.register_tool(name="agents_board", toolset="telegram_widgets",
                      schema=AGENTS_BOARD_SCHEMA, handler=handle_agents_board, emoji="🤖")
    ctx.register_tool(name="weather_board", toolset="telegram_widgets",
                      schema=WEATHER_BOARD_SCHEMA, handler=handle_weather_board, emoji="🌦")
    ctx.register_cli_command(
        name="widget-board", help="Board Telegram dei task e degli agenti",
        setup_fn=_register_cli, handler_fn=_cli,
        description="Invia e aggiorna widget HTML con i task del Kanban e lo stato degli agenti.")
