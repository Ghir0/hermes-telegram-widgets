#!/usr/bin/env python3
"""CLI minima per usare il widget board da cron o da terminale, senza gateway.

    python3 cli.py send    [--chat ID] [--limit 6] [--caption "..."]
    python3 cli.py refresh --message ID [--chat ID] [--limit 6]
    python3 cli.py size

Stampa JSON su stdout: `{"ok": true, "message_id": ...}`.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent


def _load_agents():
    import importlib
    pkg = sys.modules["telegram_widgets_cli"]
    return importlib.import_module(pkg.__name__ + ".agents")


def _load():
    name = "telegram_widgets_cli"
    spec = importlib.util.spec_from_file_location(name, PKG / "__init__.py",
                                                  submodule_search_locations=[str(PKG)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.board


def main() -> int:
    parser = argparse.ArgumentParser(description="Widget task board per Telegram")
    parser.add_argument("azione", choices=["send", "refresh", "size", "drop", "show",
                                           "agents", "activate"])
    parser.add_argument("--chat", type=int)
    parser.add_argument("--message", type=int)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--caption")
    parser.add_argument("--agent", help="agente da attivare (azione activate)")
    parser.add_argument("--task", help="istruzione per l'agente (azione activate)")
    args = parser.parse_args()

    board = _load()
    agents = _load_agents()

    if args.azione == "size":
        print(json.dumps(board.size_report(), ensure_ascii=False))
        return 0

    chat = args.chat or board.default_chat()
    if not chat:
        print(json.dumps({"ok": False, "error": "chat assente"}))
        return 2

    if args.azione == "show":
        rows = board.load_tasks(max(1, args.limit))
        if not rows:
            print("nessun task")
            return 0
        for task in rows:
            print(f"{task['status']:<8} {task['id']:<12} {str(task['assignee'] or '-'):<12} {task['title']}")
        return 0

    if args.azione == "agents":
        result = agents.send_agents(chat, max(1, min(args.limit, 8)), args.caption)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    if args.azione == "activate":
        if not args.agent or not args.task:
            print(json.dumps({"ok": False, "error": "--agent e --task richiesti"}))
            return 2
        print(json.dumps(agents.activate(args.agent, args.task), ensure_ascii=False))
        return 0

    if args.azione == "drop":
        if not args.message:
            print(json.dumps({"ok": False, "error": "--message richiesto"}))
            return 2
        answer = board.api("deleteMessage", {"chat_id": chat, "message_id": args.message})
        board.unregister_board(args.message)
        print(json.dumps({"ok": bool(answer.get("ok")), "deleted": args.message,
                          "error": answer.get("description")}, ensure_ascii=False))
        return 0 if answer.get("ok") else 1

    if args.azione == "send":
        result = board.send_board(chat, None, max(1, min(args.limit, 6)), args.caption)
    else:
        if not args.message:
            print(json.dumps({"ok": False, "error": "--message richiesto"}))
            return 2
        result = board.refresh_board(chat, args.message, None, max(1, min(args.limit, 6)))

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
