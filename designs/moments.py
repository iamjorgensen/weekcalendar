"""
"Moments": what makes the screen feel alive on special days.

  banner(...)  -> a big, coloured banner for the top of the black panel
                  (birthdays, Christmas, Easter, 17. mai, school holidays, Advent ...)
  lines(...)   -> one or two short lines under the weather (countdowns, clock
                  change, nice weekend, the dinner question ...)
  birthday_events(...) -> birthdays from the admin page as events in the day list

Pure functions on design data; the drawing is in splash.py.
"""
from datetime import date, timedelta

from designs.common import BLACK, BLUE, GREEN, RED, WHITE, YELLOW

COLOR = {"BLACK": BLACK, "RED": RED, "GREEN": GREEN, "BLUE": BLUE, "YELLOW": YELLOW, "WHITE": WHITE}
WEEKDAY_SHORT = ["man", "tir", "ons", "tor", "fre", "lør", "søn"]


# ------------------------------------------------------------------ dates
def easter(year):
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    return date(year, (h + l - 7 * m + 114) // 31, (h + l - 7 * m + 114) % 31 + 1)


def _nth_sunday(year, month, n):
    d = date(year, month, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_sunday(year, month):
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def advent_sundays(year):
    d = date(year, 12, 24)
    d -= timedelta(days=(d.weekday() + 1) % 7)       # 4th Sunday of Advent (24th itself if a Sunday)
    return [d - timedelta(weeks=3 - k) for k in range(4)]


def special_days(year):
    """{date: key} for the days that get their own banner."""
    e = easter(year)
    out = {
        date(year, 1, 1): "nyttarsdag",
        e - timedelta(days=49): "fastelavn",
        _nth_sunday(year, 2, 2): "morsdag",
        e - timedelta(days=3): "skjaertorsdag",
        e - timedelta(days=2): "langfredag",
        e - timedelta(days=1): "paskeaften",
        e: "paskedag1",
        e + timedelta(days=1): "paskedag2",
        date(year, 5, 17): "17mai",
        date(year, 6, 23): "sankthans",
        date(year, 10, 31): "halloween",
        _nth_sunday(year, 11, 2): "farsdag",
        date(year, 12, 13): "lucia",
        date(year, 12, 24): "julaften",
        date(year, 12, 25): "juledag1",
        date(year, 12, 26): "juledag2",
        date(year, 12, 31): "nyttarsaften",
    }
    for n, d in enumerate(advent_sundays(year), 1):
        out[d] = f"advent{n}"     # beats Lucia when 13.12 is a Sunday
    for d in (date(year, 12, 27), date(year, 12, 28), date(year, 12, 29), date(year, 12, 30)):
        out.setdefault(d, "romjul")
    return out


def _span(ev):
    try:
        a, b = (date.fromisoformat(x) for x in ev.get("span", "").split("/"))
        return a, b
    except Exception:
        return None


def _day_of(ev, d):
    s = _span(ev)
    if not s:
        return ""
    a, b = s
    return f"Dag {(d - a).days + 1} av {(b - a).days + 1}"


# ------------------------------------------------------------------ people
def birthdays(people, d):
    """[(person, age or None)] with a birthday on date d (29 Feb -> 28 Feb in other years)."""
    out = []
    for p in people or []:
        if p.get("celebrate") is False:
            continue
        try:
            b = date.fromisoformat(p.get("birthday") or "")
        except ValueError:
            continue
        month, day = b.month, b.day
        if (month, day) == (2, 29):
            try:
                date(d.year, 2, 29)
            except ValueError:
                day = 28
        if (d.month, d.day) == (month, day):
            out.append((p, d.year - b.year if b.year > 1900 else None))
    return out


def _names(letters, people):
    by = {p.get("letter"): p["name"] for p in people or [] if p.get("letter")}
    names = [by[l] for l in letters if l in by]
    if not names:
        return ""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " og " + names[-1]


def _chip(p):
    return (p.get("letter") or p["name"][0], COLOR.get(p.get("color", "BLACK"), BLACK))


def birthday_events(days, people, skip=None):
    """Add 'Nora 10 år' (cake) to each listed day with a birthday, unless the calendar already has it."""
    for i, day in enumerate(days):
        if day["date"] == skip:
            continue
        for p, age in birthdays(people, day["date"]):
            name = p["name"].lower()
            if any(name in e["title"].lower() and ("år" in e["title"] or "bursdag" in e["title"].lower())
                   for e in day["events"]):
                continue
            title = f"{p['name']} {age} år" if age else f"{p['name']} har bursdag"
            ev = {"time": "", "sort_time": "", "title": title,
                  "icon": "dog" if p.get("kind") == "dyr" else "cake",
                  "people": [] if p.get("kind") == "dyr" else [_chip(p)], "is_holiday": False,
                  "span": "", "feed": ""}
            days[i] = day = dict(day, events=[ev] + day["events"])
    return days


# ------------------------------------------------------------------ banner
def _b(title, big, small, icon, bg, decor, fg=None, icon_col=None, **kw):
    return dict(title=title, big=big, small=small, icon=icon, bg=bg, decor=decor, fg=fg, icon_col=icon_col, **kw)


def banner(day, people=(), today=None):
    """The banner for the black panel's day, or None."""
    d = day["date"]
    events = day.get("events") or []

    # 1. birthdays (two on the same day share the banner)
    bdays = birthdays(people, d)
    if bdays:
        p, age = bdays[0]
        names = " og ".join(x["name"] for x, _ in bdays)
        bg = COLOR.get(p.get("color", "YELLOW"), YELLOW)
        title = f"Gratulerer, {names}!"
        if len(bdays) > 1:
            big, small = "Hurra!", "Dobbel bursdag i dag!"
        elif age:
            big, small = str(age), "år i dag!"
        else:
            big, small = "Hurra!", "Bursdag i dag!"
        b = _b(title, big, small, "dog" if p.get("kind") == "dyr" else "cake", bg, "party",
               birthday=[x["name"] for x, _ in bdays])
        if bg == BLACK:
            b.update(fg=YELLOW, edge="rainbow")     # black on black: gold text and a rainbow edge
        return b

    off = [e for e in events if e.get("is_holiday")]
    off_text = " ".join(e["title"].lower() for e in off)
    who = _names([l for e in off for l, _c in e.get("people") or []], people)
    who_line = f"{who} har fri" if who else ""
    ferie = next((e for e in off if _span(e)), None)
    day_of = _day_of(ferie, d) if ferie else ""

    # 2. fixed days of the year
    key = special_days(d.year).get(d)
    jul_days = {"julaften": "Julaften", "juledag1": "1. juledag", "juledag2": "2. juledag"}
    if key in jul_days:
        return _b("God jul!", jul_days[key], day_of or "Gledelig jul", "gift", RED, "snow")
    if key == "romjul":
        return _b("God romjul!", "Romjul", day_of or "Kos dere", "star", RED, "snow", icon_col=YELLOW)
    if key == "nyttarsaften":
        return _b("Godt nytt år!", str(d.year + 1), "Nyttårsaften", "star", BLUE, "fireworks", icon_col=YELLOW)
    if key == "nyttarsdag":
        return _b("Godt nytt år!", str(d.year), "1. januar", "star", BLUE, "fireworks", icon_col=YELLOW)
    paske = {"skjaertorsdag": "Skjærtorsdag", "langfredag": "Langfredag", "paskeaften": "Påskeaften",
             "paskedag1": "1. påskedag", "paskedag2": "2. påskedag"}
    if key in paske:
        return _b("God påske!", paske[key], day_of or "Påskeferie", "sun", YELLOW, "eggs")
    if key == "17mai":
        return _b("Hipp hurra!", "17. mai", "Gratulerer, Norge!", "flag", RED, "flags", fg=WHITE)
    if key and key.startswith("advent"):
        n = int(key[-1])
        to_jul = (date(d.year, 12, 24) - d).days
        return _b("God advent!", f"{n}. søndag", f"{to_jul} dager til jul", None, GREEN, "snow", candles=n)
    if key == "lucia":
        return _b("God Lucia!", "Luciadagen", "Lussekatter til frokost?", "star", BLUE, "snow", icon_col=YELLOW)
    if key == "morsdag":
        return _b("Gratulerer!", "Morsdag", "Frokost på senga?", "heart", RED, "party", fg=WHITE)
    if key == "farsdag":
        return _b("Gratulerer!", "Farsdag", "Frokost på senga?", "heart", BLUE, "party")
    if key == "fastelavn":
        return _b("Fastelavn!", "Boller", "med krem i dag", "food", YELLOW, "party")
    if key == "sankthans":
        return _b("God sankthans!", "Sankthans", "Bål og grill i kveld", "sun", BLUE, "sun", icon_col=YELLOW)
    if key == "halloween":
        return _b("Knask eller knep!", "Halloween", "Hold godteriet klart", "moon", BLACK, "party",
                  fg=YELLOW, edge="rainbow")

    # 3. days off from the calendar / school letters
    if off:
        if "jul" in off_text:
            return _b("God jul!", "Juleferie", day_of or who_line, "gift", RED, "snow")
        if "påske" in off_text:
            return _b("God påske!", "Påskeferie", day_of or who_line, "sun", YELLOW, "eggs")
        if "vinter" in off_text:
            return _b("God vinterferie!", day_of or "Vinterferie", who_line, "sledding", BLUE, "snow")
        if "sommer" in off_text:
            return _b("God sommer!", "Sommerferie", day_of or who_line, "sun", BLUE, "sun", icon_col=YELLOW)
        if "høst" in off_text:
            return _b("God høstferie!", day_of or "Høstferie", who_line, "tree", YELLOW, "leaves")
        if ferie:
            return _b("God ferie!", ferie["title"][:22], day_of or who_line, "umbrella_beach", BLUE, "sun")
        e = off[0]
        if not e.get("people"):    # a public holiday from the holiday calendar
            return _b("Fri i dag!", e["title"][:22], "Helligdag", "flag", RED, "flags", fg=WHITE)
        return _b("Fri i dag!", e["title"][:22], who_line, "sun", GREEN, "party")

    # 4. match day: a fixture from a calendar feed (not Spond practice)
    match = next((e for e in events if e.get("feed") and not e["feed"].startswith("spond")
                  and e.get("icon") in ("soccer", "volleyball", "skate")), None)
    if match:
        return _b("Kampdag!", match.get("time") or "I dag", match["title"][:28], match["icon"], RED, "flags", fg=WHITE)
    return None


# ------------------------------------------------------------------ small lines
def _plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def lines(days, people=(), now=None, dinner_question="", evening=False, max_lines=2):
    """Short yellow lines under the weather, most useful first."""
    if not days:
        return []
    today = (now.date() if now else days[0]["date"])
    out = []

    if evening and dinner_question:
        out.append(f"Middagsspørsmål: {dinner_question}")

    # birthdays coming up (tomorrow .. 7 days)
    for n in range(1, 8):
        d = today + timedelta(days=n)
        bd = birthdays(people, d)
        if bd:
            p, age = bd[0]
            what = f"{p['name']} {age} år" if age else f"{p['name']} sin bursdag"
            out.append(f"I morgen: {what}!" if n == 1 else f"{_plural(n, 'dag', 'dager')} til {what}")
            break

    # special days tomorrow
    sp = special_days((today + timedelta(days=1)).year).get(today + timedelta(days=1))
    if sp == "morsdag":
        out.append("Morsdag i morgen!")
    elif sp == "farsdag":
        out.append("Farsdag i morgen!")

    # clock change tonight
    tomorrow = today + timedelta(days=1)
    if tomorrow == _last_sunday(tomorrow.year, 3):
        out.append("Klokka stilles fram en time i natt")
    elif tomorrow == _last_sunday(tomorrow.year, 10):
        out.append("Klokka stilles tilbake en time i natt")

    # holidays starting within a week
    for day in days[1:8]:
        start = next((e for e in day.get("events") or [] if e.get("is_holiday") and _span(e)
                      and _span(e)[0] == day["date"]), None)
        if start:
            n = (day["date"] - today).days
            name = start["title"].split(" ")[0]
            out.append(f"I morgen: {name}!" if n == 1 else f"{_plural(n, 'dag', 'dager')} til {name.lower()}")
            break

    # Christmas countdown in December
    if today.month == 12 and today.day < 24 and special_days(today.year).get(today, "")[:6] != "advent":
        out.append(f"{_plural(24 - today.day, 'dag', 'dager')} til jul")

    # solstice
    if (today.month, today.day) == (6, 21):
        out.append("Sommersolverv – årets lengste dag")
    elif (today.month, today.day) == (12, 21):
        out.append("Vintersolverv – nå blir dagene lengre")

    # nice weekend ahead (on Fridays)
    if today.weekday() == 4:
        wk = [x["weather"] for x in days[1:3] if x.get("weather")]
        if len(wk) == 2 and all(w.get("tmax", 0) >= 15 and (w.get("precip") or 0) < 1 for w in wk):
            out.append(f"Fint vær i helga: {max(w['tmax'] for w in wk):.0f}°")

    # a day off with nothing planned
    d0 = days[0]
    if d0["date"] == today and d0.get("events") and all(e.get("is_holiday") for e in d0["events"]):
        out.append("Ingen planer i dag – hva med en tur?")

    return out[:max_lines]
