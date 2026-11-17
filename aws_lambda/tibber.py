"""
Tibber (stdlib only): household electricity per day, and the car's battery if Tibber has it.

API: POST https://api.tibber.com/v1-beta/gql, header Authorization: Bearer <TIBBER_TOKEN>
(a personal token from developer.tibber.com, stored in SSM as TIBBER_TOKEN).
"""
import json
import urllib.request
from datetime import date, datetime, timedelta

API = "https://api.tibber.com/v1-beta/gql"

CONSUMPTION_Q = """{ viewer { homes { id appNickname
  consumption(resolution: DAILY, last: 100%s) { pageInfo { startCursor hasPreviousPage }
    nodes { from consumption } } } } }"""
MAX_PAGES = 5        # 5 x 100 days: enough for "the same 30 days last year"


class TibberError(RuntimeError):
    pass


def query(token, q, timeout=10):
    req = urllib.request.Request(API, data=json.dumps({"query": q}).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                          "User-Agent": "weekcalendar/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise TibberError(f"Tibber: HTTP {e.code} {e.read()[:200].decode('utf-8', 'replace')}")
    if data.get("errors"):
        raise TibberError("Tibber: " + "; ".join(str(x.get("message")) for x in data["errors"])[:300])
    return data.get("data") or {}


def daily(data):
    """{date: kWh} summed over the account's homes (days without data are left out)."""
    out = {}
    for home in ((data.get("viewer") or {}).get("homes") or []):
        for n in ((home.get("consumption") or {}).get("nodes") or []):
            if n.get("consumption") is None:
                continue
            try:
                d = datetime.fromisoformat(str(n["from"]).replace("Z", "+00:00")).date()
            except (KeyError, ValueError):
                continue
            out[d] = out.get(d, 0.0) + float(n["consumption"])
    return out


def summary(per_day, today, days=30):
    """Last `days` full days vs. the same dates a year earlier.
    -> {kwh, kwh_last_year, pct, days: [kWh...], last_year: [kWh or None...], complete}"""
    dates = [today - timedelta(days=days - i) for i in range(days)]        # up to and including yesterday
    this = [per_day.get(d) for d in dates]
    last = [per_day.get(_year_before(d)) for d in dates]
    have_this = [v for v in this if v is not None]
    if not have_this:
        return None
    kwh = sum(have_this)
    complete_ly = sum(1 for v in last if v is not None) >= days * 0.9
    kwh_ly = sum(v for v in last if v is not None) if complete_ly else None
    pct = round((kwh - kwh_ly) / kwh_ly * 100) if kwh_ly else None
    against = "i fjor" if pct is not None else None
    if pct is None:      # no year of history yet: compare with the 30 days before instead
        before = [per_day.get(d - timedelta(days=days)) for d in dates]
        if sum(1 for v in before if v is not None) >= days * 0.9:
            kwh_prev = sum(v for v in before if v is not None)
            pct, against = (round((kwh - kwh_prev) / kwh_prev * 100), "forrige 30 dager") if kwh_prev else (None, None)
    return {"kwh": round(kwh), "kwh_last_year": round(kwh_ly) if kwh_ly else None, "pct": pct, "against": against,
            "days": [round(v, 1) if v is not None else None for v in this],
            "last_year": [round(v, 1) if v is not None else None for v in last]}


def _year_before(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:      # 29 Feb
        return d.replace(year=d.year - 1, day=28)


def fetch_history(token):
    """All homes' daily consumption, paging backwards (the API may return only part per request).
    Returns data shaped like a single query result."""
    first = query(token, CONSUMPTION_Q % "")
    homes = (first.get("viewer") or {}).get("homes") or []
    for home in homes:
        cons = home.get("consumption") or {}
        for _ in range(MAX_PAGES - 1):
            info = cons.get("pageInfo") or {}
            if not info.get("hasPreviousPage") or not info.get("startCursor"):
                break
            q = CONSUMPTION_Q % f', before: "{info["startCursor"]}"'
            page = next((h for h in (query(token, q).get("viewer") or {}).get("homes") or []
                         if h.get("id") == home.get("id")), None)
            older = (page or {}).get("consumption") or {}
            if not older.get("nodes"):
                break
            home["consumption"] = cons = {"pageInfo": older.get("pageInfo"),
                                          "nodes": older["nodes"] + (cons.get("nodes") or [])}
    return first


def energy(token, today):
    return summary(daily(fetch_history(token)), today)


def vehicle_types(token):
    """Names of types in Tibber's public schema that look like car data (to see whether the car is available)."""
    data = query(token, "{ __schema { types { name } } }")
    names = [t.get("name", "") for t in ((data.get("__schema") or {}).get("types") or [])]
    return sorted(n for n in names if any(k in n.lower() for k in ("vehicle", "electricvehicle", "charger", "battery")))
