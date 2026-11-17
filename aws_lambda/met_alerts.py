"""
Weather warnings (farevarsler) from MET Norway's MetAlerts 2.0 API for one point.
Stdlib only.

  GET https://api.met.no/weatherapi/metalerts/2.0/current.json?lat=..&lon=..
  -> GeoJSON features; properties include event, eventAwarenessName ("Kuling"),
     awareness_level ("2; yellow; Moderate"), riskMatrixColor, title, instruction,
     and when.interval [start, end].

MET's terms require a User-Agent that identifies the application.
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime

URL = "https://api.met.no/weatherapi/metalerts/2.0/current.json"
USER_AGENT = "weekcalendar/1.0 (e-ink family calendar)"
LEVELS = {"yellow": 1, "orange": 2, "red": 3}
LEVEL_NO = {"yellow": "gult", "orange": "oransje", "red": "rødt"}

# what to do, short enough for one line on the frame
TIPS = {
    "wind": "sikre løse ting ute", "gale": "sikre løse ting ute", "storm": "sikre trampolinen",
    "polarLow": "sikre løse ting ute",
    "rain": "mye regn", "rainFlood": "fare for oversvømmelse", "flood": "fare for flom",
    "stormSurge": "høy vannstand",
    "snow": "mye snø", "blowingSnow": "snøfokk", "icing": "glatt", "ice": "glatt",
    "avalanches": "skredfare", "landslide": "jordskredfare", "lightning": "torden",
    "forestFire": "fare for skogbrann – ikke grill ute",
}


def _parse_time(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def parse(geojson):
    """Features -> [{name, level, color, event, start, end, tip, title}] sorted by severity."""
    out = []
    for f in (geojson or {}).get("features") or []:
        p = f.get("properties") or {}
        color = str(p.get("riskMatrixColor") or "").lower()
        if color not in LEVELS:
            parts = [x.strip().lower() for x in str(p.get("awareness_level") or "").split(";")]
            color = next((x for x in parts if x in LEVELS), "yellow")
        interval = ((f.get("when") or {}).get("interval")) or []
        start = _parse_time(interval[0]) if interval else None
        end = _parse_time(interval[1]) if len(interval) > 1 else _parse_time(p.get("eventEndingTime"))
        event = str(p.get("event") or "")
        name = str(p.get("eventAwarenessName") or event or "Farevarsel")
        out.append({"name": name[:30], "level": LEVELS[color], "color": color, "event": event,
                    "start": start.isoformat() if start else "", "end": end.isoformat() if end else "",
                    "tip": TIPS.get(event, ""), "title": str(p.get("title") or "")[:200]})
    out.sort(key=lambda w: (-w["level"], w["start"]))
    return out


def fetch(lat, lon, timeout=8):
    """Current warnings for the point, [] on any problem (never breaks the render)."""
    q = urllib.parse.urlencode({"lat": f"{float(lat):.3f}", "lon": f"{float(lon):.3f}"})
    req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status == 204:
            return []
        return parse(json.loads(r.read() or b"{}"))


def describe(w, when=""):
    """'Gult farevarsel: Kuling i kveld – sikre løse ting ute'"""
    text = f"{LEVEL_NO.get(w['color'], 'gult').capitalize()} farevarsel: {w['name']}"
    if when:
        text += f" {when}"
    if w.get("tip"):
        text += f" – {w['tip']}"
    return text
