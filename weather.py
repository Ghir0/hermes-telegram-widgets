"""Weather widget: current conditions, next hours, next days — inside the chat.

Data comes from Open-Meteo: free, no API key, no account, plain JSON. The widget itself has
no network access (QuickJS sandbox), so the bot fetches and writes the numbers into
``chat_data``; the widget only draws them.

Icons are inline SVG built from the WMO code inside the widget: emoji are drawn by the host
font and change on every device, while SVG is identical everywhere and can carry the colour
of the sky.

Location and refresh interval come from the environment:
  WEATHER_LAT   default 43.9102 (Pesaro)
  WEATHER_LON   default 12.9136
  WEATHER_PLACE default "Pesaro"
  WEATHER_TTL   seconds before re-fetching, default 900
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import zlib

try:  # package (plugin loader)
    from . import board
except ImportError:  # script
    import board  # type: ignore[no-redef]

WEATHER_HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}
body{margin:0;padding:0;font:13px/1.3 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif;
background:transparent;color:#fff}
.card{position:relative;overflow:hidden;border-radius:14px;padding:14px 15px 11px;
background:linear-gradient(158deg,var(--sky1,#243b55) 0%,var(--sky2,#141e30) 100%)}
.card:before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.55;
background:repeating-linear-gradient(115deg,rgba(255,255,255,.05) 0 1px,transparent 1px 9px)}
.card>*{position:relative}
.top{display:flex;align-items:baseline;justify-content:space-between}
.place{font-size:10.5px;letter-spacing:.15em;text-transform:uppercase;color:rgba(255,255,255,.8)}
.when{font-size:10px;color:rgba(255,255,255,.62);font-variant-numeric:tabular-nums}
.hero{display:flex;align-items:center;justify-content:space-between;margin:7px 0 1px}
.temp{font-size:52px;font-weight:200;letter-spacing:-.045em;line-height:.95;
font-variant-numeric:tabular-nums;text-shadow:0 2px 18px rgba(0,0,0,.25)}
.ic{width:56px;height:56px;flex:0 0 56px;line-height:0;filter:drop-shadow(0 3px 10px rgba(0,0,0,.3))}
.desc{font-size:12.5px;color:rgba(255,255,255,.9);margin-top:2px}
.chips{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.chip{font-size:10.5px;padding:3px 8px;border-radius:20px;background:rgba(255,255,255,.12);
color:rgba(255,255,255,.85);font-variant-numeric:tabular-nums}
.chip b{font-weight:600;color:#fff}
.strip{display:flex;gap:1px;margin-top:12px;padding:8px 3px;border-radius:12px;
background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.08)}
.col{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;padding:4px 0;border-radius:9px}
.col.now{background:rgba(255,255,255,.16);box-shadow:inset 0 0 0 1px rgba(255,255,255,.12)}
.col .h{font-size:9.5px;color:rgba(255,255,255,.6);letter-spacing:.04em}
.col .g{width:18px;height:18px;line-height:0}
.col .t{font-size:11.5px;font-weight:600;font-variant-numeric:tabular-nums}
.day{display:flex;align-items:center;gap:8px;padding:7px 0 0}
.day .d{width:32px;font-size:10px;letter-spacing:.08em;text-transform:uppercase;
color:rgba(255,255,255,.6);flex:0 0 32px}
.day .g{width:15px;height:15px;flex:0 0 15px;line-height:0}
.day .lo{font-size:10.5px;color:rgba(255,255,255,.55);width:26px;text-align:right;flex:0 0 26px}
.day .hi{font-size:10.5px;font-weight:600;width:26px;flex:0 0 26px;font-variant-numeric:tabular-nums}
.track{flex:1;height:4px;border-radius:3px;background:rgba(255,255,255,.14);position:relative;overflow:hidden}
.fill{position:absolute;top:0;bottom:0;border-radius:3px;
background:linear-gradient(90deg,#5ec8f2,#ffd166)}
.day .p{font-size:9.5px;color:rgba(255,255,255,.5);width:24px;text-align:right;flex:0 0 24px}
.foot{margin-top:11px;padding-top:8px;border-top:1px solid rgba(255,255,255,.1);
font-size:9.5px;color:rgba(255,255,255,.55)}
</style></head><body>
<div class="card" id="card">
<div class="top"><span class="place" id="place">Meteo</span><span class="when" id="when"></span></div>
<div class="hero"><span class="temp" id="temp">—</span><span class="ic" id="ic"></span></div>
<div class="desc" id="desc"></div>
<div class="chips" id="chips"></div>
<div class="strip" id="strip"></div>
<div id="days"></div>
<div class="foot">chiudi: chiedi «chiudi il meteo»</div>
</div>
<script>
var SUN='<circle cx="24" cy="24" r="9" fill="#ffcf5c"/><g stroke="#ffcf5c" stroke-width="2.4" stroke-linecap="round"><path d="M24 5v5M24 38v5M5 24h5M38 24h5M10.6 10.6l3.5 3.5M33.9 33.9l3.5 3.5M37.4 10.6l-3.5 3.5M14.1 33.9l-3.5 3.5"/></g>';
var CLOUD='<path d="M13 33h21a7 7 0 0 0 .6-14 10 10 0 0 0-19-1.6A6.5 6.5 0 0 0 13 33z" fill="#e8eef7"/>';
function drops(c){return '<g stroke="'+c+'" stroke-width="2.4" stroke-linecap="round"><path d="M18 38l-2 5M26 38l-2 5M34 38l-2 5"/></g>'}
function ibody(code,night){
 if(code==0) return night?'<path d="M31 12a13 13 0 1 0 5 22 15 15 0 0 1-5-22z" fill="#dfe8f7"/>':SUN;
 if(code==1||code==2) return '<g transform="translate(4,-4) scale(.72)">'+SUN+'</g>'+CLOUD;
 if(code==3) return CLOUD;
 if(code==45||code==48) return '<g stroke="#cfd8e3" stroke-width="2.6" stroke-linecap="round" opacity=".85"><path d="M9 19h30M9 27h30M9 35h30"/></g>';
 if((code>=51&&code<=67)||(code>=80&&code<=82)) return CLOUD+drops('#7fb8ff');
 if((code>=71&&code<=77)||code==85||code==86) return CLOUD+'<g stroke="#bcd8ff" stroke-width="2.2" stroke-linecap="round"><path d="M20 39l-2 4M30 39l-2 4"/></g>';
 if(code>=95) return CLOUD+'<path d="M25 36l-5 8h5l-2 6 8-9h-5l2-5z" fill="#ffd166"/>';
 return CLOUD;
}
function icon(c,n){return '<svg viewBox="0 0 48 48" width="100%" height="100%">'+ibody(c,n)+'</svg>'}
function sky(code){
 if(code==0) return ['#2b5876','#1b3350'];
 if(code==1||code==2) return ['#2c4a70','#17263d'];
 if(code==3) return ['#33465f','#1a2433'];
 if((code>=51&&code<=67)||(code>=80&&code<=82)) return ['#243b55','#101d2e'];
 if(code>=71&&code<=86) return ['#3a4a63','#1b2536'];
 if(code>=95) return ['#2a2f4a','#12121f'];
 return ['#243b55','#141e30'];
}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){
 return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function draw(){
 var raw=TelegramWidget.chatData,data=null;
 try{data=raw?JSON.parse(raw):null}catch(e){data=null}
 if(!data){return}
 var code=data.c||0,sk=sky(code),card=document.getElementById("card");
 card.style.setProperty("--sky1",sk[0]); card.style.setProperty("--sky2",sk[1]);
 document.getElementById("place").textContent=data.p||"Meteo";
 document.getElementById("temp").textContent=(data.t===null||data.t===undefined)?"—":Math.round(data.t)+"°";
 document.getElementById("ic").innerHTML=icon(code,data.n===1);
 document.getElementById("desc").textContent=data.s||"";
 var chips="";
 if(data.hi!==undefined&&data.hi!==null)chips+='<span class="chip"><b>H:'+Math.round(data.hi)+'°</b>  L:'+Math.round(data.lo)+'°</span>';
 if(data.x)chips+='<span class="chip">'+esc(data.x)+'</span>';
 document.getElementById("chips").innerHTML=chips;
 var strip="",hours=data.hh||[];
 for(var i=0;i<hours.length;i++){
  var c=hours[i];
  strip+='<div class="col'+(i===0?" now":"")+'"><span class="h">'+(i===0?"ora":esc(c[0]))+'</span>'+
   '<span class="g">'+icon(c[2],0)+'</span><span class="t">'+Math.round(c[1])+'°</span></div>';
 }
 document.getElementById("strip").innerHTML=strip;
 var out="",days=data.d||[],lo=99,hi=-99;
 for(var k=0;k<days.length;k++){if(days[k][1]<lo)lo=days[k][1];if(days[k][2]>hi)hi=days[k][2]}
 var span=(hi-lo)||1;
 for(var j=0;j<days.length;j++){
  var r=days[j],l=Math.round((r[1]-lo)/span*100),w=Math.max(12,Math.round((r[2]-r[1])/span*100));
  out+='<div class="day"><span class="d">'+esc(r[0])+'</span>'+
   '<span class="g">'+icon(r[3],0)+'</span>'+
   '<span class="lo">'+Math.round(r[1])+'°</span>'+
   '<span class="track"><span class="fill" style="left:'+l+'%;width:'+w+'%"></span></span>'+
   '<span class="hi">'+Math.round(r[2])+'°</span>'+
   '<span class="p">'+(r[4]>0?r[4]+"%":"")+'</span></div>';
 }
 document.getElementById("days").innerHTML=out;
 if(data.u){var d=new Date(data.u*60000);document.getElementById("when").textContent=
  ("0"+d.getHours()).slice(-2)+":"+("0"+d.getMinutes()).slice(-2)}
}
draw();
TelegramWidget.onEvent("chatDataChanged",draw);
</script></body></html>"""

# WMO codes → short Italian label
LABELS = {
    0: "sereno", 1: "poco nuvoloso", 2: "parzialmente nuvoloso", 3: "nuvoloso",
    45: "nebbia", 48: "nebbia gelata",
    51: "pioviggine", 53: "pioviggine", 55: "pioviggine forte",
    56: "pioviggine gelata", 57: "pioviggine gelata",
    61: "pioggia debole", 63: "pioggia", 65: "pioggia forte",
    66: "pioggia gelata", 67: "pioggia gelata",
    71: "neve debole", 73: "neve", 75: "neve forte", 77: "granelli",
    80: "rovesci", 81: "rovesci", 82: "rovesci forti",
    85: "rovesci di neve", 86: "rovesci di neve",
    95: "temporale", 96: "temporale con grandine", 99: "temporale forte",
}
GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def _cfg(name: str, default: str) -> str:
    return board._env(name) or default


def _cache_path():
    return board.state_dir() / "weather.json"


def fetch(force: bool = False) -> dict:
    """Open-Meteo, cached: the watcher may ask every two seconds, the API must not."""
    ttl = int(_cfg("WEATHER_TTL", "900"))
    path = _cache_path()
    if not force and path.exists():
        try:
            cached = json.loads(path.read_text())
            if time.time() - cached.get("_at", 0) < ttl:
                return cached
        except json.JSONDecodeError:
            pass

    lat = _cfg("WEATHER_LAT", "43.9102")
    lon = _cfg("WEATHER_LON", "12.9136")
    place = _cfg("WEATHER_PLACE", "Pesaro")
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat}&longitude={lon}"
           "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
           "&hourly=temperature_2m,weather_code"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
           "&timezone=Europe%2FRome&forecast_days=4")
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        if path.exists():  # meglio un dato vecchio che nessun dato
            data = json.loads(path.read_text())
            data["_stale"] = str(error)[:80]
            return data
        raise

    current = payload.get("current", {})
    daily = payload.get("daily", {})
    hourly = payload.get("hourly", {})

    hours = hourly.get("time", [])
    stamp = str(current.get("time", ""))[:13] + ":00"
    start = hours.index(stamp) if stamp in hours else 0
    next_hours = []
    for i in range(start, min(start + 6, len(hours))):
        next_hours.append([hours[i][11:13], hourly["temperature_2m"][i], hourly["weather_code"][i]])

    hour_now = int(hours[start][11:13]) if start < len(hours) else 12
    night = 1 if (hour_now >= 20 or hour_now < 6) else 0

    data = {
        "_at": time.time(),
        "p": place,
        "t": current.get("temperature_2m"),
        "f": current.get("apparent_temperature"),
        "h": current.get("relative_humidity_2m"),
        "w": current.get("wind_speed_10m"),
        "c": current.get("weather_code", 0),
        "n": night,
        "hh": next_hours,
        "d": [],
    }
    for i, day in enumerate(daily.get("time", [])[:4]):
        year, month, dom = (int(x) for x in day.split("-"))
        weekday = GIORNI[time.strptime(f"{year}-{month}-{dom}", "%Y-%m-%d").tm_wday]
        data["d"].append([weekday, daily["temperature_2m_min"][i], daily["temperature_2m_max"][i],
                          daily["weather_code"][i], daily["precipitation_probability_max"][i] or 0])
    path.write_text(json.dumps(data, ensure_ascii=False))
    return data


def weather_state(force: bool = False) -> str:
    data = fetch(force)
    code = int(data.get("c") or 0)
    detail = []
    if data.get("w") is not None:
        detail.append(f"vento {round(float(data['w']))} km/h")

    days = data.get("d", [])
    today = days[0] if days else [None, None, None]
    state = {
        "u": int(time.time() // 60),
        "p": data.get("p", "Meteo"),
        "t": round(float(data["t"])) if data.get("t") is not None else None,
        "s": LABELS.get(code, ""),
        "c": code,
        "n": int(data.get("n", 0)),
        "hi": round(float(today[2])) if today[2] is not None else None,
        "lo": round(float(today[1])) if today[1] is not None else None,
        "x": " · ".join(detail),
        "hh": [[row[0], round(float(row[1])), int(row[2])] for row in data.get("hh", [])],
        "d": [[row[0], round(float(row[1])), round(float(row[2])), int(row[3]), int(row[4])]
              for row in days[1:4]],
    }
    return json.dumps(state, ensure_ascii=False, separators=(",", ":"))


def weather_fingerprint() -> str:
    payload = json.loads(weather_state())
    payload.pop("u", None)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def size_report_weather() -> dict:
    raw = len(WEATHER_HTML.encode())
    packed = len(zlib.compress(WEATHER_HTML.encode(), 9))
    return {"html_bytes": raw, "zlib_bytes": packed, "ok": raw <= 32768 and packed <= 4096}


def send_weather(chat_id: int, caption: str | None = None, track: bool = True,
                 ttl: int | None = 120) -> dict:
    check = size_report_weather()
    if not check["ok"]:
        raise RuntimeError(f"widget too large: {check}")
    state = weather_state()
    payload = {"chat_id": chat_id, "html": WEATHER_HTML, "width": 0, "height": 0,
               "chat_data": state, "allow_queries": False}
    if caption:
        payload["caption"] = caption[:1024]
    answer = board.api("sendWidget", payload)
    if not answer.get("ok"):
        return {"ok": False, "error": answer.get("description"), "sizes": check}
    message = answer["result"]
    if track:
        board.register_board(chat_id, message["message_id"], 6,
                             fingerprint=weather_fingerprint(), kind="weather", ttl=ttl)
    return {"ok": True, "message_id": message["message_id"], "chat_id": chat_id,
            "state_bytes": len(state.encode()), "sizes": check}


def refresh_weather(chat_id: int, message_id: int) -> dict:
    state = weather_state()
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
