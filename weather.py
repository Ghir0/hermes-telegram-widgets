"""Weather widget: current conditions, next hours, next days — inside the chat.

Data comes from Open-Meteo: free, no API key, no account, plain JSON. The widget itself has
no network access (QuickJS sandbox), so the bot fetches and writes the numbers into
``chat_data``; the widget only draws them.

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
body{margin:0;padding:13px 15px 10px;font:13px/1.3 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif;
background:var(--tg-theme-bg-color,#fff);color:var(--tg-theme-text-color,#000)}
.top{display:flex;align-items:baseline;justify-content:space-between}
.place{font-size:12.5px;font-weight:600;letter-spacing:.01em}
.when{font-size:10px;color:var(--tg-theme-hint-color,#707579)}
.hero{display:flex;align-items:center;justify-content:space-between;margin:6px 0 2px}
.temp{font-size:42px;font-weight:300;letter-spacing:-.03em;line-height:1;font-variant-numeric:tabular-nums}
.glyph{font-size:40px;line-height:1}
.desc{font-size:12px;color:var(--tg-theme-hint-color,#707579)}
.hl{font-size:11.5px;color:var(--tg-theme-hint-color,#707579);margin-top:3px}
.hl b{font-weight:600;color:var(--tg-theme-text-color,#000)}
.strip{display:flex;gap:2px;margin:11px 0 2px;padding:7px 4px;border-radius:11px;
background:rgba(127,127,127,.09)}
.col{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;padding:3px 0;border-radius:8px}
.col.now{background:rgba(127,127,127,.16)}
.col .h{font-size:9.5px;color:var(--tg-theme-hint-color,#707579);letter-spacing:.03em}
.col .g{font-size:15px;line-height:1}
.col .t{font-size:11.5px;font-weight:600;font-variant-numeric:tabular-nums}
.day{display:flex;align-items:center;gap:8px;padding:5px 0;border-top:1px solid rgba(127,127,127,.14)}
.day .d{width:32px;font-size:10.5px;color:var(--tg-theme-hint-color,#707579);text-transform:uppercase;
letter-spacing:.06em;flex:0 0 32px}
.day .g{font-size:14px;flex:0 0 18px;text-align:center}
.day .r{flex:1;font-size:11.5px;font-variant-numeric:tabular-nums}
.day .r b{font-weight:600}
.day .p{font-size:10px;color:var(--tg-theme-hint-color,#707579);flex:0 0 auto}
.foot{margin-top:8px;padding-top:7px;border-top:1px solid rgba(127,127,127,.14);
font-size:10px;color:var(--tg-theme-hint-color,#707579)}
</style></head><body>
<div class="top"><span class="place" id="place">Meteo</span><span class="when" id="when"></span></div>
<div class="hero"><span class="temp" id="temp">—</span><span class="glyph" id="glyph">—</span></div>
<div class="desc" id="desc"></div>
<div class="hl" id="hl"></div>
<div class="strip" id="strip"></div>
<div id="days"></div>
<div class="foot">chiudi: chiedi «chiudi il meteo»</div>
<script>
function esc(s){return String(s).replace(/[&<>"]/g,function(c){
 return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function draw(){
 var raw=TelegramWidget.chatData,data=null;
 try{data=raw?JSON.parse(raw):null}catch(e){data=null}
 if(!data){return}
 document.getElementById("place").textContent=data.p||"Meteo";
 document.getElementById("glyph").textContent=data.g||"—";
 document.getElementById("temp").textContent=(data.t===null||data.t===undefined)?"—":Math.round(data.t)+"°";
 document.getElementById("desc").textContent=data.s||"";
 document.getElementById("hl").innerHTML=(data.hi!==undefined?
   "<b>H:"+Math.round(data.hi)+"°</b>  <b>L:"+Math.round(data.lo)+"°</b>":"")+
   (data.x?"  ·  "+esc(data.x):"");
 var strip="",hours=data.hh||[];
 for(var i=0;i<hours.length;i++){
  var c=hours[i];
  strip+='<div class="col'+(i===0?" now":"")+'"><span class="h">'+(i===0?"ora":c[0]+"")+'</span>'+
   '<span class="g">'+esc(c[2])+'</span><span class="t">'+Math.round(c[1])+'°</span></div>';
 }
 document.getElementById("strip").innerHTML=strip;
 var out="",days=data.d||[];
 for(var j=0;j<days.length;j++){
  var r=days[j];
  out+='<div class="day"><span class="d">'+esc(r[0])+'</span>'+
   '<span class="g">'+esc(r[3])+'</span>'+
   '<span class="r"><b>'+Math.round(r[2])+'°</b> / '+Math.round(r[1])+'°</span>'+
   '<span class="p">'+(r[4]>0?r[4]+"%":"")+'</span></div>';
 }
 document.getElementById("days").innerHTML=out;
 if(data.u){var d=new Date(data.u*60000);document.getElementById("when").textContent=
  ("0"+d.getHours()).slice(-2)+":"+("0"+d.getMinutes()).slice(-2)}
}
draw();
TelegramWidget.onEvent("chatDataChanged",draw);
</script></body></html>"""

# WMO weather codes → glyph + short Italian label
CODES = {
    0: ("☀", "sereno"), 1: ("🌤", "poco nuvoloso"), 2: ("⛅", "parzialmente nuvoloso"),
    3: ("☁", "nuvoloso"), 45: ("🌫", "nebbia"), 48: ("🌫", "nebbia gelata"),
    51: ("🌦", "pioviggine"), 53: ("🌦", "pioviggine"), 55: ("🌧", "pioviggine forte"),
    56: ("🌧", "pioviggine gelata"), 57: ("🌧", "pioviggine gelata"),
    61: ("🌧", "pioggia debole"), 63: ("🌧", "pioggia"), 65: ("🌧", "pioggia forte"),
    66: ("🌧", "pioggia gelata"), 67: ("🌧", "pioggia gelata"),
    71: ("🌨", "neve debole"), 73: ("🌨", "neve"), 75: ("❄", "neve forte"), 77: ("🌨", "granelli"),
    80: ("🌦", "rovesci"), 81: ("🌧", "rovesci"), 82: ("⛈", "rovesci forti"),
    85: ("🌨", "rovesci di neve"), 86: ("🌨", "rovesci di neve"),
    95: ("⛈", "temporale"), 96: ("⛈", "temporale con grandine"), 99: ("⛈", "temporale forte"),
}
GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def _cfg(name: str, default: str) -> str:
    return board._env(name) or default


def _cache_path():
    return board.state_dir() / "weather.json"


def _glyph(code) -> str:
    return CODES.get(int(code or 0), ("—", ""))[0]


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

    # prossime 6 ore a partire da quella corrente
    hours = hourly.get("time", [])
    stamp = str(current.get("time", ""))[:13] + ":00"
    start = hours.index(stamp) if stamp in hours else 0
    next_hours = []
    for i in range(start, min(start + 6, len(hours))):
        label = hours[i][11:13]
        next_hours.append([f"{label}", hourly["temperature_2m"][i], hourly["weather_code"][i]])

    data = {
        "_at": time.time(),
        "p": place,
        "t": current.get("temperature_2m"),
        "f": current.get("apparent_temperature"),
        "h": current.get("relative_humidity_2m"),
        "w": current.get("wind_speed_10m"),
        "c": current.get("weather_code", 0),
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
    glyph, label = CODES.get(int(data.get("c") or 0), ("—", ""))
    detail = []
    if data.get("f") is not None:
        detail.append(f"percepiti {round(float(data['f']))}°")
    if data.get("w") is not None:
        detail.append(f"vento {round(float(data['w']))} km/h")

    days = data.get("d", [])
    today = days[0] if days else [None, None, None]
    state = {
        "u": int(time.time() // 60),
        "p": data.get("p", "Meteo"),
        "t": round(float(data["t"])) if data.get("t") is not None else None,
        "s": label,
        "g": glyph,
        "hi": round(float(today[2])) if today[2] is not None else None,
        "lo": round(float(today[1])) if today[1] is not None else None,
        "x": " · ".join(detail),
        "hh": [[row[0], round(float(row[1])), _glyph(row[2])] for row in data.get("hh", [])],
        "d": [[row[0], round(float(row[1])), round(float(row[2])), _glyph(row[3]), int(row[4])]
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
