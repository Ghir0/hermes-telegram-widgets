"""Telegram HTML widgets: a task board that lives in the chat.

Bot API 10.4 introduced ``sendWidget``: a sandboxed HTML document that runs inside the
message bubble, with state the bot can rewrite later. A widget is *fixed code plus
changeable state*: the HTML never changes after sending, only ``chat_data`` /
``public_data`` change, and each change is silent (no "edited" mark, no notification).

That is what makes it useful for agent and cron work: one message that keeps showing the
current board, instead of a stream of near-identical messages.

Verified limits (https://core.telegram.org/bots/widgets):
  * 32768 bytes of HTML, and 4096 bytes after zlib level 9 — the second one is the real cap
  * 1024 bytes of state per message (``chat_data``), UTF-8 bytes, JSON not required
  * JS runs in QuickJS: no fetch, no XHR, no external assets, no navigation
  * widgets can only be sent to private chats in production
  * sent widgets are automatically "protected content": clients refuse screenshots/forwards

Configuration (environment, all optional except the token):
  TELEGRAM_BOT_TOKEN    bot token from @BotFather
  TELEGRAM_HOME_CHANNEL default chat id
  HERMES_KANBAN_DB      path to kanban.db (default ~/.hermes/kanban.db)
  HERMES_WIDGET_STATE   directory for the board registry
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

API = "https://api.telegram.org/bot{token}/{method}"


def _env(name: str, default: str | None = None) -> str | None:
    """Environment first, then ~/.hermes/.env — the file is never required."""
    value = os.environ.get(name)
    if value:
        return value
    env_file = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                if raw:
                    return raw
    return default


def _token() -> str:
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    return token


def default_chat() -> int | None:
    value = _env("TELEGRAM_HOME_CHANNEL")
    return int(value) if value and value.lstrip("-").isdigit() else None


def kanban_db() -> Path:
    return Path(_env("HERMES_KANBAN_DB") or (Path.home() / ".hermes" / "kanban.db"))


def state_dir() -> Path:
    path = Path(_env("HERMES_WIDGET_STATE")
                or (Path.home() / ".hermes" / "state" / "telegram-widgets"))
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------- bot api

def api(method: str, payload: dict, timeout: int = 30) -> dict:
    request = urllib.request.Request(
        API.format(token=_token(), method=method),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"ok": False, "description": body.decode(errors="replace")[:300]}


# ---------------------------------------------------------------- dati

STATUSES = {"running": 0, "queued": 1, "todo": 1, "blocked": 2, "done": 3, "failed": 2}


def load_tasks(limit: int = 6) -> list[dict]:
    """Running and queued first, then blocked, then the most recent closed ones."""
    db = kanban_db()
    if not db.exists():
        return []
    try:
        columns = {row[1] for row in sqlite3.connect(db).execute("PRAGMA table_info(tasks)")}
        stamp = "updated_at" if "updated_at" in columns else "created_at"
        order = ("CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 WHEN 'todo' THEN 1 "
                 "WHEN 'blocked' THEN 2 ELSE 3 END, " + stamp + " DESC")
        sql = f"SELECT id, title, status, assignee, {stamp} AS ts FROM tasks ORDER BY {order} LIMIT ?"
        with sqlite3.connect(db) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, (limit,)).fetchall()]
    except sqlite3.Error:
        return []


def compact_state(tasks: list[dict], limit: int = 6) -> str:
    """Smallest state that fits 1024 bytes: status code, title, agent, age in minutes."""
    now = time.time()
    rows = []
    for task in tasks[:limit]:
        # absolute minute, not age: an age would change every minute and make an
        # unchanged board look "changed", burning one message per minute.
        stamp = int(int(task.get("ts") or now) // 60)
        rows.append([
            STATUSES.get(str(task.get("status", "")).lower(), 1),
            str(task.get("title", ""))[:44],
            str(task.get("assignee") or "")[:12],
            stamp,
        ])
    return json.dumps({"u": int(now), "c": rows}, ensure_ascii=False, separators=(",", ":"))


def board_state(limit: int = 6, tasks: list[dict] | None = None) -> str:
    """State without the timestamp: this is what "did anything change?" compares."""
    source = tasks if tasks is not None else load_tasks(limit)
    payload = json.loads(compact_state(source, limit))
    payload.pop("u", None)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------- registro

def _registry_path() -> Path:
    return state_dir() / "boards.json"


@contextlib.contextmanager
def _registry_lock():
    """Read-modify-write del registro: watcher e CLI scrivono lo stesso file."""
    lock_path = state_dir() / "boards.json.lock"
    handle = open(lock_path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def get_boards() -> list[dict]:
    path = _registry_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return []


def save_boards(boards: list[dict]) -> None:
    _registry_path().write_text(json.dumps(boards, ensure_ascii=False, indent=1))


def register_board(chat_id: int, message_id: int, limit: int = 6,
                   fingerprint: str | None = None, kind: str = "tasks") -> None:
    with _registry_lock():
        boards = [b for b in get_boards() if b.get("message_id") != message_id]
        boards.append({
            "chat_id": chat_id, "message_id": message_id, "limit": limit, "kind": kind,
            "fingerprint": fingerprint if fingerprint is not None else board_state(limit),
            "updated_at": int(time.time()),
        })
        save_boards(boards)


def unregister_board(message_id: int) -> None:
    with _registry_lock():
        save_boards([b for b in get_boards() if b.get("message_id") != message_id])


def update_fingerprints(updates: dict[int, str]) -> None:
    """Aggiorna solo le voci ancora presenti, senza ripristinare quelle cancellate altrove."""
    if not updates:
        return
    with _registry_lock():
        boards = get_boards()
        changed = False
        for entry in boards:
            message_id = int(entry.get("message_id", 0))
            if message_id in updates:
                entry["fingerprint"] = updates[message_id]
                entry["updated_at"] = int(time.time())
                changed = True
        if changed:
            save_boards(boards)


# ---------------------------------------------------------------- widget

WIDGET_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}
body{margin:0;padding:12px 14px;font:13px/1.35 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif;
background:var(--tg-theme-bg-color,#fff);color:var(--tg-theme-text-color,#000);
-webkit-font-smoothing:antialiased}
.top{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:10px}
.lab{font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--tg-theme-hint-color,#707579)}
.when{font-size:10px;color:var(--tg-theme-hint-color,#707579)}
.row{display:flex;align-items:center;gap:8px;padding:7px 0;border-top:1px solid rgba(127,127,127,.16)}
.dot{width:7px;height:7px;border-radius:50%;flex:0 0 7px;background:#9aa0a6}
.s0{background:#2eb872}.s1{background:#3d8bfd}.s2{background:#e0574f}.s3{background:#9aa0a6}
.t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.t.done{color:var(--tg-theme-hint-color,#707579);text-decoration:line-through}
.who{font-size:10px;padding:1px 6px;border-radius:9px;background:rgba(127,127,127,.14);
color:var(--tg-theme-hint-color,#707579);flex:0 0 auto;max-width:88px;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.age{font-size:10px;color:var(--tg-theme-hint-color,#707579);flex:0 0 auto;font-variant-numeric:tabular-nums}
.empty{padding:16px 0;text-align:center;font-size:12px;color:var(--tg-theme-hint-color,#707579)}
</style></head><body>
<div class="top"><span class="lab" id="lab">Task</span><span class="when" id="when"></span></div>
<div id="list"><div class="empty">nessun task</div></div>
<script>
function ago(m){if(m<1)return"ora";if(m<60)return m+"m";var h=Math.floor(m/60);
if(h<24)return h+"h";return Math.floor(h/24)+"g"}
function draw(){
 var raw=TelegramWidget.chatData,data=null;
 try{data=raw?JSON.parse(raw):null}catch(e){data=null}
 var box=document.getElementById("list");
 if(!data||!data.c||!data.c.length){box.innerHTML='<div class="empty">nessun task</div>';return}
 var out="",n=0;
 for(var i=0;i<data.c.length;i++){
  var r=data.c[i],st=r[0]||0;
  var mins=Math.floor(Date.now()/60000)-(r[3]||0);
  if(st!==3)n++;
  out+='<div class="row"><span class="dot s'+st+'"></span>'+
   '<span class="t'+(st===3?" done":"")+'">'+esc(r[1])+'</span>'+
   (r[2]?'<span class="who">'+esc(r[2])+'</span>':'')+
   '<span class="age">'+ago(mins)+'</span></div>';
 }
 box.innerHTML=out;
 document.getElementById("lab").textContent=(data.c.length-n)+" chiusi · "+n+" attivi";
 if(data.u){var d=new Date(data.u*1000);document.getElementById("when").textContent=
  ("0"+d.getHours()).slice(-2)+":"+("0"+d.getMinutes()).slice(-2)}
}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){
 return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
draw();
TelegramWidget.onEvent("chatDataChanged",draw);
</script></body></html>"""


def size_report(html: str = WIDGET_HTML) -> dict:
    raw = len(html.encode())
    packed = len(zlib.compress(html.encode(), 9))
    return {"html_bytes": raw, "zlib_bytes": packed, "ok": raw <= 32768 and packed <= 4096}


def send_board(chat_id: int, tasks: list[dict] | None = None, limit: int = 6,
               caption: str | None = None, track: bool = True) -> dict:
    check = size_report()
    if not check["ok"]:
        raise RuntimeError(f"widget too large: {check}")
    state = compact_state(tasks if tasks is not None else load_tasks(limit), limit)
    if len(state.encode()) > 1024:
        state = json.dumps({"u": int(time.time()), "c": []})
    payload = {"chat_id": chat_id, "html": WIDGET_HTML, "width": 0, "height": 0,
               "chat_data": state, "allow_queries": False}
    if caption:
        payload["caption"] = caption[:1024]
    answer = api("sendWidget", payload)
    if not answer.get("ok"):
        return {"ok": False, "error": answer.get("description"), "sizes": check}
    message = answer["result"]
    if track:
        register_board(chat_id, message.get("message_id"), limit)
    return {"ok": True, "message_id": message.get("message_id"), "chat_id": chat_id,
            "state_bytes": len(state.encode()), "sizes": check}


def refresh_board(chat_id: int, message_id: int, tasks: list[dict] | None = None,
                  limit: int = 6) -> dict:
    state = compact_state(tasks if tasks is not None else load_tasks(limit), limit)
    answer = api("editMessageWidgetData",
                 {"chat_id": chat_id, "message_id": message_id, "chat_data": state})
    if not answer.get("ok"):
        description = str(answer.get("description", ""))
        if "not modified" in description:
            return {"ok": True, "unchanged": True, "message_id": message_id}
        if "not found" in description.lower():
            unregister_board(message_id)
            return {"ok": False, "error": description, "dropped": True}
        return {"ok": False, "error": description}
    return {"ok": True, "message_id": message_id, "state_bytes": len(state.encode())}
