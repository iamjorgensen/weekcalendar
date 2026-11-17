"""
Small extra data for the frame (stdlib only, every function is best effort):

  countdowns()  - calendar events marked with ⏳ in the title, up to a year ahead
  first_snow()  - True on the first day this season the forecast shows snow
  aurora_kp()   - NOAA's planetary K-index forecast for tonight (northern lights)
"""
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

MARKER = "⏳"
SEASON_KEY = "cache/season.json"
NOAA_KP = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
UA = {"User-Agent": "weekcalendar/1.0 (e-ink family calendar)"}


def _get_json(url, timeout=8):
    req = urllib.request.Request(url, headers=dict(UA, Accept="application/json"))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def countdowns(api_key, calendar_id, today, days=365):
    """[{date, title}] for events with ⏳ in the title (the marker is removed from the title)."""
    if not api_key or not calendar_id:
        return []
    q = urllib.parse.urlencode({"q": MARKER, "singleEvents": "true", "orderBy": "startTime", "maxResults": "20",
                                "timeMin": f"{today.isoformat()}T00:00:00Z",
                                "timeMax": f"{(today + timedelta(days=days)).isoformat()}T00:00:00Z",
                                "fields": "items(summary,start)", "key": api_key})
    url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(calendar_id, safe='')}/events?{q}"
    out = []
    for it in (_get_json(url) or {}).get("items") or []:
        title = str(it.get("summary") or "")
        if MARKER not in title:
            continue
        st = it.get("start") or {}
        d = st.get("date") or (st.get("dateTime") or "")[:10]
        try:
            d = date.fromisoformat(d)
        except ValueError:
            continue
        clean = " ".join(title.replace(MARKER, " ").replace("️", " ").split())
        if clean and d > today:
            out.append({"date": d.isoformat(), "title": clean[:30]})
    return out


def season(d):
    return d.year if d.month >= 7 else d.year - 1


def is_snow(symbol):
    s = str(symbol or "").lower()
    return "snø" in s or "snow" in s


def first_snow(s3, bucket, today, today_symbol):
    """True on the first day of the season (Jul-Jun) with snow in the forecast; remembered in S3."""
    try:
        state = json.loads(s3.get_object(Bucket=bucket, Key=SEASON_KEY)["Body"].read())
    except Exception:
        state = {}
    if state.get("season") != season(today):
        state = {"season": season(today)}
    if state.get("first_snow"):
        return state["first_snow"] == today.isoformat()
    if not is_snow(today_symbol):
        return False
    state["first_snow"] = today.isoformat()
    s3.put_object(Bucket=bucket, Key=SEASON_KEY, Body=json.dumps(state).encode("utf-8"),
                  ContentType="application/json")
    return True


def parse_kp(rows, tonight_from, tonight_to):
    """Highest forecast Kp between the two UTC datetimes. Accepts NOAA's list-of-lists or list-of-dicts."""
    best = None
    for row in rows or []:
        if isinstance(row, dict):
            t, kp = row.get("time_tag"), row.get("kp")
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            t, kp = row[0], row[1]
        else:
            continue
        try:
            when = datetime.fromisoformat(str(t).replace(" ", "T").replace("Z", "")).replace(tzinfo=timezone.utc)
            kp = float(kp)
        except (TypeError, ValueError):
            continue          # header row
        if tonight_from <= when <= tonight_to:
            best = kp if best is None else max(best, kp)
    return best


def aurora_kp(today):
    """Max Kp forecast for tonight (18-03 Norwegian time, roughly 17-02 UTC), or None."""
    start = datetime(today.year, today.month, today.day, 17, tzinfo=timezone.utc)
    return parse_kp(_get_json(NOAA_KP), start, start + timedelta(hours=9))
