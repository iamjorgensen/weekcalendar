# data_provider.py
"""
Henter og normaliserer data: events, weather, tommekalender.
Leser konfig fra miljøvariabler:
  - API_KEY_GOOGLE
  - CALENDAR_ID
  - MOVAR_API_TOKEN
  - MOVAR_BASE
  - LAT, LON
  - KOMMUNENR (valgfri, default 3103)
  - MOVAR_GATENAVN, MOVAR_HUSNR (valgfri)

Kjør som skript for rask feilsøking:
  python data_provider.py
"""
import os
import requests
from datetime import datetime, timedelta, timezone
import re
from PIL import ImageColor

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Oslo")
except Exception:
    TZ = None

from dotenv import load_dotenv
load_dotenv()

# --- Konfig fra miljøvariabler (fallbacks for enkel testing) ---
API_KEY_GOOGLE = os.environ.get("API_KEY_GOOGLE", "")
CALENDAR_ID = os.environ.get("CALENDAR_ID", "")

# Optional separate calendar id for public holidays (fallback to the official Norway holidays calendar)
HOLIDAYS_CALENDAR_ID = os.environ.get("HOLIDAYS_CALENDAR_ID","")
MOVAR_API_TOKEN = os.environ.get("MOVAR_API_TOKEN", "")
MOVAR_BASE = os.environ.get("MOVAR_BASE", "")
LAT = float(os.environ.get("LAT", ""))
LON = float(os.environ.get("LON", ""))
KOMMUNENR = os.environ.get("KOMMUNENR", "")
MOVAR_GATENAVN = os.environ.get("MOVAR_GATENAVN", "")
MOVAR_HUSNR = os.environ.get("MOVAR_HUSNR", "")

# Hvor mange dager vi viser standard
DEFAULT_DAYS = int(os.environ.get("DEFAULT_DAYS", "14"))


# --- Configuration ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# DEBUG: Verify key loading
if not OPENAI_API_KEY:
    print("[DEBUG] WARNING: OPENAI_API_KEY is empty or not found in .env")
else:
    print(f"[DEBUG] OpenAI API Key detected (starts with {OPENAI_API_KEY[:5]}...)")

def get_ai_suggested_icon(summary: str):
    """
    Uses OpenAI to suggest a Lucide icon name.
    Input text is often in Norwegian.
    """
    if not OPENAI_API_KEY:
        # We don't print here to avoid spamming if the key is missing
        return None

    # This log tells you the fallback is actually starting
    print(f"[AI Icon] No local mapping for '{summary}'. Asking OpenAI...")
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system", 
                    "content": "You map calendar events to Lucide icon names. Return ONLY the single most relevant lowercase icon name (e.g. 'utensils', 'car', 'users'). The input is in Norwegian. No punctuation, no explanation."
                },
                {"role": "user", "content": f"Event: {summary}"}
            ],
            temperature=0,
            max_tokens=10
        )
        suggestion = response.choices[0].message.content.strip().lower()
        # Clean up potential extra words or dots
        suggestion = suggestion.split()[0].replace(".", "").replace("'", "")
        print(f"[AI Icon] SUCCESS: Suggested '{suggestion}' for '{summary}'")
        return suggestion
    except Exception as e:
        print(f"[AI Icon Error] {e}")
        return None


# Try to import mapping helpers (non-fatal)
def parse_locationforecast_timeseries(timeseries):
    """
    Convert Locationforecast 'properties.timeseries' into a simple hourly list:
    [{'time': ISO, 'temp': float, 'precip': float, 'symbol_code': str, 'condition': str}, ...]
    """
    out = []
    for item in (timeseries or []):
        t = item.get("time") or item.get("validTime") or None

        # instant details (air temp etc.)
        inst = item.get("data", {}).get("instant", {}).get("details", {}) if item.get("data") else item.get("data", {}).get("instant", {}).get("details", {})
        temp = None
        if inst:
            temp = inst.get("air_temperature") or inst.get("airTemperature") or inst.get("temperature") or inst.get("temp")

        # Prefer next_1_hours (1-hour period) fields if present, else next_6_hours, else next_12_hours
        precip = None
        symbol_code = None
        for key in ("next_1_hours", "next_6_hours", "next_12_hours"):
            period = item.get("data", {}).get(key) if item.get("data") else item.get(key)
            if period:
                # precipitation amount often under period['details']['precipitation_amount'] or period['details']['precipitation']
                det = period.get("details", {}) or {}
                precip = det.get("precipitation_amount") or det.get("precipitation") or det.get("precipitation_amount_mm") or precip
                # symbol code sometimes under period['summary']['symbol_code'] or period['summary']['symbol']
                summary = period.get("summary") or {}
                symbol_code = summary.get("symbol_code") or summary.get("symbol") or symbol_code
                # if we found a 1-hour block, prefer it and break
                if key == "next_1_hours":
                    break

        # Fallbacks: try top-level summary if period missing
        if not symbol_code:
            top_summary = item.get("data", {}).get("summary", {}) if item.get("data") else item.get("summary", {})
            symbol_code = top_summary.get("symbol_code") or top_summary.get("symbol") or symbol_code

        # normalize precip and temp types
        try:
            precip = float(precip) if precip is not None else 0.0
        except Exception:
            precip = 0.0
        try:
            temp = float(temp) if temp is not None else None
        except Exception:
            temp = None

        # condition: map symbol_code into a friendly word
        cond = None
        if symbol_code:
            sc = symbol_code.lower()
            # common symbol name hints: 'clearsky', 'fair', 'partlycloudy', 'cloudy', 'rain', 'lightrain', 'heavyrain', 'snow', 'sleet', 'thunder'
            if "clear" in sc or "clearsky" in sc:
                cond = "Klarvær"
            elif "fair" in sc or "partly" in sc or "partlycloudy" in sc:
                cond = "Delvis skyet"
            elif "cloud" in sc or "overcast" in sc:
                cond = "Skyet"
            elif "rain" in sc or "shower" in sc or "drizzle" in sc:
                cond = "Regn"
            elif "snow" in sc or "snowshow" in sc:
                cond = "Snø"
            elif "sleet" in sc:
                cond = "Sludd"
            elif "thunder" in sc or "tstorm" in sc:
                cond = "Torden"
            else:
                cond = symbol_code
        else:
            # if no symbol_code available, fallback: guess from precip/temp
            if precip >= 2.5:
                cond = "Regn" if (temp is None or temp > 1.5) else "Snø"
            elif temp is not None and temp <= -1.5:
                cond = "Skyet"
            else:
                cond = "Delvis skyet"

        out.append({
            "time": t,
            "temp": temp,
            "precip": precip,
            "symbol_code": symbol_code,
            "condition": cond
        })
    return out


try:
    import mappings as mappings_module
    # expose common helpers if present
    mapping_info_for_event = getattr(mappings_module, "mapping_info_for_event", None)
    EVENT_MAPPINGS = getattr(mappings_module, "EVENT_MAPPINGS", None)
    color_to_rgb = getattr(mappings_module, "color_to_rgb", None)
except Exception:
    mappings_module = None
    mapping_info_for_event = None
    color_to_rgb = None
    EVENT_MAPPINGS = None

# Avoid duplicate zoneinfo block - we've already set TZ above, but keep a warning if not set
try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    if TZ is None:
        TZ = _ZoneInfo("Europe/Oslo")
except Exception:
    if TZ is None:
        TZ = None
        print("[WARN] zoneinfo.ZoneInfo('Europe/Oslo') unavailable: falling back to system local time")


def now_local():
    """
    Return an AWARE datetime in Europe/Oslo if possible,
    otherwise a naive datetime in the system local time (with warning above).
    """
    if TZ:
        return datetime.now(TZ)
    return datetime.now()


def date_string_for_offset(day_index=0):
    d = now_local().date() + timedelta(days=day_index)
    return d.strftime("%Y-%m-%d")


# --------------------------------------------------------------------
# Lightweight apply_event_mapping shim (SIMPLIFIED)
# --------------------------------------------------------------------
# This file no longer contains the heavy apply_event_mapping implementation.
# Instead we prefer mappings.apply_event_mapping when available.
# We remove the old mapping_info_for_event fallback entirely.
# Note: ImageColor, re, and importlib are assumed imported globally or via imports in surrounding code.


# --- REMOVED: _safe_rgb_from_mapping_entry as it is now redundant ---
def apply_event_mapping(summary: str):
    original = (summary or "").strip()
    out = {
        "display_text": original,
        "tag_text": None,
        "tag_color_name": None,
        "tag_color_rgb": None,
        "icon": None,
        "icon_size": None,
        "icon_color_name": "",
        "icon_color_rgb": None,
        "mode": None,
        "filtered_out": False,
        "original_name": original,
        "tags": [],
    }

    # 1) TRY LOCAL MAPPING FIRST
    found_local_icon = False
    try:
        if mappings_module and hasattr(mappings_module, "apply_event_mapping"):
            res = mappings_module.apply_event_mapping(original)
            if isinstance(res, dict):
                # Apply all keys from mapping (This preserves your "Middag:" stripping logic)
                for k in out.keys():
                    if k in res:
                        out[k] = res.get(k)
                if res.get("tags"):
                    out["tags"] = res.get("tags")
                
                # Check if we found an icon in your CSV/Mappings
                if out.get("icon"):
                    found_local_icon = True
    except Exception:
        pass

    # 2) AI FALLBACK
    # Trigger ONLY if no icon was found locally and we have an API key
    if not found_local_icon:
        # Use display_text if mapping stripped it, otherwise use original summary
        ai_query = out.get("display_text") or original
        if ai_query and len(ai_query.strip()) > 0:
            ai_icon = get_ai_suggested_icon(ai_query)
            if ai_icon:
                out["icon"] = ai_icon
        else:
            # This handles your "Middag:" case where text might be intentionally empty
            print(f"[AI Icon] Skipped: Mapping for '{original}' resulted in empty text.")

    return out

# --------------------------------------------------------------------
# Tommekalender integration
# --------------------------------------------------------------------
def fetch_fraction_names(session=None):
    session = session or requests.Session()
    url = f"{MOVAR_BASE}/Fraksjoner"
    headers = {"Kommunenr": KOMMUNENR, "Accept": "application/json", "User-Agent": "InkyFrameCalendar/1.0"}
    params = {"apitoken": MOVAR_API_TOKEN} if MOVAR_API_TOKEN else {}
    try:
        r = session.get(url, headers=headers, params=params, timeout=10, verify=True)
        if r.status_code == 200:
            data = r.json()
            return {int(item.get("id", -1)): item.get("navn", "") for item in data}
        else:
            if r.status_code == 401:
                try_headers = headers.copy()
                try_headers["apitoken"] = MOVAR_API_TOKEN
                r2 = session.get(url, headers=try_headers, timeout=10, verify=True)
                print("[fetch_fraction_names] retry with apitoken header status:", r2.status_code)
            return {}
    except Exception as ex:
        print("[fetch_fraction_names] exception:", ex)
        return {}


def fetch_tommekalender_events(fraction_names, days=DEFAULT_DAYS, session=None, gatenavn=None, husnr=None):
    session = session or requests.Session()
    gatenavn = gatenavn or MOVAR_GATENAVN
    husnr = husnr or MOVAR_HUSNR
    url = f"{MOVAR_BASE}/Tommekalender"
    headers = {"Kommunenr": KOMMUNENR, "Accept": "application/json", "User-Agent": "InkyFrameCalendar/1.0"}
    params = {"gatenavn": gatenavn, "husnr": husnr}
    if MOVAR_API_TOKEN:
        params["apitoken"] = MOVAR_API_TOKEN
    events = []
    try:
        r = session.get(url, headers=headers, params=params, timeout=10, verify=True)
        if r.status_code != 200:
            if r.status_code == 401 and MOVAR_API_TOKEN:
                try_headers = headers.copy()
                try_headers["apitoken"] = MOVAR_API_TOKEN
                r2 = session.get(url, headers=try_headers, params={"gatenavn": gatenavn, "husnr": husnr}, timeout=10, verify=True)
            return events
        data = r.json()
        allowed = {date_string_for_offset(i) for i in range(days)}
        for item in data:
            try:
                fid = int(item.get("fraksjonId", -1))
            except Exception:
                fid = -1
            dates = item.get("tommedatoer", []) or []
            for d_iso in dates:
                if not d_iso:
                    continue
                date_part = d_iso[:10]
                if date_part in allowed:
                    raw_name = "Movar: " + fraction_names.get(fid, "Ukjent")
                    mapped = apply_event_mapping(raw_name)
                    if mapped.get("filtered_out"):
                        continue
                    ev = {
                        "date": date_part,
                        "name": mapped.get("display_text") or "",
                        "display_text": mapped.get("display_text"),
                        "tag_text": mapped.get("tag_text"),
                        "tag_color_name": mapped.get("tag_color_name"),
                        "tag_color_rgb": mapped.get("tag_color_rgb"),
                        "time": "",
                        "icon": mapped.get("icon"),
                        "icon_size": mapped.get("icon_size"),
                        "icon_color_name": mapped.get("icon_color_name"),
                        "icon_color_rgb": mapped.get("icon_color_rgb"),
                        "icon_mode": mapped.get("mode"),
                        "original_name": raw_name,
                    }
                    if not any(e['date'] == ev['date'] and e['name'] == ev['name'] for e in events):
                        events.append(ev)
    except Exception as ex:
        print("[fetch_tommekalender_events] exception:", ex)
    return events


# --------------------------------------------------------------------
# Google Calendar integration
# --------------------------------------------------------------------
def _ensure_aware(dt):
    """
    Return a tz-aware datetime in UTC.
    - If dt has tzinfo: convert to UTC.
    - If dt is naive: assume it's in TZ (Europe/Oslo) if TZ available, otherwise assume system local time and convert to UTC.
    """
    if dt.tzinfo is None:
        if TZ:
            dt = dt.replace(tzinfo=TZ)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fetch_google_calendar_events(days=DEFAULT_DAYS, session=None):
    session = session or requests.Session()
    today_local = now_local().date()

    if TZ:
        start_local_dt = datetime(year=today_local.year, month=today_local.month, day=today_local.day,
                                  hour=0, minute=0, second=0, microsecond=0, tzinfo=TZ)
    else:
        start_local_dt = datetime.combine(today_local, datetime.min.time())  # naive
    start_utc = _ensure_aware(start_local_dt)
    end_utc = start_utc + timedelta(days=days)

    def iso_z(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    timeMin = iso_z(start_utc)
    timeMax = iso_z(end_utc)
    url = (
        f"https://www.googleapis.com/calendar/v3/calendars/{CALENDAR_ID}/events"
        f"?timeMin={timeMin}&timeMax={timeMax}&singleEvents=true&fields=items(summary,start,end)&orderBy=startTime&key={API_KEY_GOOGLE}"
    )

    events = []
    try:
        r = session.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            items = data.get("items", [])
            for it in items:
                summary = (it.get("summary") or "").strip()
                if not summary:
                    continue
                # Removed redundant pre-check logic (was lines 339-346)
                
                start = it.get("start", {})
                end = it.get("end", {})
                if "date" in start:  # heldags-event
                    sdate = start["date"]
                    edate = end.get("date", sdate)
                    try:
                        sdt = datetime.strptime(sdate, "%Y-%m-%d").date()
                        edt = datetime.strptime(edate, "%Y-%m-%d").date()
                    except Exception:
                        sdt = None
                        edt = None

                    try:
                        query_start_date = start_local_dt.date()
                    except Exception:
                        query_start_date = now_local().date()

                    if sdt is None or edt is None:
                        date_str = sdate
                        try:
                            if datetime.strptime(date_str, "%Y-%m-%d").date() < query_start_date:
                                continue
                        except Exception:
                            pass
                        mapped = apply_event_mapping(summary)
                        if mapped.get("filtered_out"):
                            continue
                        ev = {
                            "date": date_str,
                            "name": mapped.get("display_text") or "",
                            "display_text": mapped.get("display_text"),
                            "tag_text": mapped.get("tag_text"),
                            "tag_color_name": mapped.get("tag_color_name"),
                            "tag_color_rgb": mapped.get("tag_color_rgb"),
                            "time": "",
                            "icon": mapped.get("icon"),
                            "icon_size": mapped.get("icon_size"),
                            "icon_color_name": mapped.get("icon_color_name"),
                            "icon_color_rgb": mapped.get("icon_color_rgb"),
                            "icon_mode": mapped.get("mode"),
                            "original_name": summary,
                        }
                        if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in events):
                            events.append(ev)
                    else:
                        last_day = edt - timedelta(days=1)
                        day = max(sdt, query_start_date)
                        while day <= last_day:
                            date_str = day.strftime("%Y-%m-%d")
                            mapped = apply_event_mapping(summary)
                            if mapped.get("filtered_out"):
                                day += timedelta(days=1)
                                continue
                            ev = {
                                "date": date_str,
                                "name": mapped.get("display_text") or "",
                                "display_text": mapped.get("display_text"),
                                "tag_text": mapped.get("tag_text"),
                                "tag_color_name": mapped.get("tag_color_name"),
                                "tag_color_rgb": mapped.get("tag_color_rgb"),
                                "time": "",
                                "icon": mapped.get("icon"),
                                "icon_size": mapped.get("icon_size"),
                                "icon_color_name": mapped.get("icon_color_name"),
                                "icon_color_rgb": mapped.get("icon_color_rgb"),
                                "icon_mode": mapped.get("mode"),
                                "original_name": summary,
                            }
                            if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in events):
                                events.append(ev)
                            day += timedelta(days=1)
                elif "dateTime" in start:
                    dt_start_raw = start.get("dateTime")
                    dt_end_raw = end.get("dateTime") or dt_start_raw

                    dt_core_start = dt_start_raw[:19]
                    dt_core_end = dt_end_raw[:19]
                    try:
                        dt_start = datetime.strptime(dt_core_start, "%Y-%m-%dT%H:%M:%S")
                        dt_end = datetime.strptime(dt_core_end, "%Y-%m-%dT%H:%M:%S")
                    except Exception:
                        try:
                            dt = datetime.strptime(dt_core_start, "%Y-%m-%dT%H:%M:%S")
                            date_str = dt.strftime("%Y-%m-%d")
                            time_str = dt.strftime("%H:%M")
                            mapped = apply_event_mapping(summary)
                            if mapped.get("filtered_out"):
                                continue
                            ev = {
                                "date": date_str,
                                "name": mapped.get("display_text") or "",
                                "display_text": mapped.get("display_text"),
                                "tag_text": mapped.get("tag_text"),
                                "tag_color_name": mapped.get("tag_color_name"),
                                "tag_color_rgb": mapped.get("tag_color_rgb"),
                                "time": time_str,
                                "icon": mapped.get("icon"),
                                "icon_size": mapped.get("icon_size"),
                                "icon_color_name": mapped.get("icon_color_name"),
                                "icon_color_rgb": mapped.get("icon_color_rgb"),
                                "icon_mode": mapped.get("mode"),
                                "original_name": summary,
                            }
                            if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in events):
                                events.append(ev)
                        except Exception:
                            pass
                        continue

                    sdt = dt_start.date()
                    edt = dt_end.date()
                    include_end = (dt_end.time() != datetime.min.time())
                    last_day = edt if include_end else (edt - timedelta(days=1))

                    try:
                        query_start_date = start_local_dt.date()
                    except Exception:
                        query_start_date = now_local().date()

                    day = max(sdt, query_start_date)
                    while day <= last_day:
                        date_str = day.strftime("%Y-%m-%d")
                        mapped = apply_event_mapping(summary)
                        if mapped.get("filtered_out"):
                            day += timedelta(days=1)
                            continue

                        time_str = dt_start.strftime("%H:%M") if day == sdt else ""

                        ev = {
                            "date": date_str,
                            "name": mapped.get("display_text") or "",
                            "display_text": mapped.get("display_text"),
                            "tag_text": mapped.get("tag_text"),
                            "tag_color_name": mapped.get("tag_color_name"),
                            "tag_color_rgb": mapped.get("tag_color_rgb"),
                            "time": time_str,
                            "icon": mapped.get("icon"),
                            "icon_size": mapped.get("icon_size"),
                            "icon_color_name": mapped.get("icon_color_name"),
                            "icon_color_rgb": mapped.get("icon_color_rgb"),
                            "icon_mode": mapped.get("mode"),
                            "original_name": summary,
                        }
                        if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in events):
                            events.append(ev)
                        day += timedelta(days=1)
    except Exception as ex:
        print("[fetch_google_calendar_events] exception:", ex)
    events.sort(key=lambda e: (e['date'], e.get('time', '')))
    return events


# --------------------------------------------------------------------
# Weather provider integration
# --------------------------------------------------------------------
try:
    from weather_provider import get_forecast_json, debug_print  # may raise
except Exception:
    def get_forecast_json(*args, **kwargs):
        return {}
    def debug_print(*args, **kwargs):
        pass


def fetch_weather_from_provider(lat=LAT, lon=LON, days=DEFAULT_DAYS):
    try:
        forecast = get_forecast_json(lat=lat, lon=lon, days=days, user_agent="InkyFrameCalendar/1.0 (contact: youremail@example.com)", keep_debug_hourly=True)
        weather_list = []
        for day in forecast.get("daily", []):
            weather_list.append({
                "date": day.get("date"),
                "condition": day.get("symbol"),
                "temp_max": day.get("temp_max"),
                "temp_min": day.get("temp_min"),
                "precip": day.get("precip"),
                "wind_max": day.get("wind_max"),
                "wind_dir_deg": day.get("wind_dir_deg"),
                "source": day.get("source")
            })
        hourly_today = forecast.get("hourly_today", [])
        return weather_list, hourly_today, forecast.get("meta", {})
    except Exception as ex:
        return [], [], {}


# --------------------------------------------------------------------
# Tag enrichment helpers (new) and initial_fetch_all wiring
# --------------------------------------------------------------------
def _color_from_mapping_entry(entry):
    """
    Try to return an (r,g,b) tuple from a mapping entry (dict), or None.
    """
    if not entry or not isinstance(entry, dict):
        return None
    for k in ("color_rgb", "tag_color_rgb", "icon_color_rgb"):
        if entry.get(k) is not None:
            try:
                v = entry.get(k)
                return (int(v[0]), int(v[1]), int(v[2]))
            except Exception:
                pass
    for k in ("color", "tag_color_name", "icon_color_name", "color_name"):
        if entry.get(k):
            try:
                rgb = ImageColor.getrgb(str(entry.get(k)))
                return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            except Exception:
                pass
    for k, v in entry.items():
        try:
            if str(k).lower().endswith("color") and v:
                rgb = ImageColor.getrgb(str(v))
                return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        except Exception:
            pass
    return None



def _split_tag_text_into_tokens(raw):
    """
    Heuristic splitting: commas first; else capitalized words.
    Returns list of token strings.
    """
    if not raw:
        return []
    s = str(raw).strip()
    # If comma-separated, use those
    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if parts:
            return parts
    # Collapse whitespace and return single token if short
    s_clean = re.sub(r"\s+", " ", s).strip()
    if len(s_clean) <= 30 and " " not in s_clean:
        return [s_clean]
    # Try to capture capitalized words (Norwegian chars included)
    caps = re.findall(r"\\b[A-ZÆØÅ][a-zæøåA-ZÆØÅ\\-']+\\b", s_clean)
    if caps:
        return caps
    # Fallback: split on spaces and punctuation
    parts = [p.strip() for p in re.split(r"[,;/\\-\\:]+|\\s+", s_clean) if p.strip()]
    return parts

def _ensure_rgb(rgb_like):
    """Return (r,g,b) tuple or None for a mapping-provided rgb-like value."""
    if not rgb_like:
        return None
    try:
        # Check if it's already a tuple/list of ints
        if isinstance(rgb_like, (list, tuple)) and len(rgb_like) == 3:
            return (int(rgb_like[0]), int(rgb_like[1]), int(rgb_like[2]))
        
        # Check if it's a string representation like "r,g,b"
        parts = str(rgb_like).split(",")
        if len(parts) == 3:
            return (int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None
    return None

def normalize_event(ev):
    """
    Normalize incoming event dict from any source into canonical shape.
    (FIX: Preserves capitalization in tag_text)
    """
    out = {}
    try:
        out['date'] = ev.get('date') or ev.get('dt') or None
        out['time'] = ev.get('time') or ev.get('start_time') or ev.get('time_str') or ""
        out['calendar'] = ev.get('calendar') or ev.get('source') or None
        out['all_day'] = bool(ev.get('all_day')) or (out['time'] == "")

        original = ev.get('original_name') or ev.get('name') or ev.get('summary') or ""
        display_text = ev.get('display_text') if ev.get('display_text') is not None else ev.get('name')
        if display_text is None:
            display_text = original

        out['original_name'] = original
        out['display_text'] = str(display_text).strip() if display_text is not None else ""
        out['name'] = out['display_text']

        raw_tag = ev.get('tag_text') or ev.get('tag') or ev.get('tags_text') or ""
        if raw_tag:
            t = re.sub(r"\s+", " ", str(raw_tag).strip())
            # FIX: Removed .lower() to preserve capitalization
            t_clean = t
            out['tag_text'] = t_clean
        else:
            out['tag_text'] = ""

        out['tag_color_name'] = ev.get('tag_color_name') or ev.get('color') or ev.get('tag_color') or None
        rgb = ev.get('tag_color_rgb') or ev.get('color_rgb') or ev.get('icon_color_rgb')
        out['tag_color_rgb'] = _ensure_rgb(rgb)

        out['icon'] = ev.get('icon')
        out['icon_size'] = ev.get('icon_size') or ev.get('size_px') or None
        out['icon_color_name'] = ev.get('icon_color_name') or ev.get('icon_color') or None
        out['icon_color_rgb'] = _ensure_rgb(ev.get('icon_color_rgb') or ev.get('icon_color'))

        out['icon_mode'] = ev.get('icon_mode') or ev.get('mode') or None

        tags = []
        for t in ev.get('tags') or ev.get('structured_tags') or []:
            try:
                if isinstance(t, dict) and t.get('text'):
                    entry = {'text': str(t.get('text')).strip()}
                    if t.get('color_rgb'):
                        entry['color_rgb'] = _ensure_rgb(t.get('color_rgb'))
                    elif t.get('color_name'):
                        entry['color_name'] = t.get('color_name')
                    tags.append(entry)
            except Exception:
                pass
        out['tags'] = tags

        out['_raw'] = ev

    except Exception:
        out = {
            'date': ev.get('date'),
            'time': ev.get('time') or "",
            'name': ev.get('name') or ev.get('original_name') or "",
            'display_text': ev.get('display_text') or ev.get('name') or "",
            'original_name': ev.get('original_name') or ev.get('name') or "",
            'tag_text': ev.get('tag_text') or "",
            'tag_color_name': ev.get('tag_color_name'),
            'tag_color_rgb': None,
            'icon': ev.get('icon'),
            'icon_size': ev.get('icon_size'),
            'icon_color_name': ev.get('icon_color_name'),
            'icon_color_rgb': None,
            'icon_mode': ev.get('icon_mode'),
            'calendar': ev.get('calendar'),
            'all_day': bool(ev.get('all_day')),
            'tags': ev.get('tags') or []
        }
        out['_raw'] = ev
    return out

# --- Retaining complex _build_lookup_from_EVENT_MAPPINGS as it is a dependency for enrich_events_with_tags ---
def _build_lookup_from_EVENT_MAPPINGS(event_mappings_obj):
    """
    Convert EVENT_MAPPINGS (list or dict) -> simple lookup dict by common keys.

    Make the lookup tolerant: register several normalized variants for each keyword
    so matching works regardless of case and trailing ':' punctuation produced by
    different calendar sources.
    """
    lookup = {}
    if not event_mappings_obj:
        return lookup
    try:
        def _variants_for_key(k):
            k = str(k).strip()
            if not k:
                return []
            # normalize internal whitespace
            k_norm = re.sub(r"\s+", " ", k).strip()
            variants = set()
            variants.add(k_norm)
            variants.add(k_norm.lower())
            variants.add(k_norm.rstrip(":"))
            variants.add(k_norm.rstrip(":").lower())
            variants.add(k_norm.capitalize())
            variants.add(k_norm.title())
            # also add versions without diacritics? (optional)
            # dedupe
            seen = set()
            out = []
            for v in variants:
                if v and v not in seen:
                    seen.add(v)
                    out.append(v)
            return out

        if isinstance(event_mappings_obj, dict):
            for k, v in event_mappings_obj.items():
                for cand in _variants_for_key(k):
                    lookup[cand] = v
                # also register common alternative fields inside the mapping dict
                if isinstance(v, dict):
                    for candidate_field in ("replacement", "token", "keyword", "name"):
                        val = v.get(candidate_field)
                        if val:
                            for cand in _variants_for_key(val):
                                lookup[cand] = v
        elif isinstance(event_mappings_obj, (list, tuple)):
            for v in event_mappings_obj:
                if not isinstance(v, dict):
                    continue
                # register the explicit keyword-like fields from each row
                for candidate_field in ("keyword", "token", "replacement", "name"):
                    val = v.get(candidate_field)
                    if val:
                        for cand in _variants_for_key(val):
                            lookup[cand] = v
                # as a fallback, if the mapping row uses plain keys, try 'keyword' spelled differently
                # (some versions of the mapping sheet may use slightly different names)
                for alt in ("key", "kw"):
                    val = v.get(alt)
                    if val:
                        for cand in _variants_for_key(val):
                            lookup[cand] = v
    except Exception:
        # be defensive: if anything goes wrong, return what we built so far
        pass
    return lookup


# --- Keeping original enrich_events_with_tags as requested ---
def enrich_events_with_tags(events, EVENT_MAPPINGS=None, prefer_mapping_module=True):
    """
    Enrich events with ev['tags'] = [{'text':..., 'color_rgb':(r,g,b)}] where possible.

    This version is tolerant about token matching:
      - tries lowercased and punctuation-stripped variants (e.g. "Fridag:", "fridag", "fridag:")
      - tries mapping_func with normalized variants
      - optional debug with env var DEBUG_TAG_MATCH=1 to print tried variants
    """
    import importlib
    import os
    mapping_func = None
    try:
        m = importlib.import_module("mappings")
        if hasattr(m, "apply_event_mapping") and callable(getattr(m, "apply_event_mapping")):
            mapping_func = getattr(m, "apply_event_mapping")
    except Exception:
        mapping_func = None

    lookup = {}
    if EVENT_MAPPINGS:
        lookup = _build_lookup_from_EVENT_MAPPINGS(EVENT_MAPPINGS)

    DEBUG = os.environ.get("DEBUG_TAG_MATCH") == "1"

    def _variants_for_token(p):
        """Return a list of normalized variants to try for token p."""
        if p is None:
            return []
        s = str(p).strip()
        # collapse whitespace
        s = re.sub(r"\s+", " ", s)
        variants = []
        # original trimmed
        variants.append(s)
        # without trailing colons
        variants.append(s.rstrip(":"))
        # lower variants
        variants.append(s.lower())
        variants.append(s.rstrip(":").lower())
        # also capitalized and title (helps for lookup that might have Title case)
        variants.append(s.capitalize())
        variants.append(s.title())
        # dedupe preserving order
        seen = set()
        out = []
        for v in variants:
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        return out

    def _find_entry_for_token(p):
        """Try lookup and mapping_func with tolerant variants. Return mapping entry or None."""
        variants = _variants_for_token(p)
        if DEBUG:
            print("[TAGDEBUG] token:", repr(p), "variants:", variants)
        # try lookup dictionary first
        for v in variants:
            entry = lookup.get(v)
            if entry:
                if DEBUG:
                    print("[TAGDEBUG] lookup hit:", v)
                return entry
        # try mapping_func on variants
        if mapping_func:
            for v in variants:
                try:
                    info = mapping_func(v)
                    if isinstance(info, dict) and info:
                        if DEBUG:
                            print("[TAGDEBUG] mapping_func hit:", v, "->", info)
                        return info
                except Exception:
                    pass
        # try a contains-style match: if any lookup key is substring of token or vice-versa
        for k in list(lookup.keys()):
            try:
                if k and p and (k in p or p in k):
                    if DEBUG:
                        print("[TAGDEBUG] contains heuristic hit:", k, "for token", p)
                    return lookup.get(k)
            except Exception:
                pass
        return None

    enriched = []
    for ev in events:
        ev_copy = dict(ev)

        # 1) If ev already has structured tags, normalize them and keep
        if ev_copy.get("tags"):
            try:
                norm = []
                for t in ev_copy.get("tags"):
                    if not isinstance(t, dict):
                        continue
                    te = {"text": str(t.get("text") or "").strip()}
                    if t.get("color_rgb") is not None:
                        try:
                            te["color_rgb"] = _ensure_rgb(t["color_rgb"])
                        except Exception:
                            pass
                    elif t.get("color_name"):
                        try:
                            rgb = ImageColor.getrgb(str(t.get("color_name")))
                            te["color_rgb"] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
                        except Exception:
                            pass
                    norm.append(te)
                if norm:
                    ev_copy["tags"] = norm
                enriched.append(ev_copy)
                continue
            except Exception:
                pass

        # 2) Try mapping_func for full summary first (may return structured tags)
        try:
            if mapping_func and prefer_mapping_module:
                mapped = mapping_func(ev_copy.get("name") or ev_copy.get("display_text") or "")
                if isinstance(mapped, dict) and mapped.get("tags"):
                    out_tags = []
                    for t in mapped.get("tags"):
                        if not isinstance(t, dict):
                            continue
                        te = {"text": str(t.get("text") or "").strip()}
                        if t.get("color_rgb") is not None:
                            try:
                                te["color_rgb"] = _ensure_rgb(t["color_rgb"])
                            except Exception:
                                pass
                        elif t.get("color_name"):
                            try:
                                rgb = ImageColor.getrgb(str(t.get("color_name")))
                                te["color_rgb"] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
                            except Exception:
                                pass
                        out_tags.append(te)
                    if out_tags:
                        ev_copy["tags"] = out_tags
                        enriched.append(ev_copy)
                        continue
        except Exception:
            pass

        # 3) If explicit tag_text exists, split by commas and honor legacy color if given
        raw = ev_copy.get("tag_text") or ev_copy.get("tag") or ""
        parts = _split_tag_text_into_tokens(raw)

        tags_out = []
        legacy_rgb = None
        legacy_name = ev_copy.get("tag_color_name")
        if ev_copy.get("tag_color_rgb") is not None:
            try:
                legacy_rgb = _ensure_rgb(ev_copy["tag_color_rgb"])
            except Exception:
                legacy_rgb = None

        if parts:
            for p in parts:
                if not p:
                    continue
                color_rgb = None
                # tolerant lookup via helper
                entry = _find_entry_for_token(p)
                if entry:
                    color_rgb = _color_from_mapping_entry(entry)
                # mapping_func on token as fallback
                if color_rgb is None and mapping_func:
                    try:
                        info = mapping_func(p)
                        if isinstance(info, dict):
                            color_rgb = _color_from_mapping_entry(info)
                            if color_rgb is None and info.get("tags"):
                                try:
                                    t0 = info.get("tags")[0]
                                    color_rgb = _color_from_mapping_entry(t0) or color_rgb
                                except Exception:
                                    pass
                    except Exception:
                        pass
                # final fallback legacy color
                if color_rgb is None and legacy_rgb is not None:
                    color_rgb = legacy_rgb
                elif color_rgb is None and legacy_name:
                    try:
                        color_rgb = ImageColor.getrgb(str(legacy_name))
                    except Exception:
                        color_rgb = None

                tag_entry = {"text": str(p).strip()}
                # propagate icon/mode from mapping entry if present (so renderer can draw icons)
                try:
                    if entry and isinstance(entry, dict):
                        icon_name = entry.get("icon") or entry.get("icon_name") or entry.get("icon_id")
                        if icon_name:
                            tag_entry["icon"] = icon_name
                        m = entry.get("mode") or entry.get("action") or entry.get("icon_mode")
                        if m:
                            tag_entry["mode"] = m
                except Exception:
                    pass
                if color_rgb is not None:
                    try:
                        tag_entry["color_rgb"] = _ensure_rgb(color_rgb)
                    except Exception:
                        pass
                tags_out.append(tag_entry)
            if tags_out:
                ev_copy["tags"] = tags_out
                enriched.append(ev_copy)
                continue

        # 4) CONSERVATIVE FALLBACK: scan tokens in name but only accept them
        name_source = ev_copy.get("name") or ev_copy.get("original_name") or ""
        tokens = [t.strip() for t in re.split(r"[,\s\-\:]+", str(name_source)) if t.strip()]
        found = []
        for t in tokens:
            if not t:
                continue
            # only consider short tokens (avoid long fragments)
            if len(t) > 30 or len(t) < 2:
                continue
            # try tolerant lookup
            entry = None
            for candidate in _variants_for_token(t):
                entry = lookup.get(candidate) or lookup.get(candidate.lower())
                if entry:
                    break
            color_rgb = None
            if entry:
                color_rgb = _color_from_mapping_entry(entry)
            # else ask mapping_func for the token (if available)
            if color_rgb is None and mapping_func:
                try:
                    for candidate in _variants_for_token(t):
                        info = mapping_func(candidate)
                        if isinstance(info, dict):
                            color_rgb = _color_from_mapping_entry(info)
                            if color_rgb is None and info.get("tags"):
                                try:
                                    t0 = info.get("tags")[0]
                                    color_rgb = _color_from_mapping_entry(t0) or color_rgb
                                except Exception:
                                    pass
                            # accept only if mapping suggests it is a tag/replacement
                            if (info.get("replacement") or info.get("mode") or info.get("tags") or info.get("color") or info.get("color_rgb")):
                                break
                            else:
                                color_rgb = None
                except Exception:
                    pass
            if color_rgb is not None:
                found.append((t, color_rgb))

        if found:
            out_tags = ev_copy.get("tags") or []
            for t, c in found:
                te = {"text": str(t)}
                try:
                    te["color_rgb"] = _ensure_rgb(c)
                except Exception:
                    pass
                # try to attach icon/mode from mapping lookup for this token
                try:
                    entry_for_t = _find_entry_for_token(t)
                    if entry_for_t and isinstance(entry_for_t, dict):
                        icon_name = entry_for_t.get("icon") or entry_for_t.get("icon_name")
                        if icon_name:
                            te["icon"] = icon_name
                        mode_name = entry_for_t.get("mode")
                        if mode_name:
                            te["mode"] = mode_name
                except Exception:
                    pass
                out_tags.append(te)
            ev_copy["tags"] = out_tags

        enriched.append(ev_copy)

    return enriched



# --------------------------------------------------------------------
# initial_fetch_all (wired to call enrichment)
# --------------------------------------------------------------------
def initial_fetch_all(days=DEFAULT_DAYS, session=None, gatenavn=None, husnr=None):
    import json
    import os
    from datetime import datetime

    s = session or requests.Session()
    try:
        # fetch initial data
        fractions = fetch_fraction_names(session=s)
        tomme = fetch_tommekalender_events(fractions, days=days, session=s, gatenavn=gatenavn, husnr=husnr)
        gcal = fetch_google_calendar_events(days=days, session=s)

        
        # fetch public holidays (Norway calendar by default)
        holidays = []
        try:
            holidays = fetch_google_holiday_events(calendar_id=HOLIDAYS_CALENDAR_ID, days=days, session=s)
        except Exception:
            holidays = []
# fetch weather: (weather, hourly, meta) expected from your provider function
        weather, hourly, meta = fetch_weather_from_provider(lat=LAT, lon=LON, days=days)

        # --- Ensure hourly entries include 'condition' and 'precip' for renderer ---
        try:
            # Normalize keys and fill missing fields so renderer can map icons
            hourly = hourly or []
            for h in hourly:
                # ensure precip is present (many providers use precip_mm or precipitation)
                if h.get("precip") is None:
                    if h.get("precip_mm") is not None:
                        h["precip"] = h.get("precip_mm")
                    elif h.get("precipitation") is not None:
                        h["precip"] = h.get("precipitation")
                    else:
                        h["precip"] = 0.0

                # ensure temperature field is normalized
                if h.get("temp") is None:
                    if h.get("temperature") is not None:
                        h["temp"] = h.get("temperature")
                    elif h.get("air_temperature") is not None:
                        h["temp"] = h.get("air_temperature")

                # ensure there's a condition string; try matching daily summary first
                if not h.get("condition"):
                    # try find the day summary for this hour (match by date prefix YYYY-MM-DD)
                    t = h.get("time") or h.get("dt") or h.get("datetime")
                    date_str = None
                    if isinstance(t, str) and len(t) >= 10:
                        date_str = t[:10]
                    elif isinstance(t, (int, float)):
                        # if time is hour index or epoch, we don't try to match day summary
                        date_str = None

                    day_entry = None
                    if date_str and weather:
                        for d in weather:
                            if d.get("date") == date_str:
                                day_entry = d
                                break
                    if day_entry and (day_entry.get("condition") or day_entry.get("symbol")):
                        # prefer daily textual condition if available
                        h["condition"] = day_entry.get("condition") or day_entry.get("symbol")
                    else:
                        # fallback heuristic: if temp exists and <= 0 -> 'Skyet' (or 'Snø' if heavy precip)
                        tval = h.get("temp")
                        pval = h.get("precip", 0.0) or 0.0
                        if pval >= 2.5:
                            # heavy precip — guess rain or snow depending on temp
                            h["condition"] = "Regn" if (tval is None or tval > 1.5) else "Snø"
                        else:
                            if tval is None:
                                h["condition"] = "Skyet"
                            else:
                                # use a slightly more descriptive guess
                                if tval <= -1.5:
                                    h["condition"] = "Skyet"
                                elif tval <= 0.5:
                                    h["condition"] = "Delvis skyet"
                                else:
                                    h["condition"] = "Klarvær"
        except Exception:
            # don't break the whole fetch if something odd happens here
            pass

        # merge events (tommekalender + gcal)
        events = []
        # merge events (tommekalender + gcal + holidays) - normalize everything first
        events = []
        for raw in (gcal or []) + (tomme or []) + (holidays or []):
            ne = normalize_event(raw)
            key_exists = any(
                (x.get('date') == ne.get('date') and x.get('name') == ne.get('name') and x.get('time', '') == ne.get('time',''))
                for x in events
            )
            if not key_exists:
                events.append(ne)
        events.sort(key=lambda e: (e.get('date') or "", e.get('time') or ""))

        
        
        # ---- ENRICH events with structured tags (so renderer can color per-tag) ----
        try:
            # Prefer EVENT_MAPPINGS exported from mappings module if available.
            em = None
            try:
                # import mappings module explicitly and read its EVENT_MAPPINGS
                import mappings as _m
                em = getattr(_m, "EVENT_MAPPINGS", None)
                # If EVENT_MAPPINGS is empty, optionally call a reload helper if provided (useful in dev)
                if (em is None or (isinstance(em, (list, tuple)) and len(em) == 0)) and hasattr(_m, "reload_event_mappings"):
                    try:
                        _m.reload_event_mappings(force_refresh=False)
                        em = getattr(_m, "EVENT_MAPPINGS", None)
                    except Exception:
                        pass
            except Exception:
                # fallback to any global EVENT_MAPPINGS
                em = globals().get("EVENT_MAPPINGS")

            # final fallback to global var if still None
            if em is None:
                em = globals().get("EVENT_MAPPINGS")

            events = enrich_events_with_tags(events, EVENT_MAPPINGS=em, prefer_mapping_module=True)
        except Exception:
            # fail gracefully: keep original events
            pass

        # renderer-safe fallback: ensure name exists (in case mapping removed it)
        try:
            for ev in events:
                if not ev.get("name") and ev.get("display_text"):
                    ev["name"] = ev["display_text"]
        except Exception:
            pass
# DEBUG: dump first weather entry for debugging and produce hourly preview + period picks
        try:
            if weather:
                print("[DEBUG weather sample] first weather entry:", weather[0])
            else:
                print("[DEBUG weather sample] weather list empty")
            print("[DEBUG hourly_today sample] len:", len(hourly))
        except Exception:
            print("[DEBUG] failed to print weather debug")

            # compact preview of first 24 entries
            try:
                print("[DEBUG hourly entries preview] (index, time, cond, temp, precip)")
                for i, h in enumerate((hourly or [])[:24]):
                    t = h.get("time") or h.get("dt") or h.get("datetime") or h.get("hour") or "<no-time>"
                    cond = h.get("condition") or h.get("symbol") or h.get("weather") or ""
                    temp = h.get("temp") or h.get("temperature") or None
                    precip = h.get("precip") if h.get("precip") is not None else h.get("precip_mm", None)
                    print(f"  {i:02d}: {t} | {cond!r:30} | temp={str(temp):>6} | precip={str(precip)}")
            except Exception as ex:
                print("[DEBUG] failed to print hourly summary:", ex)

            # quick representative selection check (simple heuristics)
            try:
                def _norm_cond_key(cond):
                    if not cond:
                        return "cloud"
                    c = str(cond).lower()
                    if "rain" in c or "regn" in c or "byge" in c:
                        return "rain"
                    if "snow" in c or "snø" in c:
                        return "snow"
                    if "sun" in c or "klar" in c:
                        return "sun"
                    if "thun" in c or "lyn" in c:
                        return "thunder"
                    if "fog" in c or "tåke" in c:
                        return "fog"
                    if "cloud" in c or "sky" in c or "skyet" in c:
                        return "cloud"
                    return "cloud"

                def _choose_for_period(hours):
                    if not hours:
                        return None
                    rank = {"sun":0, "cloud":1, "rain":2, "snow":3, "thunder":4}
                    best = None
                    best_rank = -1
                    for hh in hours:
                        key = _norm_cond_key(hh.get("condition") or hh.get("symbol") or hh.get("weather"))
                        r = rank.get(key, 1)
                        precip = hh.get("precip") or hh.get("precip_mm") or 0.0
                        if best is None or (r > best_rank) or (r == best_rank and (precip or 0) > (best.get("precip") or 0)):
                            best_rank = r
                            best = {"hour": hh, "key": key, "precip": precip}
                    return best

                # naive split by hour-of-day; fallback to index-based distribution if no proper time field
                periods = {"morning":[], "lunch":[], "day":[], "evening":[]}
                for idx, hh in enumerate(hourly or []):
                    t = hh.get("time")
                    hour = None
                    if isinstance(t, str):
                        try:
                            hour = int(datetime.fromisoformat(t.replace("Z", "+00:00")).hour)
                        except Exception:
                            hour = None
                    elif isinstance(t, (int, float)):
                        try:
                            hour = int(t)
                        except Exception:
                            hour = None
                    if hour is None:
                        # distribute by index along 24h
                        pos = idx % 24
                        hour = pos

                    if 6 <= hour <= 10:
                        periods["morning"].append(hh)
                    elif 11 <= hour <= 13:
                        periods["lunch"].append(hh)
                    elif 14 <= hour <= 17:
                        periods["day"].append(hh)
                    else:
                        periods["evening"].append(hh)

                for name in ("morning","lunch","day","evening"):
                    rep = _choose_for_period(periods[name])
                    if rep:
                        hh = rep["hour"]
                        t = hh.get("time") or hh.get("dt") or "<no-time>"
                        print(f"[DEBUG chosen] {name:7} -> {t} {rep['key']} precip={rep['precip']}")
                    else:
                        print(f"[DEBUG chosen] {name:7} -> <no data>")
            except Exception as ex:
                print("[DEBUG] rep selection failed:", ex)

        except Exception as ex:
            print("[DEBUG] hourly debug block failed:", ex)

        return {"events": events, "weather": weather, "hourly_today": hourly, "meta": meta}

    finally:
        if session is None:
            s.close()


# --------------------------------------------------------------------
# debug main
# --------------------------------------------------------------------
if __name__ == "__main__":
    out = initial_fetch_all(days=14)
    print("Events count:", len(out.get("events", [])))
    for e in out.get("events", [])[:100]:
        print(e)

    print("\nDetailed debug preview (first 40):")
    for e in out.get("events", [])[:40]:
        print("----")
        print("date:", e.get("date"))
        print("name:", e.get("name"))
        print("display_text:", repr(e.get("display_text")))
        print("tag_text:", repr(e.get("tag_text")))
        print("tag_color_name:", repr(e.get("tag_color_name")))
        print("tag_color_rgb:", repr(e.get("tag_color_rgb")))
        print("tags:", repr(e.get("tags")))
        print("icon:", repr(e.get("icon")))
        print("icon_color_name:", repr(e.get("icon_color_name")))
        print("icon_color_rgb:", repr(e.get("icon_color_rgb")))


def fetch_google_holiday_events(calendar_id=None, days=DEFAULT_DAYS, session=None):
    """
    Fetch public-holiday (all-day) events from a given Google Calendar ID.
    The summary is prefixed with "Fridag: " to trigger custom mapping logic.
    """
    import requests
    from datetime import datetime, timedelta

    session = session or requests.Session()
    cal_id = calendar_id or HOLIDAYS_CALENDAR_ID
    # ensure '#' is URL encoded for use in URL
    encoded_cal_id = cal_id.replace("#", "%23")

    today_local = now_local().date()
    if TZ:
        start_local_dt = datetime(year=today_local.year, month=today_local.month, day=today_local.day,
                                  hour=0, minute=0, second=0, microsecond=0, tzinfo=TZ)
    else:
        start_local_dt = datetime.combine(today_local, datetime.min.time())
    start_utc = _ensure_aware(start_local_dt)
    end_utc = start_utc + timedelta(days=days)

    def iso_z(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    timeMin = iso_z(start_utc)
    timeMax = iso_z(end_utc)
    url = (
        f"https://www.googleapis.com/calendar/v3/calendars/{encoded_cal_id}/events"
        f"?timeMin={timeMin}&timeMax={timeMax}&singleEvents=true&fields=items(summary,start,end)&orderBy=startTime&key={API_KEY_GOOGLE}"
    )

    holidays = []
    try:
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        items = data.get("items", [])
        # query_start_date used to skip past multi-day events that start earlier
        try:
            query_start_date = start_local_dt.date()
        except Exception:
            query_start_date = now_local().date()

        for it in items:
            summary = (it.get("summary") or "").strip()
            if not summary:
                continue

            # --- FIX: Prepend "Fridag: " to summary to trigger mapping logic ---
            holiday_summary = "Fridag: " + summary
            # --------------------------------------------------------------------

            start = it.get("start", {})
            end = it.get("end", {})

            # Prefer all-day date events; but if dateTime present, treat defensively.
            if "date" in start:
                sdate = start["date"]
                edate = end.get("date", sdate)
                try:
                    sdt = datetime.strptime(sdate, "%Y-%m-%d").date()
                    edt = datetime.strptime(edate, "%Y-%m-%d").date()
                except Exception:
                    sdt = None
                    edt = None

                # If parsing failed, include if not obviously out-of-range
                if sdt is None or edt is None:
                    date_str = sdate
                    try:
                        if datetime.strptime(date_str, "%Y-%m-%d").date() < query_start_date:
                            continue
                    except Exception:
                        pass

                    # Apply event mapping using the prepended summary
                    mapped = apply_event_mapping(holiday_summary)
                    if mapped.get("filtered_out"):
                        continue
                    ev = {
                        "date": date_str,
                        "name": mapped.get("display_text") or "",
                        "display_text": mapped.get("display_text"),
                        "tag_text": mapped.get("tag_text"),
                        "tag_color_name": mapped.get("tag_color_name"),
                        "tag_color_rgb": mapped.get("tag_color_rgb"),
                        "time": "",
                        "icon": mapped.get("icon"),
                        "icon_size": mapped.get("icon_size"),
                        "icon_color_name": mapped.get("icon_color_name"),
                        "icon_color_rgb": mapped.get("icon_color_rgb"),
                        "icon_mode": mapped.get("mode"),
                        "original_name": summary,
            "is_holiday": True,  # explicit holiday flag
                    }
                    if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in holidays):
                        holidays.append(ev)
                else:
                    # Google calendar all-day events use exclusive end date, so last_day = edt - 1
                    last_day = edt - timedelta(days=1)
                    day = max(sdt, query_start_date)
                    while day <= last_day:
                        date_str = day.strftime("%Y-%m-%d")

                        # Apply event mapping using the prepended summary
                        mapped = apply_event_mapping(holiday_summary)
                        if mapped.get("filtered_out"):
                            day += timedelta(days=1)
                            continue
                        ev = {
                            "date": date_str,
                            "name": mapped.get("display_text") or "",
                            "display_text": mapped.get("display_text"),
                            "tag_text": mapped.get("tag_text"),
                            "tag_color_name": mapped.get("tag_color_name"),
                            "tag_color_rgb": mapped.get("tag_color_rgb"),
                            "time": "",
                            "icon": mapped.get("icon"),
                            "icon_size": mapped.get("icon_size"),
                            "icon_color_name": mapped.get("icon_color_name"),
                            "icon_color_rgb": mapped.get("icon_color_rgb"),
                            "icon_mode": mapped.get("mode"),
                            "original_name": summary,
            "is_holiday": True,  # explicit holiday flag
                        }

                        if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in holidays):
                            holidays.append(ev)
                        day += timedelta(days=1)
            elif "dateTime" in start:
                # Uncommon for a holiday calendar, but handle gracefully:
                try:
                    dt_start = start.get("dateTime") or ""
                    date_str = dt_start[:10]
                except Exception:
                    date_str = None
                if date_str:
                    # Apply event mapping using the prepended summary
                    mapped = apply_event_mapping(holiday_summary)
                    if mapped.get("filtered_out"):
                        continue
                    ev = {
                        "date": date_str,
                        "name": mapped.get("display_text") or "",
                        "display_text": mapped.get("display_text"),
                        "tag_text": mapped.get("tag_text"),
                        "tag_color_name": mapped.get("tag_color_name"),
                        "tag_color_rgb": mapped.get("tag_color_rgb"),
                        "time": "",
                        "icon": mapped.get("icon"),
                        "icon_size": mapped.get("icon_size"),
                        "icon_color_name": mapped.get("icon_color_name"),
                        "icon_color_rgb": mapped.get("icon_color_rgb"),
                        "icon_mode": mapped.get("mode"),
                        "original_name": summary,
            "is_holiday": True,  # explicit holiday flag
                    }

                    if not any(e['date'] == ev['date'] and e['name'] == ev['name'] and e.get('time','') == ev['time'] for e in holidays):
                        holidays.append(ev)
        holidays.sort(key=lambda e: (e['date'], e.get('time', '')))
        return holidays
    except Exception as ex:
        print("[fetch_google_holiday_events] exception:", ex)
        return []
    
def initial_fetch_all(days=DEFAULT_DAYS, session=None, gatenavn=None, husnr=None):
    """ Master fetch function that combines all your logic """
    s = session or requests.Session()
    try:
        fractions = fetch_fraction_names(session=s)
        waste = fetch_tommekalender_events(fractions, days=days, session=s, gatenavn=gatenavn, husnr=husnr)
        gcal = fetch_google_calendar_events(days=days, session=s)
        
        # Merge all events
        all_events = gcal + waste
        all_events.sort(key=lambda e: (e['date'], e.get('time', '')))

        weather, hourly, meta = fetch_weather_from_provider(lat=LAT, lon=LON, days=days)
        
        return {
            "events": all_events,
            "weather": weather,
            "hourly_today": hourly,
            "meta": meta
        }
    finally:
        if session is None:
            s.close()