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


# From a weekly letter these go to the frame only (this module); the rest (days off, meetings,
# deadlines, events) goes to Google Calendar.
SCHOOL_KINDS = ("early_finish", "trip", "gym", "bring")
REMINDER_PREFIX = "Husk denne uka: "


def _week(v):
    """A stored week: {"days": [...], "items": [...]} (a bare list is an older days-only week)."""
    return v if isinstance(v, dict) else {"days": v or [], "items": []}


def merge(store, child, week, days, items=()):
    """
    Store `child`'s week from a letter: `days` (extract.to_timetable) and the school `items`
    ([{date: 'YYYY-MM-DD', kind, title, start}]). Replaces that week; keeps the newest weeks.
    """
    store = {k: dict(v) for k, v in (store or {}).items() if isinstance(v, dict)}
    weeks = store.get(child, {})
    weeks[week] = {"days": list(days or []), "items": list(items or [])}
    store[child] = {k: weeks[k] for k in sorted(weeks)[-KEEP_WEEKS:]}
    return store


def _entry(weeks, d):
    """Timetable entry for d's weekday: this week's letter, else the latest recent one."""
    if d.weekday() > 4:
        return None
    w = weeks.get(week_key(d))
    if w is not None and _week(w)["days"]:
        return next((x for x in _week(w)["days"] if x.get("weekday") == d.weekday()), None)
    for k in range(1, FALLBACK_WEEKS + 1):
        w = weeks.get(week_key(d - timedelta(weeks=k)))
        if w is not None and _week(w)["days"]:
            e = next((x for x in _week(w)["days"] if x.get("weekday") == d.weekday()), None)
            if e and not e.get("closed"):    # last week's one-off closure says nothing about this week
                return e
    return None


def items_on(weeks, d):
    """The letter's school items for date d (only from d's own week)."""
    w = weeks.get(week_key(d))
    return [i for i in _week(w)["items"] if i.get("date") == d.isoformat()] if w is not None else []


def usual_end(weeks):
    """The end time that occurs most often in the stored weeks ('' if none)."""
    ends = Counter(x["end"] for w in weeks.values() for x in _week(w)["days"]
                   if x.get("end") and not x.get("closed"))
    return ends.most_common(1)[0][0] if ends else ""


def _tagged(ev, letter):
    return any(p[0] == letter for p in ev.get("people") or [])


def _color(p):
    from designs.moments import COLOR
    from designs.common import BLACK
    return COLOR.get(p.get("color", "BLACK"), BLACK)


def day_rows(store, people, day):
    """
    Rows for the 'Skoledag' box for `day` (a design day: {date, events}):
      [{name, letter, color, start, lunch, end, lessons, notes, early, off, note}]
    notes: [(kind, text)] from the letter (turdag, gym, things to bring). An early finish from the
    letter (or a "Skoleslutt 13:20" event) sets the end; a day off in the calendar overrides it all.
    """
    rows = []
    d = day["date"]
    for p in people or []:
        weeks = (store or {}).get(p.get("name"))
        if not weeks:
            continue
        letter = p.get("letter") or p["name"][0]
        e = _entry(weeks, d)
        items = [i for i in items_on(weeks, d) if not i.get("title", "").startswith(REMINDER_PREFIX)]
        events = [ev for ev in day.get("events") or [] if not ev.get("people") or _tagged(ev, letter)]
        holiday = next((ev for ev in events if not ev.get("time") and (
            ev.get("is_holiday") and not ev.get("people") or OFF_RE.search(ev.get("title") or ""))), None)
        if e is None and holiday is None and not items:
            continue
        row = {"name": p["name"], "letter": letter, "color": _color(p), "start": "", "lunch": "", "end": "",
               "lessons": [], "notes": [], "early": False, "off": False, "note": ""}
        if holiday is not None or (e and e.get("closed")):
            note = e.get("note") if e and e.get("closed") else ""
            row.update(off=True, note=note or (holiday or {}).get("title", "") or "Fri")
            rows.append(row)
            continue
        if e:
            row.update(start=e.get("start", ""), lunch=e.get("lunch", ""), end=e.get("end", ""),
                       lessons=list(e.get("lessons") or []))
        for i in items:
            if i.get("kind") == "early_finish":
                m = EARLY_RE.search("skoleslutt " + (i.get("start") or "")) or EARLY_RE.search(i.get("title", ""))
                if m:
                    row["end"] = f"{int(m.group(1)):02d}:{m.group(2)}"
            else:
                row["notes"].append((i.get("kind", ""), i.get("title", "")))
        for ev in events:
            m = EARLY_RE.search(ev.get("title") or "")
            if m:
                row["end"] = f"{int(m.group(1)):02d}:{m.group(2)}"
        usual = usual_end(weeks)
        row["early"] = bool(row["end"] and usual and row["end"] < usual)
        rows.append(row)
    return rows


def husk_events(store, people, start, end, skip=None):
    """
    The letters' reminders and things to bring from `start` to `end` as design events for the
    'Husk denne uka' box: {date: [event]}. `skip` = a date already shown in the 'Skoledag' box.
    """
    out = {}
    for p in people or []:
        weeks = (store or {}).get(p.get("name"))
        if not weeks:
            continue
        chip = [(p.get("letter") or p["name"][0], _color(p))]

        def add(d, title):
            out.setdefault(d, []).append({"time": "", "title": title, "icon": None, "people": chip,
                                          "is_holiday": False})
        w = weeks.get(week_key(start))
        for i in _week(w)["items"] if w is not None else []:
            if i.get("title", "").startswith(REMINDER_PREFIX):   # for the whole week, so shown from today
                add(start, i["title"])
        d = start
        while d <= end:
            for i in items_on(weeks, d):
                if d == skip or i.get("kind") == "early_finish" or i.get("title", "").startswith(REMINDER_PREFIX):
                    continue
                add(d, i.get("title", ""))
            d += timedelta(days=1)
    return out
