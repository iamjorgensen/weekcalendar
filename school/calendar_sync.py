"""
Write extracted school items into Google Calendar with a service account.

Each event is tagged with private extended properties (source, child, week),
so uploading the same week again replaces the old events instead of adding
duplicates.
"""
from datetime import datetime, timedelta

SOURCE = "weekcalendar-ukebrev"
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
API = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events"
TZ = "Europe/Oslo"


def session_from_service_account(info: dict):
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return AuthorizedSession(creds)


def _url(calendar_id, suffix=""):
    from urllib.parse import quote
    return API.format(cal=quote(calendar_id, safe="")) + suffix


def _check(resp, what):
    if resp.status_code >= 400:
        raise RuntimeError(f"Google Calendar {what} feilet: HTTP {resp.status_code} {resp.text[:300]}")
    return resp


def family_events(session, calendar_id, start, end):
    """Everything in the calendar between two dates, except events this tool wrote:
    [(date, 'HH:MM' or '', summary)]. Used so the model can skip duplicates."""
    from datetime import date as _date
    params = {"timeMin": f"{start.isoformat()}T00:00:00Z", "timeMax": f"{end.isoformat()}T23:59:59Z",
              "singleEvents": "true", "orderBy": "startTime", "maxResults": 2500}
    data = _check(session.get(_url(calendar_id), params=params), "lesing").json()
    out = []
    for ev in data.get("items", []):
        if (ev.get("extendedProperties") or {}).get("private", {}).get("source") == SOURCE:
            continue
        st = ev.get("start") or {}
        if st.get("date"):
            out.append((_date.fromisoformat(st["date"]), "", ev.get("summary", "")))
        elif st.get("dateTime"):
            dt = datetime.fromisoformat(st["dateTime"].replace("Z", "+00:00"))
            try:
                from zoneinfo import ZoneInfo
                dt = dt.astimezone(ZoneInfo(TZ))
            except Exception:
                pass
            out.append((dt.date(), dt.strftime("%H:%M"), ev.get("summary", "")))
    return out


def existing_events(session, calendar_id, child, week_id):
    params = {"privateExtendedProperty": [f"source={SOURCE}", f"child={child}", f"week={week_id}"],
              "maxResults": 250, "showDeleted": "false", "singleEvents": "true"}
    items, token = [], None
    while True:
        if token:
            params["pageToken"] = token
        data = _check(session.get(_url(calendar_id), params=params), "listing").json()
        items.extend(data.get("items", []))
        token = data.get("nextPageToken")
        if not token:
            return items


def event_body(child, week_id, item):
    d = item["date"]
    body = {
        "summary": f"{child}: {item['title']}",
        "description": "\n".join(x for x in (item.get("details"), f"Fra ukebrev {week_id}") if x),
        "extendedProperties": {"private": {"source": SOURCE, "child": child, "week": week_id,
                                           "kind": item.get("kind", "")}},
        "transparency": "transparent",   # don't block anyone's free/busy
    }
    start = item.get("start") or ""
    if start:
        try:
            st = datetime.strptime(f"{d.isoformat()} {start}", "%Y-%m-%d %H:%M")
        except ValueError:
            start = ""
    if start:
        try:
            en = datetime.strptime(f"{d.isoformat()} {item.get('end')}", "%Y-%m-%d %H:%M")
            if en <= st:
                raise ValueError
        except (ValueError, TypeError):
            en = st + timedelta(minutes=30 if item.get("kind") == "early_finish" else 60)
        body["start"] = {"dateTime": st.isoformat(), "timeZone": TZ}
        body["end"] = {"dateTime": en.isoformat(), "timeZone": TZ}
    else:
        body["start"] = {"date": d.isoformat()}
        body["end"] = {"date": (d + timedelta(days=1)).isoformat()}
    return body


def sync_week(session, calendar_id, child, week_id, items):
    """Replace this child's events for this week. Returns (deleted, created)."""
    old = existing_events(session, calendar_id, child, week_id)
    for ev in old:
        resp = session.delete(_url(calendar_id, "/" + ev["id"]))
        if resp.status_code not in (200, 204, 404, 410):
            _check(resp, "sletting")
    for item in items:
        _check(session.post(_url(calendar_id), json=event_body(child, week_id, item)), "oppretting")
    return len(old), len(items)
