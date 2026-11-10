"""Agent board: who is on duty, what they are doing, and how to put one to work.

Status is derived from the Kanban, not from a heartbeat: an agent is *busy* when it has a
task in `running`, *queued* when it has one waiting, *idle* otherwise. A profile with no
tasks at all still shows up — an empty agent is information too.

Activation writes a `queued` task assigned to that agent: the Kanban dispatcher is what
actually starts the worker, so this stays within the existing contract instead of inventing
a second way to spawn agents.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import zlib
from pathlib import Path

try:  # caricato come package dal plugin
    from . import board
except ImportError:  # eseguito come script (watcher.py, cli.py)
    import board  # type: ignore[no-redef]

AGENTS_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}
body{margin:0;padding:12px 14px;font:13px/1.35 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif;
background:var(--tg-theme-bg-color,#fff);color:var(--tg-theme-text-color,#000)}
.top{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:10px}
.lab{font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--tg-theme-hint-color,#707579)}
.when{font-size:10px;color:var(--tg-theme-hint-color,#707579)}
.row{display:flex;align-items:center;gap:8px;padding:7px 0;border-top:1px solid rgba(127,127,127,.16)}
.dot{width:7px;height:7px;border-radius:50%;flex:0 0 7px;background:#9aa0a6}
.s0{background:#2eb872}.s1{background:#3d8bfd}.s2{background:#9aa0a6}.s3{background:#e0574f}
.n{font-weight:600;flex:0 0 auto;min-width:74px;max-width:96px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.what{flex:1;min-width:0;font-size:11.5px;color:var(--tg-theme-hint-color,#707579);
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cmd{font:10px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--tg-theme-link-color,#3390ec);
flex:0 0 auto;max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.foot{margin-top:9px;padding-top:8px;border-top:1px solid rgba(127,127,127,.16);
font-size:10px;color:var(--tg-theme-hint-color,#707579)}
</style></head><body>
<div class="top"><span class="lab" id="lab">Agenti</span><span class="when" id="when"></span></div>
<div id="list"></div>
<div class="foot" id="foot">attiva: «attiva &lt;agente&gt; con &lt;istruzione&gt;» · chiudi: «chiudi gli agenti»</div>
<script>
function esc(s){return String(s).replace(/[&<>"]/g,function(c){
 return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function draw(){
 var raw=TelegramWidget.chatData,data=null;
 try{data=raw?JSON.parse(raw):null}catch(e){data=null}
 var box=document.getElementById("list");
 if(!data||!data.a||!data.a.length){box.innerHTML='<div class="foot">nessun agente configurato</div>';return}
 var out="",busy=0;
 for(var i=0;i<data.a.length;i++){
  var r=data.a[i],st=r[0]||0;
  if(st===0)busy++;
  out+='<div class="row"><span class="dot s'+st+'"></span>'+
   '<span class="n">'+esc(r[1])+'</span>'+
   '<span class="what">'+esc(r[2]||'—')+'</span>'+
   (r[3]?'<span class="cmd">'+esc(r[3])+'</span>':'')+'</div>';
 }
 box.innerHTML=out;
 document.getElementById("lab").textContent=busy+" al lavoro · "+data.a.length+" agenti";
 if(data.u){var d=new Date(data.u*60000);document.getElementById("when").textContent=
  ("0"+d.getHours()).slice(-2)+":"+("0"+d.getMinutes()).slice(-2)}
}
draw();
TelegramWidget.onEvent("chatDataChanged",draw);
</script></body></html>"""

STATUS_NAME = {0: "busy", 1: "queued", 2: "idle", 3: "error"}


def profiles_dir() -> Path:
    return Path(board._env("HERMES_HOME") or (Path.home() / ".hermes")) / "profiles"


def load_agents() -> list[dict]:
    """Ogni profilo più il profilo principale; stato dedotto dai task in Kanban."""
    names: list[str] = []
    directory = profiles_dir()
    if directory.exists():
        names = sorted(p.name for p in directory.iterdir() if p.is_dir())
    if "default" not in names:
        names.insert(0, "default")

    running: dict[str, list[dict]] = {}
    db = board.kanban_db()
    if db.exists():
        try:
            with sqlite3.connect(db) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    "SELECT title, assignee, status FROM tasks WHERE status IN ('running','queued','blocked') "
                    "ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END, created_at DESC"
                ).fetchall()
            for row in rows:
                running.setdefault(str(row["assignee"] or ""), []).append(dict(row))
        except sqlite3.Error:
            pass

    agents = []
    for name in names:
        tasks = running.get(name, [])
        live = [t for t in tasks if t["status"] == "running"]
        waiting = [t for t in tasks if t["status"] in {"queued", "blocked"}]
        if live:
            code, current = 0, str(live[0]["title"])[:38]
        elif waiting:
            code, current = 1, "in coda: " + str(waiting[0]["title"])[:30]
        else:
            code, current = 2, "libero"
        agents.append({"name": name, "status": code, "task": current,
                       "command": "attiva " + name})
    return agents


def agents_state(agents: list[dict] | None = None, limit: int = 8) -> str:
    items = (agents if agents is not None else load_agents())[:limit]
    rows = [[a["status"], a["name"][:14], a["task"][:38], a["command"][:18]] for a in items]
    return json.dumps({"u": int(time.time() // 60), "a": rows}, ensure_ascii=False,
                      separators=(",", ":"))


def agents_fingerprint(limit: int = 8) -> str:
    payload = json.loads(agents_state(None, limit))
    payload.pop("u", None)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def size_report_agents() -> dict:
    raw = len(AGENTS_HTML.encode())
    packed = len(zlib.compress(AGENTS_HTML.encode(), 9))
    return {"html_bytes": raw, "zlib_bytes": packed, "ok": raw <= 32768 and packed <= 4096}


def send_agents(chat_id: int, limit: int = 8, caption: str | None = None,
                track: bool = True) -> dict:
    check = size_report_agents()
    if not check["ok"]:
        raise RuntimeError(f"widget too large: {check}")
    state = agents_state(None, limit)
    if len(state.encode()) > 1024:
        state = json.dumps({"u": int(time.time() // 60), "a": []})
    payload = {"chat_id": chat_id, "html": AGENTS_HTML, "width": 0, "height": 0,
               "chat_data": state, "allow_queries": False}
    if caption:
        payload["caption"] = caption[:1024]
    answer = board.api("sendWidget", payload)
    if not answer.get("ok"):
        return {"ok": False, "error": answer.get("description"), "sizes": check}
    message = answer["result"]
    if track:
        board.register_board(chat_id, message["message_id"], limit,
                             fingerprint=agents_fingerprint(limit), kind="agents")
    return {"ok": True, "message_id": message["message_id"], "chat_id": chat_id,
            "state_bytes": len(state.encode()), "sizes": check}


def refresh_agents(chat_id: int, message_id: int, limit: int = 8) -> dict:
    state = agents_state(None, limit)
    answer = board.api("editMessageWidgetData",
                       {"chat_id": chat_id, "message_id": message_id, "chat_data": state})
    if not answer.get("ok"):
        description = str(answer.get("description", ""))
        if "not modified" in description:
            return {"ok": True, "unchanged": True, "message_id": message_id}
        if "not found" in description.lower():
            board.unregister_board(message_id)
            return {"ok": False, "error": description, "dropped": True}
        return {"ok": False, "error": description}
    return {"ok": True, "message_id": message_id, "state_bytes": len(state.encode())}


def activate(agent: str, task: str, priority: int = 2) -> dict:
    """Mette in coda un task per quell'agente: è il dispatcher Kanban ad avviare il worker."""
    db = board.kanban_db()
    if not db.exists():
        return {"ok": False, "error": "kanban.db non trovato"}
    task_id = "t_" + os.urandom(4).hex()
    now = int(time.time())
    try:
        with sqlite3.connect(db) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
            values = {"id": task_id, "title": task[:160], "body": task[:2000],
                      "assignee": agent, "status": "queued", "priority": str(priority),
                      "created_by": "widget", "created_at": now}
            fields = [c for c in values if c in columns]
            connection.execute(
                f"INSERT INTO tasks ({','.join(fields)}) VALUES ({','.join('?' * len(fields))})",
                [values[c] for c in fields])
            connection.commit()
    except sqlite3.Error as error:
        return {"ok": False, "error": str(error)[:200]}
    return {"ok": True, "task_id": task_id, "agent": agent, "title": task[:160]}
