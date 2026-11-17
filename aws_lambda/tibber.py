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
    nodes { from consumption cost } } } } }"""
MAX_PAGES = 15       # Tibber returns about a month per page: 15 pages reach well over a year back
HOURLY_Q = """{ viewer { homes { id
  consumption(resolution: HOURLY, last: %d%s) { pageInfo { startCursor hasPreviousPage }
    nodes { from consumption } } } } }"""
HOURS_PER_PAGE = 744   # a month of hours
CACHE_KEY = "cache/tibber_daily.json"


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


def daily_cost(data):
    """{date: cost in the account's currency (NOK)} summed over homes; days without a price are left out."""
    out = {}
    for home in ((data.get("viewer") or {}).get("homes") or []):
        for n in ((home.get("consumption") or {}).get("nodes") or []):
            if n.get("cost") is None:
                continue
            try:
                d = datetime.fromisoformat(str(n["from"]).replace("Z", "+00:00")).date()
            except (KeyError, ValueError):
                continue
            out[d] = out.get(d, 0.0) + float(n["cost"])
    return out


# Norgespris (fixed price via the grid company): kr/kWh incl. VAT, for up to NORGESPRIS_CAP kWh per month.
# Use above the cap is billed at the ordinary (spot) price. Nettleie and Tibber's monthly fee are not included.
NORGESPRIS = {2025: 0.50, 2026: 0.50}
NORGESPRIS_CAP = 5000


def _norgespris(year):
    return NORGESPRIS.get(year) or NORGESPRIS[max(NORGESPRIS)]


def _month_cost(kwh, year, spot_price):
    """Cost of one month's kWh under Norgespris; above the cap at `spot_price` (kr/kWh)."""
    within = min(kwh, NORGESPRIS_CAP)
    return within * _norgespris(year) + (kwh - within) * (spot_price if spot_price is not None else _norgespris(year))


def year_cost(per_day, per_day_cost, today, grid=None):
    """Electricity cost (Norgespris) so far this year and an estimate for the whole year, plus Elvia's
    nettleie when `grid` ({date: [day kWh, night kWh, peak hour kWh]}, from hourly data) covers the year.
    The rest of the year uses last year's kWh for the same dates, or else the last 30 days' average.
    -> {year, cost, estimate, nettleie} or None when the history doesn't cover this year."""
    per_day_cost = per_day_cost or {}
    start = date(today.year, 1, 1)
    so_far = [start + timedelta(days=i) for i in range((today - start).days)]      # up to yesterday
    if not so_far or sum(1 for d in so_far if d in per_day) < len(so_far) * 0.9:
        return None
    recent = [d for d in (today - timedelta(days=i) for i in range(1, 31)) if d in per_day]
    kwh_recent = sum(per_day[d] for d in recent)
    priced = [d for d in recent if d in per_day_cost]
    spot = sum(per_day_cost[d] for d in priced) / sum(per_day[d] for d in priced) \
        if priced and sum(per_day[d] for d in priced) else None

    rest = [today + timedelta(days=i) for i in range((date(today.year, 12, 31) - today).days + 1)]
    last = {d: per_day.get(_year_before(d)) for d in rest}
    use_last = sum(1 for v in last.values() if v is not None) >= len(rest) * 0.9
    avg = kwh_recent / len(recent) if recent else None
    months = {}          # month -> [kWh so far, kWh estimated]
    rest_kwh = {}
    for d in so_far:
        months.setdefault(d.month, [0.0, 0.0])[0] += per_day.get(d, 0.0)
    for d in rest:
        v = last[d] if use_last and last[d] is not None else avg
        rest_kwh[d] = v or 0.0
        months.setdefault(d.month, [0.0, 0.0])[1] += v or 0.0
    cost = sum(_month_cost(a, today.year, spot) for a, _b in months.values())
    total = sum(_month_cost(a + b, today.year, spot) for a, b in months.values())
    can_estimate = use_last or len(recent) >= 20
    grid_cost = _nettleie(per_day, grid, today, so_far, rest_kwh) if grid else None
    if grid_cost:
        cost, total = cost + grid_cost[0], total + grid_cost[1]
    return {"year": today.year, "cost": round(cost), "estimate": round(total) if can_estimate else None,
            "nettleie": bool(grid_cost)}


def _top3(values):
    top = sorted(values, reverse=True)[:3]
    return sum(top) / len(top) if top else 0.0


def _nettleie(per_day, grid, today, so_far, rest_kwh):
    """Elvia nettleie (so far, whole year) from daily [day kWh, night kWh, peak] values, or None when
    the hourly data doesn't cover this year. The rest of the year uses the last 30 days' day/night
    split and peak-to-kWh ratio on the estimated kWh."""
    import calendar
    import nettleie
    if sum(1 for d in so_far if d in grid) < len(so_far) * 0.9:
        return None
    energy_so_far = 0.0
    for d in so_far:
        if d in grid:
            energy_so_far += nettleie.energy_cost(d, grid[d][0], grid[d][1])
        else:   # a missing day: its kWh at the night rate
            energy_so_far += nettleie.energy_cost(d, 0.0, per_day.get(d, 0.0))
    recent = [d for d in (today - timedelta(days=i) for i in range(1, 31)) if d in grid and sum(grid[d][:2]) > 0]
    work = [d for d in recent if nettleie.is_workday(d)]
    work_kwh = sum(sum(grid[d][:2]) for d in work)
    day_share = sum(grid[d][0] for d in work) / work_kwh if work_kwh else 0.6
    peak_ratio = sum(grid[d][2] / sum(grid[d][:2]) for d in recent) / len(recent) if recent else 1 / 12
    energy_rest = 0.0
    peaks = {}           # month -> [daily peaks, actual and estimated]
    for d in so_far:
        if d in grid:
            peaks.setdefault(d.month, []).append(grid[d][2])
    actual_peaks = {m: list(v) for m, v in peaks.items()}
    for d, v in rest_kwh.items():
        share = day_share if nettleie.is_workday(d) else 0.0
        energy_rest += nettleie.energy_cost(d, v * share, v * (1 - share))
        peaks.setdefault(d.month, []).append(v * peak_ratio)
    fees_so_far, fees_total = 0.0, 0.0
    for m in range(1, 13):
        first = date(today.year, m, 1)
        fees_total += nettleie.capacity_fee(_top3(peaks.get(m, [])), first)
        if m < today.month:
            fees_so_far += nettleie.capacity_fee(_top3(actual_peaks.get(m, [])), first)
        elif m == today.month and actual_peaks.get(m):      # this month so far, pro rata
            days_in_month = calendar.monthrange(today.year, m)[1]
            fees_so_far += nettleie.capacity_fee(_top3(actual_peaks[m]), first) * (today.day - 1) / days_in_month
    return energy_so_far + fees_so_far, energy_so_far + energy_rest + fees_total


def summary(per_day, today, days=30, per_day_cost=None, grid=None):
    """Last `days` full days vs. the same dates a year earlier.
    -> {kwh, kwh_last_year, pct, days: [kWh...], last_year: [kWh or None...], year_cost}"""
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
            "last_year": [round(v, 1) if v is not None else None for v in last],
            "year_cost": year_cost(per_day, per_day_cost, today, grid)}


def _year_before(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:      # 29 Feb
        return d.replace(year=d.year - 1, day=28)


def fetch_history(token, max_pages=MAX_PAGES):
    """All homes' daily consumption, paging backwards (the API may return only part per request).
    Returns data shaped like a single query result."""
    first = query(token, CONSUMPTION_Q % "")
    homes = (first.get("viewer") or {}).get("homes") or []
    for home in homes:
        cons = home.get("consumption") or {}
        for _ in range(max_pages - 1):
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


def fetch_hours(token, since, max_pages=14, last=HOURS_PER_PAGE):
    """Hourly nodes for all homes, paging back until `since` (a date) is reached.
    -> (nodes, partial_first): partial_first is True when the oldest day may be cut off by the paging."""
    nodes, partial = [], False
    first = query(token, HOURLY_Q % (last, ""))
    for home in (first.get("viewer") or {}).get("homes") or []:
        cons = home.get("consumption") or {}
        got = list(cons.get("nodes") or [])
        info = cons.get("pageInfo") or {}
        for _ in range(max_pages - 1):
            oldest = _node_date(got[0]) if got else None
            if not info.get("hasPreviousPage") or not info.get("startCursor") or (oldest and oldest <= since):
                break
            page = next((h for h in (query(token, HOURLY_Q % (last, f', before: "{info["startCursor"]}"'))
                                     .get("viewer") or {}).get("homes") or [] if h.get("id") == home.get("id")), None)
            older = (page or {}).get("consumption") or {}
            if not older.get("nodes"):
                break
            got = older["nodes"] + got
            info = older.get("pageInfo") or {}
        partial = partial or bool(info.get("hasPreviousPage"))
        nodes += got
    return nodes, partial


def _node_date(n):
    try:
        return datetime.fromisoformat(str(n["from"]).replace("Z", "+00:00")).date()
    except (KeyError, ValueError):
        return None


def grid_days(nodes, partial_first=False):
    """Hourly nodes -> {date: [day-rate kWh, night/weekend kWh, peak hour kWh]} (Elvia's periods).
    Hours are summed over homes first. The oldest day is dropped when it may be incomplete."""
    import nettleie
    hours = {}
    for n in nodes:
        if n.get("consumption") is None:
            continue
        try:
            t = datetime.fromisoformat(str(n["from"]).replace("Z", "+00:00"))    # local time with offset
        except (KeyError, ValueError):
            continue
        key = (t.date(), t.hour)
        hours[key] = hours.get(key, 0.0) + float(n["consumption"])
    out = {}
    for (d, h), kwh in hours.items():
        v = out.setdefault(d, [0.0, 0.0, 0.0])
        v[0 if nettleie.is_day_hour(d, h) else 1] += kwh
        v[2] = max(v[2], kwh)
    if partial_first and out:
        out.pop(min(out))
    return {d: [round(a, 3), round(b, 3), round(c, 3)] for d, (a, b, c) in out.items()}


def _update_grid(token, today, cached):
    """This year's daily Elvia values, from the cache plus Tibber's hourly data: the year is fetched
    once, afterwards only the last three days (the oldest of them is dropped as possibly partial)."""
    grid = {date.fromisoformat(k): v for k, v in (cached.get("grid") or {}).items()}
    start = min(date(today.year, 1, 1), today - timedelta(days=31))
    if not grid or min(grid) > start + timedelta(days=1) and not cached.get("grid_complete"):
        nodes, partial = fetch_hours(token, start)
        complete = not partial
    else:
        nodes, partial = fetch_hours(token, today, max_pages=1, last=72)
        partial, complete = True, cached.get("grid_complete", False)
    grid.update(grid_days(nodes, partial))
    return {d: v for d, v in grid.items() if d >= start}, complete


def energy(token, today, s3=None, bucket=None):
    """The summary for the frame. With S3, the daily history is kept in cache/tibber_daily.json: the
    full history is fetched once (and again if it is too short), afterwards only the newest page."""
    if s3 is None:
        data = fetch_history(token)
        return summary(daily(data), today, per_day_cost=daily_cost(data))
    try:
        cached = json.loads(s3.get_object(Bucket=bucket, Key=CACHE_KEY)["Body"].read())
    except Exception:
        cached = {}
    known = {date.fromisoformat(k): v for k, v in (cached.get("days") or {}).items()}
    costs = {date.fromisoformat(k): v for k, v in (cached.get("cost") or {}).items()}
    full = not known or "cost" not in cached or \
        (not cached.get("complete") and min(known) > today - timedelta(days=400))   # older caches had no cost
    data = fetch_history(token) if full else fetch_history(token, max_pages=1)
    known.update(daily(data))
    costs.update(daily_cost(data))
    complete = cached.get("complete", False)
    if full:      # reached the start of the customer's history, or a year and a bit back
        complete = all(not ((h.get("consumption") or {}).get("pageInfo") or {}).get("hasPreviousPage")
                       for h in (data.get("viewer") or {}).get("homes") or []) or \
            min(known) <= today - timedelta(days=400)
    keep = {d: v for d, v in known.items() if d > today - timedelta(days=420)}
    keep_cost = {d: v for d, v in costs.items() if d > today - timedelta(days=420)}
    grid, grid_complete = {date.fromisoformat(k): v for k, v in (cached.get("grid") or {}).items()}, \
        cached.get("grid_complete", False)
    try:
        grid, grid_complete = _update_grid(token, today, cached)
    except Exception as e:      # nettleie is optional: keep what we have
        print(f"[tibber] hourly data failed: {e}")
    s3.put_object(Bucket=bucket, Key=CACHE_KEY, ContentType="application/json",
                  Body=json.dumps({"complete": complete, "days": {d.isoformat(): v for d, v in sorted(keep.items())},
                                   "cost": {d.isoformat(): round(v, 2) for d, v in sorted(keep_cost.items())},
                                   "grid": {d.isoformat(): v for d, v in sorted(grid.items())},
                                   "grid_complete": grid_complete})
                  .encode("utf-8"))
    return summary(keep, today, per_day_cost=keep_cost, grid=grid)


def vehicle_types(token):
    """Names of types in Tibber's public schema that look like car data (to see whether the car is available)."""
    data = query(token, "{ __schema { types { name } } }")
    names = [t.get("name", "") for t in ((data.get("__schema") or {}).get("types") or [])]
    return sorted(n for n in names if any(k in n.lower() for k in ("vehicle", "electricvehicle", "charger", "battery")))
