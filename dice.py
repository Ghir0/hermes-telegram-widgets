"""Dice widget: a d20 (and friends) that rolls when you tap it.

Two kinds of roll, on purpose:

* the first value comes from the bot, ``secrets.randbelow`` — a CSPRNG;
* every tap rolls **inside the widget**, because a tap that needs the bot would need
  ``widget_query``, which the gateway does not handle. The local roll uses
  ``crypto.getRandomValues`` when the sandbox exposes it and falls back to ``Math.random``.

So the widget is interactive without a round trip, and the message the bot sends is still
unpredictable.
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
border:1px solid rgba(201,162,39,.35);cursor:pointer;-webkit-user-select:none;user-select:none}
.card:before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.35;
background:repeating-linear-gradient(45deg,rgba(255,255,255,.035) 0 2px,transparent 2px 7px)}
.card>*{position:relative}
.top{display:flex;align-items:baseline;justify-content:space-between}
.lab{font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:rgba(233,206,138,.92)}
.when{font-size:9.5px;color:rgba(233,206,138,.75);font-variant-numeric:tabular-nums}
.main{display:flex;align-items:center;gap:14px;margin-top:8px}
.die{width:96px;height:96px;flex:0 0 96px;filter:drop-shadow(0 6px 14px rgba(0,0,0,.55));
transform-origin:50% 50%}
.die svg{width:100%;height:100%;display:block}
.out{flex:1;min-width:0}
.res{font-size:40px;font-weight:700;line-height:1;letter-spacing:-.02em;
font-variant-numeric:tabular-nums;color:#f7ecd0;text-shadow:0 2px 14px rgba(0,0,0,.5)}
.res small{font-size:13px;font-weight:400;color:rgba(233,206,138,.6);letter-spacing:.04em}
.verdict{font-size:11px;letter-spacing:.14em;text-transform:uppercase;margin-top:5px;
color:rgba(233,206,138,.8)}
.crit{color:#ffdf8a;font-size:12px;display:inline-block;padding:2px 9px;margin-top:4px;
border:1px solid rgba(255,207,92,.55);border-radius:4px;background:rgba(255,207,92,.1);
text-shadow:0 0 14px rgba(255,207,92,.6)}
.fumble{color:#e8796b}
.faces{display:flex;gap:4px;margin-top:10px;flex-wrap:wrap}
.face{font-size:9.5px;padding:3px 8px;border-radius:6px;border:1px solid rgba(201,162,39,.3);
color:rgba(233,206,138,.75);font-variant-numeric:tabular-nums}
.face.on{background:rgba(201,162,39,.22);border-color:rgba(201,162,39,.75);color:#ffe9b0}
.rule{margin-top:9px;padding-top:8px;border-top:1px solid rgba(201,162,39,.38);
display:flex;justify-content:space-between;font-size:9.5px;color:rgba(233,206,138,.78)}
.rolling{animation:tumble .85s cubic-bezier(.3,.1,.3,1)}
@keyframes tumble{0%{transform:rotate(0) scale(1)}
20%{transform:rotate(-16deg) scale(1.07)}
45%{transform:rotate(13deg) scale(.94)}
70%{transform:rotate(-6deg) scale(1.04)}
100%{transform:rotate(0) scale(1)}}
.rolling .res{animation:flicker .85s steps(1)}
@keyframes flicker{0%{opacity:.3;filter:blur(2.5px)}
55%{opacity:.45;filter:blur(1.5px)}
80%{opacity:.75;filter:blur(.6px)}
100%{opacity:1;filter:none}}
.landed{animation:land .4s ease-out}
@keyframes land{0%{transform:scale(1.14)}100%{transform:scale(1)}}
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
<div class="faces" id="faces"></div>
<div class="rule"><span id="hint">tocca per tirare</span><span>chiudi: «chiudi il dado»</span></div>
</div>
<script>
var SIDES=[4,6,8,10,12,20,100],state={n:20,r:null},busy=false;
function esc(s){return String(s).replace(/[&<>"]/g,function(c){
 return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function localRoll(n){
 try{
  if(typeof crypto!=="undefined"&&crypto.getRandomValues){
   var a=new Uint32Array(1),lim=Math.floor(4294967296/n)*n;
   for(var i=0;i<8;i++){crypto.getRandomValues(a);if(a[0]<lim)return (a[0]%n)+1}
  }
 }catch(e){}
 return Math.floor(Math.random()*n)+1;
}
function dieSvg(){
 var p='<polygon points="50,4 90,27 90,73 50,96 10,73 10,27" fill="rgba(255,255,255,.04)" stroke="#c9a227" stroke-width="2.2" stroke-linejoin="round"/>'+
 '<polygon points="50,30 68,64 32,64" fill="rgba(201,162,39,.12)" stroke="#c9a227" stroke-width="1.5" stroke-linejoin="round"/>'+
 '<g stroke="rgba(201,162,39,.55)" stroke-width="1.2">'+
 '<path d="M50,4 L50,30M90,27 L68,64M90,73 L68,64M50,96 L50,64M10,73 L32,64M10,27 L32,64"/></g>';
 return '<svg viewBox="0 0 100 100">'+p+'</svg>';
}
function faces(){
 var out="";
 for(var i=0;i<SIDES.length;i++)
  out+='<span class="face'+(SIDES[i]===state.n?" on":"")+'" data-n="'+SIDES[i]+'">d'+SIDES[i]+'</span>';
 document.getElementById("faces").innerHTML=out;
}
function paint(){
 var n=state.n,r=state.r;
 document.getElementById("lab").textContent="D"+n;
 document.getElementById("die").innerHTML=dieSvg();
 var res=document.getElementById("res");
 res.innerHTML=Math.round(r)+'<small> / '+n+'</small>';
 var v=document.getElementById("verdict");
 if(r===n){v.textContent="colpo critico";v.className="verdict crit"}
 else if(r===1){v.textContent="fallimento critico";v.className="verdict fumble"}
 else if(r>=n*0.75){v.textContent="colpo netto";v.className="verdict"}
 else{v.textContent="";v.className="verdict"}
 document.getElementById("when").textContent="";
}
function start(){
 var raw=TelegramWidget.chatData,data=null;
 try{data=raw?JSON.parse(raw):null}catch(e){data=null}
 var n=(data&&data.n)||20,r=(data&&data.r);
 if(SIDES.indexOf(n)<0)n=20;
 if(!isFinite(Number(r))||Number(r)<1||Number(r)>n)r=localRoll(n);
 state={n:n,r:Number(r)};
 if(data&&data.u){var d=new Date(data.u*60000);
  document.getElementById("when").textContent=("0"+d.getHours()).slice(-2)+":"+("0"+d.getMinutes()).slice(-2)}
 faces();paint();
}
function roll(){
 if(busy)return;
 busy=true;
 var dieEl=document.getElementById("die"),card=document.getElementById("card");
 dieEl.classList.remove("rolling");void dieEl.offsetWidth;dieEl.classList.add("rolling");
 card.classList.add("rolling");
 var done=function(){
  busy=false;dieEl.classList.remove("rolling");card.classList.remove("rolling");
  document.getElementById("res").classList.remove("landed");void dieEl.offsetWidth;
  document.getElementById("res").classList.add("landed");
 };
 var finish=function(){state.r=localRoll(state.n);paint();done()};
 try{setTimeout(finish,850)}catch(e){finish()}
}
document.getElementById("card").addEventListener("click",function(ev){
 var f=ev.target&&ev.target.getAttribute&&ev.target.getAttribute("data-n");
 if(f){state.n=parseInt(f,10);faces();paint()}
 roll();
});
start();
TelegramWidget.onEvent("chatDataChanged",function(){start()});
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
