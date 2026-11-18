"""
Each child's school week from the weekly letters ("Skoledag" box on the frame).

Stored in S3 (log/timetable.json) as {child: {"YYYY-Www": [{weekday, start, end, lunch, lessons, closed, note}, ...]}}.
Pure logic here; the Lambdas read and write the JSON.
"""
import re
from collections import Counter
from datetime import date, timedelta

KEY = "log/timetable.json"
KEEP_WEEKS = 10                      # per child
FALLBACK_WEEKS = 3                   # no letter this week: use the latest one at most this old
OFF_RE = re.compile(r"ferie\b|\b(fri|fridag|planleggingsdag|kursdag|stengt|skolefri)\b", re.I)   # høstferie too
EARLY_RE = re.compile(r"\bskoleslutt\s+(\d{1,2})[.:](\d{2})\b", re.I)


def week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def merge(store, child, week, days):
    """Store `days` (extract.to_timetable) as `child`'s timetable for `week`; keeps the newest weeks."""
    store = {k: dict(v) for k, v in (store or {}).items() if isinstance(v, dict)}
    weeks = store.get(child, {})
    weeks[week] = days
    store[child] = {k: weeks[k] for k in sorted(weeks)[-KEEP_WEEKS:]}
    return store


def _entry(weeks, d):
    """(entry for d's weekday, from_this_week) - this week's letter, else the latest recent one."""
    if d.weekday() > 4:
        return None, False
    days = weeks.get(week_key(d))
    if days is not None:
        return next((x for x in days if x.get("weekday") == d.weekday()), None), True
    for k in range(1, FALLBACK_WEEKS + 1):
        days = weeks.get(week_key(d - timedelta(weeks=k)))
        if days is not None:
            e = next((x for x in days if x.get("weekday") == d.weekday()), None)
            if e and not e.get("closed"):    # last week's one-off closure says nothing about this week
                return e, False
    return None, False


def usual_end(weeks):
    """The end time that occurs most often in the stored weeks ('' if none)."""
    ends = Counter(x["end"] for days in weeks.values() for x in days if x.get("end") and not x.get("closed"))
    return ends.most_common(1)[0][0] if ends else ""


def _tagged(ev, letter):
    return any(p[0] == letter for p in ev.get("people") or [])


def day_rows(store, people, day):
    """
    Rows for the 'Skoledag' box for `day` (a design day: {date, events}):
      [{name, letter, color, start, lunch, end, lessons, early, off, note}]
    Children are the people with a stored timetable. A school-letter event "Skoleslutt 13:20" or an
    all-day holiday/closed day in the calendar overrides the timetable.
    """
    from designs.moments import COLOR
    from designs.common import BLACK
    rows = []
    d = day["date"]
    for p in people or []:
        weeks = (store or {}).get(p.get("name"))
        if not weeks:
            continue
        letter = p.get("letter") or p["name"][0]
        e, _this_week = _entry(weeks, d)
        events = [ev for ev in day.get("events") or [] if not ev.get("people") or _tagged(ev, letter)]
        holiday = next((ev for ev in events if not ev.get("time") and (
            ev.get("is_holiday") and not ev.get("people") or OFF_RE.search(ev.get("title") or ""))), None)
        if e is None and holiday is None:
            continue
        row = {"name": p["name"], "letter": letter, "color": COLOR.get(p.get("color", "BLACK"), BLACK),
               "start": "", "lunch": "", "end": "", "lessons": [], "early": False, "off": False, "note": ""}
        if holiday is not None or (e and e.get("closed")):
            note = (e or {}).get("note") if e and e.get("closed") else ""
            row.update(off=True, note=note or (holiday or {}).get("title", "") or "Fri")
            rows.append(row)
            continue
        row.update(start=e.get("start", ""), lunch=e.get("lunch", ""), end=e.get("end", ""), lessons=list(e.get("lessons") or []))
        for ev in events:
            m = EARLY_RE.search(ev.get("title") or "")
            if m:
                row["end"] = f"{int(m.group(1)):02d}:{m.group(2)}"
        usual = usual_end(weeks)
        row["early"] = bool(row["end"] and usual and row["end"] < usual)
        rows.append(row)
    return rows
