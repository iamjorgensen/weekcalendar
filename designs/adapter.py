"""
Turn data_provider.initial_fetch_all() output into the shape the designs use
(see designs/sample_data.py for that shape).
"""
import math
from datetime import date, datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    OSLO = ZoneInfo("Europe/Oslo")
except Exception:  # pragma: no cover
    OSLO = None

from designs.common import BLACK, BLUE, GREEN, PALETTE, RED, WHITE, YELLOW

# Fallback location (Moss area) if LAT/LON are unknown
DEFAULT_LAT, DEFAULT_LON = 59.4376, 10.6432

CARDINAL_NO = ["N", "NØ", "Ø", "SØ", "S", "SV", "V", "NV"]

PERIODS = [("Morgen", 6, 10), ("Dag", 11, 16), ("Kveld", 17, 22)]

# Worst-weather first: used to pick one symbol for a period
SEVERITY = ["thunder", "snow", "sleet", "rain", "fog", "cloudy", "partlycloudy", "fair", "clearsky"]


def _nearest_palette(rgb):
    if rgb is None:
        return BLACK
    try:
        r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    except Exception:
        return BLACK
    best = min([c for c in PALETTE if c != WHITE],
               key=lambda c: (c[0] - r) ** 2 + (c[1] - g) ** 2 + (c[2] - b) ** 2)
    return best


def _color_of(tag):
    if tag.get("color_rgb") is not None:
        return _nearest_palette(tag["color_rgb"])
    name = str(tag.get("color_name") or tag.get("color") or "").strip().lower()
    return {"black": BLACK, "red": RED, "yellow": YELLOW, "green": GREEN, "blue": BLUE}.get(name, BLACK)


def people_from_tags(tags):
    """Person tags (capitalised names like 'Amalie') -> [(initial, rgb)]. Other tags are ignored."""
    out, seen = [], set()
    for t in tags or []:
        if not isinstance(t, dict):
            continue
        text = str(t.get("text") or "").strip()
        if not text or not text[0].isupper() or len(text) > 24:
            continue
        letter = text[0]
        if letter in seen:
            continue
        seen.add(letter)
        out.append((letter, _color_of(t)))
    return out


def _clean_title(ev):
    title = (ev.get("display_text") or ev.get("name") or ev.get("original_name") or "").strip()
    for prefix in ("Fridag:", "fridag:"):
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
    # leftovers after the tag mapping removed a name, e.g. ": Slutt 13:20" or "Tur –"
    return title.strip(" \t:;,–-|/").strip()


def _is_holiday(ev):
    return bool(ev.get("is_holiday")) or str(ev.get("original_name") or "").lower().startswith("fridag")


def deg_to_cardinal(deg):
    if deg is None:
        return ""
    try:
        return CARDINAL_NO[int((float(deg) % 360 + 22.5) // 45) % 8]
    except Exception:
        return ""


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _symbol_rank(code):
    c = (code or "").lower()
    for i, key in enumerate(SEVERITY):
        if key in c:
            return i
    return len(SEVERITY)


def periods_from_hourly(hourly, today):
    """[(label, symbol_code, temp)] for morning/day/evening of today, from MET hourly data."""
    out = []
    for label, h0, h1 in PERIODS:
        temps, symbols = [], []
        for h in hourly or []:
            try:
                t = datetime.fromisoformat(str(h.get("time")))
            except Exception:
                continue
            if OSLO is not None and t.tzinfo is not None:
                t = t.astimezone(OSLO)
            if t.date() != today or not (h0 <= t.hour <= h1):
                continue
            tv = _num(h.get("temp"))
            if tv is not None:
                temps.append(tv)
            if h.get("symbol"):
                symbols.append(h["symbol"])
        if not temps:
            continue
        temp = round(sum(temps) / len(temps))
        symbol = min(symbols, key=_symbol_rank) if symbols else "cloudy"
        out.append((label, symbol, temp))
    return out


def sun_times(day, lat, lon, tz=OSLO):
    """Sunrise/sunset as 'HH:MM' local time (NOAA approximation). None in polar day/night."""
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    lat_r = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(lat_r) * math.cos(decl))
              - math.tan(lat_r) * math.tan(decl))
    if cos_ha < -1 or cos_ha > 1:
        return None, None
    ha = math.degrees(math.acos(cos_ha))
    res = []
    for sign in (1, -1):  # sunrise, sunset
        minutes_utc = 720 - 4 * (lon + sign * ha) - eqtime
        dt = datetime(day.year, day.month, day.day) + timedelta(minutes=minutes_utc)
        if tz is not None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc).astimezone(tz)
        res.append(dt.strftime("%H:%M"))
    return res[0], res[1]


def _weather_for(entry):
    if not entry:
        return None
    tmax, tmin = _num(entry.get("temp_max")), _num(entry.get("temp_min"))
    if tmax is None or tmin is None:
        return None
    return {
        "symbol": entry.get("condition") or entry.get("symbol") or "",
        "tmax": tmax,
        "tmin": tmin,
        "precip": _num(entry.get("precip")) or 0.0,
        "wind": _num(entry.get("wind_max")) or 0.0,
        "wind_dir": deg_to_cardinal(entry.get("wind_dir_deg")),
    }


def to_design_data(data, days=10, now=None, lat=None, lon=None):
    data = data or {}
    now = now or (datetime.now(OSLO) if OSLO else datetime.now())
    today = now.date()

    by_date = {}
    for ev in data.get("events") or []:
        try:
            d = date.fromisoformat(str(ev.get("date"))[:10])
        except Exception:
            continue
        title = _clean_title(ev)
        if not title:
            continue
        by_date.setdefault(d, []).append({
            "time": (ev.get("time") or "").strip(),
            "title": title,
            "icon": ev.get("icon") or None,
            "people": people_from_tags(ev.get("tags")),
            "is_holiday": _is_holiday(ev),
        })

    weather_by_date = {}
    for w in data.get("weather") or []:
        try:
            weather_by_date[date.fromisoformat(str(w.get("date"))[:10])] = w
        except Exception:
            pass

    out_days = []
    for i in range(max(1, int(days))):
        d = today + timedelta(days=i)
        events = sorted(by_date.get(d, []), key=lambda e: (e["time"] != "", e["time"]))
        out_days.append({"date": d, "events": events, "weather": _weather_for(weather_by_date.get(d))})

    w0 = out_days[0]["weather"]
    if w0 is not None:
        w0["periods"] = periods_from_hourly(data.get("hourly_today"), today)
        la = lat if lat is not None else DEFAULT_LAT
        lo = lon if lon is not None else DEFAULT_LON
        try:
            rise, sset = sun_times(today, la, lo)
        except Exception:
            rise = sset = None
        if rise and sset:
            w0["sunrise"], w0["sunset"] = rise, sset

    battery = data.get("battery")
    if not isinstance(battery, int) or not 0 <= battery <= 100:
        battery = None
    return {"today": today, "days": out_days, "updated": now.strftime("%H:%M"), "battery": battery}
