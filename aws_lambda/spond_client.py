"""
Minimal client for Spond's (unofficial) API, stdlib only so the small serve
function can use it too. Same endpoints as the open-source `spond` package:
  POST core/v1/auth2/login {email, password} -> {"accessToken": {"token": ...}}
  GET  core/v1/groups/
  GET  core/v1/sponds/?groupId=&minEndTimestamp=&maxStartTimestamp=&max=
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.spond.com/core/v1/"
_DT = "%Y-%m-%dT00:00:00.000Z"


class SpondError(RuntimeError):
    pass


def _request(method, path, token=None, body=None, params=None, timeout=20):
    url = API + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"content-type": "application/json", "User-Agent": "weekcalendar/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode("utf-8", "replace")
        raise SpondError(f"Spond {path}: HTTP {e.code} {detail}")


def login(email, password):
    res = _request("POST", "auth2/login", body={"email": email, "password": password})
    token = ((res or {}).get("accessToken") or {}).get("token")
    if not token:
        raise SpondError("Innlogging til Spond feilet – sjekk e-post og passord")
    return token


def groups(token):
    """[{id, name, subGroups: [{id, name}]}] the account can see."""
    out = []
    for g in _request("GET", "groups/", token) or []:
        out.append({"id": g.get("id"), "name": g.get("name") or "",
                    "subGroups": [{"id": s.get("id"), "name": s.get("name") or ""} for s in g.get("subGroups") or []]})
    return out


def events(token, group_id, days_ahead=90, now=None):
    now = now or datetime.now(timezone.utc)
    params = {"groupId": group_id, "max": "300", "scheduled": "true",
              "minEndTimestamp": (now - timedelta(days=1)).strftime(_DT),
              "maxStartTimestamp": (now + timedelta(days=days_ahead)).strftime(_DT)}
    return _request("GET", "sponds/", token, params=params) or []


def _ts(v):
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def to_feed_events(spond_events):
    """Spond events -> the parsed-event shape feeds.sync_events() takes. Cancelled ones get STATUS CANCELLED."""
    out = []
    for e in spond_events or []:
        start, end = _ts(e.get("startTimestamp")), _ts(e.get("endTimestamp"))
        if not start or not e.get("heading"):
            continue
        loc = e.get("location") or {}
        place = ", ".join(x for x in (loc.get("feature"), loc.get("address")) if x)
        out.append({
            "uid": f"spond-{e.get('id')}",
            "summary": str(e["heading"]).strip(),
            "start": start,
            "end": end if end and end > start else None,
            "all_day": False,
            "location": place,
            "description": "Fra Spond",
            "status": "CANCELLED" if e.get("cancelled") else "",
        })
    return out
