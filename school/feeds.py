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
    """
    One feed per line: '<url> | <names> | <icon>' (names and icon optional).
    Returns [(url, ['Christian'], 'soccer'), ...]. FotMob feeds default to the 'soccer' icon.
    """
    feeds = []
    for line in (spec or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        url = parts[0]
        names = parts[1].split() if len(parts) > 1 else []
        icon = parts[2] if len(parts) > 2 and parts[2] else ("soccer" if "fotmob.com" in url else "")
        if url.lower().startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        if url:
            feeds.append((url, names, icon))
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


# English country names in sports feeds -> Norwegian
COUNTRIES = {
    "Norway": "Norge", "Denmark": "Danmark", "Sweden": "Sverige", "Finland": "Finland", "Iceland": "Island",
    "Italy": "Italia", "Spain": "Spania", "Germany": "Tyskland", "France": "Frankrike", "England": "England",
    "Scotland": "Skottland", "Wales": "Wales", "Northern Ireland": "Nord-Irland", "Ireland": "Irland",
    "Netherlands": "Nederland", "Belgium": "Belgia", "Switzerland": "Sveits", "Austria": "Østerrike",
    "Poland": "Polen", "Czechia": "Tsjekkia", "Czech Republic": "Tsjekkia", "Slovakia": "Slovakia",
    "Hungary": "Ungarn", "Croatia": "Kroatia", "Serbia": "Serbia", "Slovenia": "Slovenia", "Greece": "Hellas",
    "Turkey": "Tyrkia", "Türkiye": "Tyrkia", "Portugal": "Portugal", "Romania": "Romania", "Ukraine": "Ukraina",
    "Russia": "Russland", "Estonia": "Estland", "Latvia": "Latvia", "Lithuania": "Litauen", "Moldova": "Moldova",
    "Israel": "Israel", "Cyprus": "Kypros", "Georgia": "Georgia", "Armenia": "Armenia", "Albania": "Albania",
    "Kosovo": "Kosovo", "North Macedonia": "Nord-Makedonia", "Montenegro": "Montenegro", "Bosnia and Herzegovina":
    "Bosnia-Hercegovina", "Luxembourg": "Luxembourg", "Faroe Islands": "Færøyene", "Malta": "Malta",
    "USA": "USA", "United States": "USA", "Canada": "Canada", "Mexico": "Mexico", "Brazil": "Brasil",
    "Argentina": "Argentina", "Japan": "Japan", "South Korea": "Sør-Korea", "Morocco": "Marokko",
    "Egypt": "Egypt", "Australia": "Australia",
}
_COUNTRY_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, COUNTRIES), key=len, reverse=True)) + r")\b")


def clean_title(text):
    """Drop emoji / flags (no glyphs on the e-ink fonts), translate country names, tidy spaces."""
    out = []
    for ch in text or "":
        o = ord(ch)
        if o > 0xFFFF or 0x2600 <= o <= 0x27BF or 0xFE00 <= o <= 0xFE0F or o == 0x200D:
            continue
        out.append(ch)
    t = _COUNTRY_RE.sub(lambda m: COUNTRIES[m.group(1)], "".join(out))
    t = re.sub(r"\s+-\s+", " – ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def parse_ics(text):
    """Minimal VEVENT parser: [{uid, summary, start, end, all_day, location, description}].
    Properties of nested components (e.g. VALARM reminders) are ignored."""
    events, cur, nested = [], None, 0
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur, nested = {}, 0
            continue
        if cur is not None and line.startswith("BEGIN:"):
            nested += 1
            continue
        if cur is not None and line.startswith("END:") and line != "END:VEVENT":
            nested = max(0, nested - 1)
            continue
        if nested:
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
        elif name == "STATUS":
            cur["status"] = value.strip().upper()
        elif name in ("DTSTART", "DTEND"):
            dt, all_day = _parse_dt(value, params)
            cur["start" if name == "DTSTART" else "end"] = dt
            if name == "DTSTART":
                cur["all_day"] = all_day
    return events


# ------------------------------------------------------------------ sync
def _norm(s):
    return re.sub(r"[^a-z0-9æøå]+", "", (s or "").lower())


def _event_body(ev, names, fid, icon=""):
    body = {
        "summary": title_with_names(clean_title(ev["summary"]), names),
        "description": "\n".join(x for x in (ev.get("description"), "Fra kalenderabonnement") if x),
        "extendedProperties": {"private": {"source": SOURCE, "feed": fid, "uid": ev["uid"][:900],
                                           **({"icon": icon} if icon else {})}},
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


def sync_feed(session, calendar_id, ics_text, names, fid, today, days_ahead=365, icon=""):
    """ICS text -> family calendar. Returns dict with created/updated/deleted/skipped counts."""
    return sync_events(session, calendar_id, parse_ics(ics_text), names, fid, today, days_ahead, icon)


def sync_events(session, calendar_id, events, names, fid, today, days_ahead=365, icon=""):
    """
    Parsed events ({uid, summary, start, end, all_day, location, description, status}) ->
    family calendar, scoped to `fid`. Events missing from the list (or CANCELLED) are
    deleted if they are still in the future.
    """
    window_end = today + timedelta(days=days_ahead)
    wanted = []
    for ev in events:
        if ev.get("status") == "CANCELLED":
            continue     # cancelled: not wanted, so an existing copy is deleted below
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
        body = _event_body(ev, names, fid, icon)
        old = existing.get(uid)
        if old:
            old_icon = ((old.get("extendedProperties") or {}).get("private") or {}).get("icon", "")
            if (old.get("summary") != body["summary"] or not _same_time(old.get("start", {}), body["start"])
                    or not _same_time(old.get("end", {}), body["end"]) or old_icon != (icon or "")):
                _check(session.patch(_url(calendar_id, "/" + old["id"]),
                                     json={k: body[k] for k in ("summary", "start", "end", "description",
                                                                "extendedProperties")}),
                       "oppdatering")
                stats["updated"] += 1
            continue
        title = _norm(clean_title(ev["summary"]))
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


# ------------------------------------------------------------------ clean-up
def _mentions(ev, marker):
    org = ev.get("organizer") or {}
    creator = ev.get("creator") or {}
    hay = " ".join(str(x) for x in (ev.get("description"), ev.get("location"), ev.get("iCalUID"),
                                    org.get("email"), org.get("displayName"), creator.get("email"),
                                    (ev.get("source") or {}).get("url"))).lower()
    return marker in hay


def find_foreign(session, calendar_id, start, end, marker="spond"):
    """
    Events in the family calendar that some other tool put there (e.g. Spond's own
    calendar sync) and that mention `marker`. Events this tool wrote are never included.
    Returns [{id, summary, start}] sorted by start.
    """
    params = {"timeMin": f"{start.isoformat()}T00:00:00Z", "timeMax": f"{end.isoformat()}T23:59:59Z",
              "singleEvents": "false", "maxResults": 2500, "showDeleted": "false"}
    found, token = [], None
    while True:
        if token:
            params["pageToken"] = token
        data = _check(session.get(_url(calendar_id), params=params), "lesing").json()
        for ev in data.get("items", []):
            priv = (ev.get("extendedProperties") or {}).get("private", {})
            if priv.get("source", "").startswith("weekcalendar"):
                continue
            if _mentions(ev, marker.lower()):
                st = ev.get("start") or {}
                found.append({"id": ev["id"], "summary": ev.get("summary", ""),
                              "start": st.get("dateTime") or st.get("date") or ""})
        token = data.get("nextPageToken")
        if not token:
            return sorted(found, key=lambda e: e["start"])


def delete_ids(session, calendar_id, ids, allowed):
    """Delete the chosen events, but only ids that find_foreign returned (`allowed`)."""
    n = 0
    for i in ids:
        if i not in allowed:
            continue
        resp = session.delete(_url(calendar_id, "/" + i))
        if resp.status_code not in (200, 204, 404, 410):
            _check(resp, "sletting")
        n += 1
    return n
