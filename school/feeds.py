"""
Copy events from public calendar feeds (ICS / webcal, e.g. a national team's
fixtures) into the family Google Calendar, with names appended to the title so
the tag mapping shows them as people tags ("Norge – Danmark Christian").

Config (SSM parameter CALENDAR_FEEDS), one feed per line:
    <url> | <name> [<name> ...]
    webcal://example.com/norway.ics | Christian

Each copied event carries private extended properties (source, feed, uid), so
re-syncing updates changed kick-off times, removes cancelled future events and
never duplicates. An event the family already put in the calendar themselves
(same day, same title) is not added again.
"""
import hashlib
import re
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

from school.calendar_sync import TZ, _check, _url, family_events
from school.extract import title_with_names

SOURCE = "weekcalendar-feed"
DEFAULT_DURATION = timedelta(hours=2)


# ------------------------------------------------------------------ config
def parse_feeds(spec):
    """'url | Christian\\nurl2' -> [(url, ['Christian']), (url2, [])]"""
    feeds = []
    for line in (spec or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        url, _, names = line.partition("|")
        url = url.strip()
        if url.lower().startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        if url:
            feeds.append((url, names.split()))
    return feeds


def feed_id(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------ ICS parsing
def _unfold(text):
    out = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _unescape(v):
    return (v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",")
             .replace("\\;", ";").replace("\\\\", "\\")).strip()


def _parse_dt(value, params):
    """ICS DTSTART/DTEND -> (aware datetime) or (date, all_day=True)."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])), True
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z)?", value)
    if not m:
        return None, False
    y, mo, d, h, mi, s, z = m.groups()
    dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    if z:
        dt = dt.replace(tzinfo=timezone.utc)
    elif params.get("TZID") and ZoneInfo is not None:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(params["TZID"]))
        except Exception:
            dt = dt.replace(tzinfo=ZoneInfo(TZ))
    elif ZoneInfo is not None:
        dt = dt.replace(tzinfo=ZoneInfo(TZ))
    return dt, False


def parse_ics(text):
    """Minimal VEVENT parser: [{uid, summary, start, end, all_day, location, description}]."""
    events, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
            continue
        if line == "END:VEVENT":
            if cur is not None and cur.get("start") is not None and cur.get("summary"):
                cur.setdefault("uid", f"{cur['summary']}@{cur['start']}")
                events.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        name, *rawp = head.split(";")
        params = dict(p.split("=", 1) for p in rawp if "=" in p)
        name = name.upper()
        if name == "UID":
            cur["uid"] = value.strip()
        elif name == "SUMMARY":
            cur["summary"] = _unescape(value)
        elif name == "LOCATION":
            cur["location"] = _unescape(value)
        elif name == "DESCRIPTION":
            cur["description"] = _unescape(value)
        elif name in ("DTSTART", "DTEND"):
            dt, all_day = _parse_dt(value, params)
            cur["start" if name == "DTSTART" else "end"] = dt
            if name == "DTSTART":
                cur["all_day"] = all_day
    return events


# ------------------------------------------------------------------ sync
def _norm(s):
    return re.sub(r"[^a-z0-9æøå]+", "", (s or "").lower())


def _event_body(ev, names, fid):
    body = {
        "summary": title_with_names(ev["summary"], names),
        "description": "\n".join(x for x in (ev.get("description"), "Fra kalenderabonnement") if x),
        "extendedProperties": {"private": {"source": SOURCE, "feed": fid, "uid": ev["uid"][:900]}},
        "transparency": "transparent",
    }
    if ev.get("location"):
        body["location"] = ev["location"]
    if ev.get("all_day"):
        end = ev.get("end") if isinstance(ev.get("end"), date) and not isinstance(ev.get("end"), datetime) \
            else ev["start"] + timedelta(days=1)
        body["start"] = {"date": ev["start"].isoformat()}
        body["end"] = {"date": end.isoformat()}
    else:
        end = ev.get("end") if isinstance(ev.get("end"), datetime) else ev["start"] + DEFAULT_DURATION
        body["start"] = {"dateTime": ev["start"].isoformat(), "timeZone": TZ}
        body["end"] = {"dateTime": end.isoformat(), "timeZone": TZ}
    return body


def _same_time(a, b):
    def key(x):
        if x.get("date"):
            return x["date"]
        try:
            return datetime.fromisoformat(x["dateTime"].replace("Z", "+00:00")).timestamp()
        except Exception:
            return x.get("dateTime")
    return key(a) == key(b)


def _ours(session, calendar_id, fid, since):
    params = {"privateExtendedProperty": [f"source={SOURCE}", f"feed={fid}"],
              "timeMin": f"{since.isoformat()}T00:00:00Z", "singleEvents": "true", "maxResults": 2500}
    return _check(session.get(_url(calendar_id), params=params), "lesing").json().get("items", [])


def sync_feed(session, calendar_id, ics_text, names, fid, today, days_ahead=365):
    """Returns dict with created/updated/deleted/skipped counts."""
    window_end = today + timedelta(days=days_ahead)
    wanted = []
    for ev in parse_ics(ics_text):
        d = ev["start"] if ev.get("all_day") else ev["start"].astimezone(ZoneInfo(TZ)).date() \
            if ZoneInfo else ev["start"].date()
        if today <= d <= window_end:
            ev["_date"] = d
            wanted.append(ev)

    existing = {(e.get("extendedProperties") or {}).get("private", {}).get("uid"): e
                for e in _ours(session, calendar_id, fid, today)}
    manual = {}
    for d, _t, title in family_events(session, calendar_id, today, window_end):
        manual.setdefault(d, []).append(_norm(title))

    stats = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0}
    seen = set()
    for ev in wanted:
        uid = ev["uid"][:900]
        seen.add(uid)
        body = _event_body(ev, names, fid)
        old = existing.get(uid)
        if old:
            if (old.get("summary") != body["summary"] or not _same_time(old.get("start", {}), body["start"])
                    or not _same_time(old.get("end", {}), body["end"])):
                _check(session.patch(_url(calendar_id, "/" + old["id"]),
                                     json={k: body[k] for k in ("summary", "start", "end", "description")}),
                       "oppdatering")
                stats["updated"] += 1
            continue
        title = _norm(ev["summary"])
        if any(title and (title in t or t in title) for t in manual.get(ev["_date"], []) if len(t) >= 4):
            stats["skipped"] += 1     # the family already has it in the calendar
            continue
        _check(session.post(_url(calendar_id), json=body), "oppretting")
        stats["created"] += 1

    now = datetime.now(timezone.utc)
    for uid, old in existing.items():
        if uid in seen:
            continue
        st = old.get("start", {})
        try:
            start = datetime.fromisoformat(st["dateTime"].replace("Z", "+00:00")) if st.get("dateTime") \
                else datetime.fromisoformat(st["date"] + "T23:59:59+00:00")
        except Exception:
            continue
        if start > now:   # cancelled / moved out of the feed
            resp = session.delete(_url(calendar_id, "/" + old["id"]))
            if resp.status_code not in (200, 204, 404, 410):
                _check(resp, "sletting")
            stats["deleted"] += 1
    return stats
