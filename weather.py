"""Weather widget: current conditions and a short forecast, inside the chat.

Data comes from Open-Meteo: free, no API key, no account, and it answers with plain JSON.
The widget itself has no network access at all (QuickJS sandbox), so the bot fetches and
puts the numbers into ``chat_data`` — the widget only draws them.

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
body{margin:0;padding:12px 14px;font:13px/1.35 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif;
background:var(--tg-theme-bg-color,#fff);color:var(--tg-theme-text-color,#000)}
.top{display:flex;align-items:baseline;justify-content:space-between}
.lab{font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--tg-theme-hint-color,#707579)}
.when{font-size:10px;color:var(--tg-theme-hint-color,#707579)}
.now{display:flex;align-items:center;gap:10px;margin:8px 0 4px}
.glyph{font-size:34px;line-height:1}
.temp{font-size:34px;font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.desc{font-size:12px;color:var(--tg-theme-hint-color,#707579)}
.detail{font-size:11px;color:var(--tg-theme-hint-color,#707579);margin-bottom:9px}
.day{display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid rgba(127,127,127,.16)}
.day .d{width:34px;font-size:11px;color:var(--tg-theme-hint-color,#707579);text-transform:uppercase;
letter-spacing:.06em;flex:0 0 34px}
.day .g{font-size:15px;flex:0 0 20px;text-align:center}
.day .r{flex:1;font-size:12px;font-variant-numeric:tabular-nums}
.day .r b{font-weight:600}
.day .p{font-size:10px;color:var(--tg-theme-hint-color,#707579);flex:0 0 auto}
</style></head><body>
<div class="top"><span class="lab" id="lab">Meteo</span><span class="when" id="when"></span></div>
<div class="now"><span class="glyph" id="glyph">—</span><span class="temp" id="temp">—</span></div>
<div class="desc" id="desc"></div>
<div class="detail" id="detail"></div>
<div id="days"></div>
<script>
function esc(s){return String(s).replace(/[&<>"]/g,function(c){
 return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function draw(){
 var raw=TelegramWidget.chatData,data=null;
 try{data=raw?JSON.parse(raw):null}catch(e){data=null}
 if(!data){return}
 document.getElementById("lab").textContent=data.p||"Meteo";
 document.getElementById("glyph").textContent=data.g||"—";
 document.getElementById("temp").textContent=(data.t===null||data.t===undefined)?"—":Math.round(data.t)+"°";
 document.getElementById("desc").textContent=data.s||"";
 document.getElementById("detail").textContent=data.x||"";
 var out="";
 for(var i=0;i<(data.d||[]).length;i++){
  var r=data.d[i];
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
    data = {
        "_at": time.time(),
        "p": place,
        "t": current.get("temperature_2m"),
        "f": current.get("apparent_temperature"),
        "h": current.get("relative_humidity_2m"),
        "w": current.get("wind_speed_10m"),
        "c": current.get("weather_code", 0),
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
    if data.get("h") is not None:
        detail.append(f"umidità {int(data['h'])}%")
    if data.get("w") is not None:
        detail.append(f"vento {round(float(data['w']))} km/h")
    state = {
        "u": int(time.time() // 60),
        "p": data.get("p", "Meteo"),
        "t": round(float(data["t"])) if data.get("t") is not None else None,
        "s": label,
        "g": glyph,
        "x": " · ".join(detail),
        "d": [[row[0], round(float(row[1])), round(float(row[2])), CODES.get(int(row[3]), ("—", ""))[0],
               int(row[4])] for row in data.get("d", [])],
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


def send_weather(chat_id: int, caption: str | None = None, track: bool = True) -> dict:
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
        board.register_board(chat_id, message["message_id"], 4,
                             fingerprint=weather_fingerprint(), kind="weather")
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
