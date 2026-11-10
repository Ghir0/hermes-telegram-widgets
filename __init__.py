"""telegram-widgets — HTML widgets in chat (Bot API 10.4).

One tool, `widget_board`: send a live board of agent/cron tasks as an HTML widget, then
refresh it in place. The widget reads its rows from ``chat_data``; a refresh rewrites that
state and Telegram repaints the bubble without an "edited" mark and without moving the chat.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from . import board

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


def register(ctx) -> None:
    ctx.register_tool(name="widget_board", toolset="telegram_widgets",
                      schema=WIDGET_BOARD_SCHEMA, handler=handle_widget_board, emoji="🗂")
