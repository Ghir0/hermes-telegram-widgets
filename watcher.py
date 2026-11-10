#!/usr/bin/env python3
"""Watches the Kanban database and refreshes registered widgets when the board changes.

A widget edit is silent and counts as one sent message against the bot's rate limit, so
the loop is deliberately cheap: it stats the database file first and only computes a
fingerprint when the file moved. Identical state is never sent — Telegram would answer
"message is not modified", and refusing to send it at all keeps the rate limit untouched.

Run it as a systemd unit (see widget-watcher.service) or by hand:

    python3 watcher.py --interval 2
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import board  # noqa: E402


def log(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def tick(min_interval: float = 1.0) -> int:
    """One pass over the registry. Returns how many widgets were refreshed."""
    boards = board.get_boards()
    if not boards:
        return 0

    refreshed = 0
    now = time.time()
    for entry in boards:
        limit = int(entry.get("limit", 6))
        fingerprint = board.board_state(limit)
        if fingerprint == entry.get("fingerprint"):
            continue
        if now - float(entry.get("updated_at", 0)) < min_interval:
            continue  # rate-limit guard: one edit per widget per second at most

        result = board.refresh_board(int(entry["chat_id"]), int(entry["message_id"]), None, limit)
        if result.get("ok"):
            entry["fingerprint"] = fingerprint
            entry["updated_at"] = int(now)
            refreshed += 1
            log(f"refresh message={entry['message_id']} bytes={result.get('state_bytes')}")
        elif result.get("dropped"):
            board.save_boards(board.get_boards())  # refresh_board already unregistered it
            log(f"dropped message={entry['message_id']}: {result.get('error')}")
        else:
            log(f"error message={entry['message_id']}: {result.get('error')}")

    if refreshed:
        board.save_boards(boards)
    return refreshed


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Telegram widgets when the Kanban changes")
    parser.add_argument("--interval", type=float, default=2.0, help="polling seconds (default 2)")
    parser.add_argument("--once", action="store_true", help="single pass, for cron")
    parser.add_argument("--json", action="store_true", help="print one JSON line per tick")
    args = parser.parse_args()

    if args.once:
        count = tick()
        print(json.dumps({"refreshed": count}))
        return 0

    log(f"watcher avviato: {board.kanban_db()} ogni {args.interval}s")
    while True:
        try:
            # No mtime gate: SQLite in WAL mode writes to kanban.db-wal, so the main file's
            # mtime often does not move. Reading a few rows every tick is cheaper than a
            # missed update, and the fingerprint comparison still skips the API call.
            tick()
        except Exception as error:  # the watcher must not die on a transient sqlite lock
            log(f"errore: {type(error).__name__}: {error}")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
