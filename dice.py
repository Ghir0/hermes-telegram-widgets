"""Dice widget: a d20 (and friends) that rolls in the chat.

The roll happens on the bot side with ``secrets.randbelow`` — a CSPRNG, not ``random``,
because a die that can be predicted is not a die. The widget only shows the result, and
replays a small animation every time the state changes.

A tap cannot roll: that needs ``widget_query``, which the gateway does not handle yet. So
the roll is triggered by asking, and the widget is resent (or refreshed) with the new value.
"""
from __future__ import annotations

import json
import secrets
import time
import zlib

try:  # package (plugin loader)
    from . import board
except ImportError:  # script
    import board  # type: ignore[no-redef]

DICE_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}
body{margin:0;padding:0;background:transparent;
font:13px/1.35 Georgia,"Times New Roman",serif;color:#f3e9d2}
.card{position:relative;overflow:hidden;border-radius:14px;padding:13px 15px 11px;
background:radial-gradient(120% 120% at 15% 0%,#3a2b1d 0%,#241a12 55%,#17100b 100%);
border:1px solid rgba(201,162,39,.35)}
.card:before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.35;
background:repeating-linear-gradient(45deg,rgba(255,255,255,.035) 0 2px,transparent 2px 7px)}
.card>*{position:relative}
.top{display:flex;align-items:baseline;justify-content:space-between}
.lab{font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:rgba(233,206,138,.92)}
.when{font-size:9.5px;color:rgba(233,206,138,.75);font-variant-numeric:tabular-nums}
.main{display:flex;align-items:center;gap:14px;margin-top:8px}
.die{width:96px;height:96px;flex:0 0 96px;filter:drop-shadow(0 6px 14px rgba(0,0,0,.55))}
.die svg{width:100%;height:100%;display:block}
.num{font-family:Georgia,serif;font-weight:700;fill:#f7ecd0}
.out{flex:1;min-width:0}
.res{font-size:40px;font-weight:700;line-height:1;letter-spacing:-.02em;
font-variant-numeric:tabular-nums;color:#f7ecd0;text-shadow:0 2px 14px rgba(0,0,0,.5)}
.res small{font-size:13px;font-weight:400;color:rgba(233,206,138,.6);letter-spacing:.04em}
.verdict{font-size:11px;letter-spacing:.14em;text-transform:uppercase;margin-top:5px;
color:rgba(233,206,138,.8)}
.crit{color:#ffdf8a;font-size:12px;display:inline-block;padding:2px 9px;margin-top:4px;border:1px solid rgba(255,207,92,.55);border-radius:4px;background:rgba(255,207,92,.1);text-shadow:0 0 14px rgba(255,207,92,.6)}
.fumble{color:#e8796b}
.rule{margin-top:10px;padding-top:8px;border-top:1px solid rgba(201,162,39,.38);
display:flex;justify-content:space-between;font-size:9.5px;color:rgba(233,206,138,.78)}
.pop{animation:pop .55s cubic-bezier(.2,1.4,.4,1)}
@keyframes pop{0%{transform:scale(.6) rotate(-7deg);opacity:.2}
60%{transform:scale(1.12) rotate(2deg)}100%{transform:scale(1) rotate(0);opacity:1}}
.glow{animation:glow 1.2s ease-out}
@keyframes glow{0%{filter:drop-shadow(0 0 0 rgba(255,207,92,0))}
40%{filter:drop-shadow(0 0 14px rgba(255,207,92,.75))}
100%{filter:drop-shadow(0 6px 14px rgba(0,0,0,.55))}}
</style></head><body>
<div class="card" id="card">
<div class="top"><span class="lab" id="lab">D20</span><span class="when" id="when"></span></div>
<div class="main">
  <div class="die" id="die"></div>
  <div class="out">
    <div class="res" id="res">—</div>
    <div class="verdict" id="verdict">&nbsp;</div>
  </div>
</div>
<div class="rule"><span>chiudi: «chiudi il dado»</span><span id="seed"></span></div>
</div>
<script>
function esc(s){return String(s).replace(/[&<>"]/g,function(c){
 return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function die(n){
 var p='<polygon points="50,4 90,27 90,73 50,96 10,73 10,27" fill="rgba(255,255,255,.04)" stroke="#c9a227" stroke-width="2.2" stroke-linejoin="round"/>'+
 '<polygon points="50,30 68,64 32,64" fill="rgba(201,162,39,.12)" stroke="#c9a227" stroke-width="1.5" stroke-linejoin="round"/>'+
 '<g stroke="rgba(201,162,39,.55)" stroke-width="1.2">'+
 '<path d="M50,4 L50,30M90,27 L68,64M90,73 L68,64M50,96 L50,64M10,73 L32,64M10,27 L32,64"/></g>';
 return '<svg viewBox="0 0 100 100">'+p+'</svg>';
}
function draw(){
 var raw=TelegramWidget.chatData,data=null;
 try{data=raw?JSON.parse(raw):null}catch(e){data=null}
 if(!data){return}
 var n=data.n||20, r=data.r;
 document.getElementById("lab").textContent="D"+n;
 document.getElementById("die").innerHTML=die(n);
 var res=document.getElementById("res");
 res.innerHTML=Math.round(r)+'<small> / '+n+'</small>';
 res.className="res"+(r===n?" crit":"");
 var v=document.getElementById("verdict");
 if(r===n){v.textContent="colpo critico";v.className="verdict crit"}
 else if(r===1){v.textContent="fallimento critico";v.className="verdict fumble"}
 else if(r>=n*0.75){v.textContent="colpo netto";v.className="verdict"}
 else{v.textContent="";v.className="verdict"}
 if(data.u){var d=new Date(data.u*60000);document.getElementById("when").textContent=
  ("0"+d.getHours()).slice(-2)+":"+("0"+d.getMinutes()).slice(-2)}
}
function replay(){
 var dieEl=document.getElementById("die"),resEl=document.getElementById("res");
 [dieEl,resEl].forEach(function(el){
  if(!el)return; el.classList.remove("pop","glow"); void el.offsetWidth;
  el.classList.add(el===dieEl?"glow":"pop");
 });
}
draw();replay();
TelegramWidget.onEvent("chatDataChanged",function(){draw();replay()});
</script></body></html>"""

SIDES = (4, 6, 8, 10, 12, 20, 100)


def roll(sides: int = 20) -> int:
    """CSPRNG: un dado prevedibile non è un dado."""
    sides = int(sides)
    if sides not in SIDES:
        raise ValueError(f"dado non supportato: d{sides}")
    return secrets.randbelow(sides) + 1


def dice_state(sides: int = 20, result: int | None = None) -> str:
    state = {
        "u": int(time.time() // 60),
        "n": int(sides),
        "r": int(result if result is not None else roll(sides)),
    }
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def size_report_dice() -> dict:
    raw = len(DICE_HTML.encode())
    packed = len(zlib.compress(DICE_HTML.encode(), 9))
    return {"html_bytes": raw, "zlib_bytes": packed, "ok": raw <= 32768 and packed <= 4096}


def send_dice(chat_id: int, sides: int = 20, caption: str | None = None,
              track: bool = True, ttl: int | None = 120) -> dict:
    check = size_report_dice()
    if not check["ok"]:
        raise RuntimeError(f"widget too large: {check}")
    result = roll(sides)
    state = dice_state(sides, result)
    payload = {"chat_id": chat_id, "html": DICE_HTML, "width": 0, "height": 0,
               "chat_data": state, "allow_queries": False}
    if caption:
        payload["caption"] = caption[:1024]
    answer = board.api("sendWidget", payload)
    if not answer.get("ok"):
        return {"ok": False, "error": answer.get("description"), "sizes": check}
    message = answer["result"]
    if track:
        board.register_board(chat_id, message["message_id"], 6, kind="dice",
                             fingerprint=f"{sides}:{result}", ttl=ttl)
    return {"ok": True, "message_id": message["message_id"], "chat_id": chat_id,
            "sides": sides, "result": result, "state_bytes": len(state.encode()),
            "sizes": check}


def refresh_dice(chat_id: int, message_id: int, sides: int = 20) -> dict:
    """Tira di nuovo e aggiorna il widget esistente (se non è ancora scaduto)."""
    result = roll(sides)
    state = dice_state(sides, result)
    answer = board.api("editMessageWidgetData",
                       {"chat_id": chat_id, "message_id": message_id, "chat_data": state})
    if not answer.get("ok"):
        description = str(answer.get("description", ""))
        if "not modified" in description:
            return {"ok": True, "unchanged": True, "message_id": message_id, "result": result}
        if "not found" in description.lower():
            board.unregister_board(message_id)
            return {"ok": False, "error": description, "dropped": True}
        return {"ok": False, "error": description}
    return {"ok": True, "message_id": message_id, "sides": sides, "result": result,
            "state_bytes": len(state.encode())}
