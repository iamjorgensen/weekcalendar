"""
Concept A2 — "Dense hero": the hero layout squeezed for maximum information.

Differences from hero.py:
  - Today's weather: icon + temp, then morning/day/evening on ONE line, then
    precipitation + wind.
  - Day sections start with a rule above the heading (weekday in bold, then the date);
    waste pickup as a small outlined tag; weather icon + max temp right (precipitation
    >= 1 mm in blue in front of it).
  - Waste pickup events are not separate rows in the day list.
  - One event per row: time (fixed column) | icon | title ... people, so titles line up.
"""
import re
from datetime import timedelta

from PIL import Image, ImageDraw

from designs import hero
from designs.blocks import event_row
from designs.common import (
    draw_battery,
    BLACK, BLUE, RED, WHITE, YELLOW, W, H, MONTHS, WEEKDAYS, WEEKDAYS_SHORT, MONTHS_SHORT,
    cap_height, chip_ring, draw_text_top, ellipsize, f_body, f_bold, f_light, f_tiny, is_red_day, paste_icon,
    person_chip, quantize, text_w, weather_icon_name, wrap,
)

HERO_W = hero.HERO_W
ROW = dict(size=15, icon_size=16, chip_d=16, max_lines=2, pad=3)
TODAY_ROW = dict(size=16, icon_size=20, chip_d=18, max_lines=2, pad=2)

WASTE_WORDS = ("restavfall", "papir", "plast", "glass", "metall", "matavfall", "bioavfall",
               "avfall", "tømming", "movar", "søppel", "farlig avfall")
WASTE_SHORT = [("rest", "Rest"), ("papir", "Papir"), ("plast", "Plast"), ("glass", "Glass"),
               ("mat", "Mat"), ("bio", "Bio"), ("farlig", "Farlig")]


def is_waste(ev):
    if (ev.get("icon") or "") in ("trash", "trash-2"):
        return True
    t = (ev.get("title") or "").lower()
    return any(w in t for w in WASTE_WORDS)


def waste_label(ev):
    t = (ev.get("title") or "").lower()
    parts = [label for key, label in WASTE_SHORT if key in t]
    return "/".join(parts[:2]) or (ev.get("title") or "Avfall").split()[0]


# ------------------------------------------------------------------ today panel
def _today(img, draw, day, updated, accent=RED, battery=None, reserve_bottom=0, banner=None, extra_lines=(),
           car=None):
    draw.rectangle([0, 0, HERO_W, H], fill=BLACK)
    x0, x1 = 18, HERO_W - 16
    d = day["date"]
    red = is_red_day(d, day["events"])

    if banner:     # birthday / holiday: a big coloured banner replaces the date heading
        from designs.splash import draw_banner
        line = f"{WEEKDAYS[d.weekday()]} {d.day}. {MONTHS[d.month - 1]} · uke {d.isocalendar()[1]}"
        y = draw_banner(img, draw, HERO_W, banner, line, seed=d.toordinal()) + 4
    else:
        y = _today_heading(draw, day, d, red, accent, x0, x1)
    return _today_body(img, draw, day, y, x0, x1, updated, battery, reserve_bottom, extra_lines, car)


def _today_heading(draw, day, d, red, accent, x0, x1):
    f_day, f_num, f_mon = f_bold(26), f_bold(50), f_body(21)
    y = 14
    heading = day.get("heading") or WEEKDAYS[d.weekday()]
    draw_text_top(draw, (x0, y), heading, f_day, YELLOW if day.get("heading") else (accent if red else WHITE))
    f_wk = f_tiny(15)
    wk = f"uke {d.isocalendar()[1]}"
    draw_text_top(draw, (x1 - text_w(draw, wk, f_wk), y + cap_height(draw, f_day) - cap_height(draw, f_wk)),
                  wk, f_wk, WHITE)
    y += cap_height(draw, f_day) + 11
    num = str(d.day)
    draw_text_top(draw, (x0, y), num, f_num, WHITE)
    nch, mch = cap_height(draw, f_num), cap_height(draw, f_mon)
    draw_text_top(draw, (x0 + text_w(draw, num, f_num) + 10, y + nch - mch), MONTHS[d.month - 1], f_mon, WHITE)
    y += nch + 14
    return y


def _precip_text(mm):
    return f"{mm:.1f} mm".replace(".", ",")


def _today_weather(img, draw, w, y, x0, x1):
    """Big icon + temperature with condition and min below, wind (and rain if any) top right,
    morning/day/evening in three cells, then the clothing advice. Returns y after."""
    isz = 40
    paste_icon(img, weather_icon_name(w.get("symbol")), x0 - 2, y, isz, WHITE)
    f_t, f_s, f_d = f_bold(30), f_body(15), f_tiny(14)
    tx = x0 + isz + 10
    draw_text_top(draw, (tx, y + 1), f"{w['tmax']:.0f}°", f_t, WHITE)

    # right: wind, and under it the precipitation when there is any (>= 0.1 mm)
    right = [("wind", f"{w.get('wind', 0):.0f} m/s {w.get('wind_dir', '')}".strip(), y + 4)]
    if (w.get("precip") or 0) >= 0.1:
        right.append(("umbrella", _precip_text(w["precip"]), y + 24))
    for ic, txt, ty in right:
        rx = x1 - text_w(draw, txt, f_d)
        draw_text_top(draw, (rx, ty), txt, f_d, WHITE)
        paste_icon(img, ic, rx - 21, ty - 3, 16, WHITE)
    sy = y + 1 + cap_height(draw, f_t) + 7
    room = x1 - tx
    if len(right) > 1:      # keep the condition line clear of the rain amount
        room = x1 - text_w(draw, right[1][1], f_d) - 21 - 8 - tx
    draw_text_top(draw, (tx, sy), ellipsize(draw, f"{w.get('symbol', '')}  ·  min {w['tmin']:.0f}°", f_s, room),
                  f_s, WHITE)
    y += isz + 10

    periods = w.get("periods") or []
    if periods:             # three equal cells with a rule above and dividers between
        cw = (x1 - x0 + 1) / len(periods)
        f_l, f_p = f_tiny(12), f_bold(16)
        draw.rectangle([x0, y, x1, y], fill=WHITE)
        for k, (label, ic, temp) in enumerate(periods):
            cx = round(x0 + k * cw)
            if k:
                draw.rectangle([cx, y + 6, cx, y + 40], fill=WHITE)
            lx = cx + (10 if k else 0)
            draw_text_top(draw, (lx, y + 7), label, f_l, WHITE)
            paste_icon(img, weather_icon_name(ic), lx, y + 21, 20, WHITE)
            draw_text_top(draw, (lx + 25, y + 25), f"{temp:.0f}°", f_p, WHITE)
        y += 48
    if w.get("advice"):
        f_a = f_body(14)
        adv = re.sub(r"^Klær:\s*", "", w["advice"])
        paste_icon(img, "shirt", x0, y - 2, 16, YELLOW)
        draw_text_top(draw, (x0 + 22, y), ellipsize(draw, adv, f_a, x1 - x0 - 22), f_a, YELLOW)
        y += 21
    return y + 1


def _today_body(img, draw, day, y, x0, x1, updated, battery, reserve_bottom, extra_lines, car=None):
    w = day.get("weather") or {}
    if w:
        y = _today_weather(img, draw, w, y, x0, x1)
    for text in extra_lines or ():    # countdowns, clock change, dinner question (may take two lines)
        from designs.common import wrap
        f_ln = f_body(14)
        two = text.startswith(("Middagsspørsmål", "Svar på Spond")) or "farevarsel" in text
        chips = getattr(text, "chips", ()) or ()
        room = x1 - x0 - 17 * len(chips)
        for part in wrap(draw, text, f_ln, room, 2 if two else 1):
            draw_text_top(draw, (x0, y), part, f_ln, YELLOW)
            y += 19
        cx = x1 - 17 * len(chips) + 8
        for letter, col in chips:     # who it is for, like on the events
            person_chip(draw, cx, y - 19 + cap_height(draw, f_ln) // 2, letter, col, 15, bg=BLACK)
            cx += 17
        y += 1

    draw.rectangle([x0, y, x1, y + 1], fill=WHITE)
    y += 7

    bottom = H - 26 - reserve_bottom
    shown = 0
    n = len(day["events"])
    for k, ev in enumerate(day["events"]):
        kw = TODAY_ROW
        h = event_row(img, draw, x0, y, x1 - x0, ev, draw_it=False, **kw)
        # keep a line free for "+ N til" unless this is the last event
        if y + h > bottom - (18 if k < n - 1 else 0):
            break
        event_row(img, draw, x0, y, x1 - x0, ev, color=WHITE, bg=BLACK, **kw)
        y += h
        shown += 1
    rest = len(day["events"]) - shown
    if rest:
        draw_text_top(draw, (x0, y + 2), f"+ {rest} til", f_tiny(14), YELLOW)
    if rest:
        y += 20
    if not day["events"]:
        draw_text_top(draw, (x0, y + 4), "Ingen avtaler i dag", f_body(16), WHITE)
        y += 28

    f_up = f_tiny(12)
    up = f"Oppdatert {updated}"
    draw_text_top(draw, (x1 - text_w(draw, up, f_up), H - 17), up, f_up, WHITE)
    if battery is not None:
        draw_battery(draw, x0, H - 17 + cap_height(draw, f_up) // 2, battery, WHITE)
        if battery < LOW_BATTERY:     # "Bytt batteri!" next to the battery
            draw_text_top(draw, (x0 + 66, H - 17), "Bytt batteri!", f_bold(12), YELLOW)
    if car and car.get("pct") is not None and not (battery is not None and battery < LOW_BATTERY):
        cx = x0 + 70                  # the car's battery, e.g. "⚡ Bil 64 %"
        _bolt(draw, cx, H - 19, 13, YELLOW)
        draw_text_top(draw, (cx + 16, H - 17), f"Bil {car['pct']:.0f} %", f_bold(12), WHITE)
    return y


LOW_BATTERY = 15


# ------------------------------------------------------------------ day list
def _waste_tag_w(draw, ev):
    return 17 + text_w(draw, waste_label(ev), f_tiny(12)) + 5


def _day_section(img, draw, x, y, w, day, measure=False, morning=False):
    """A day in the list: a rule above the heading (red on red days), 'Tor 19. nov', waste
    pickup tags, weather right; then one row per event. Returns the height."""
    d = day["date"]
    red = is_red_day(d, day["events"])
    col = RED if red else BLACK
    fh = f_bold(16)
    hdr_h = cap_height(draw, fh) + 13

    waste = [e for e in day["events"] if is_waste(e)]
    events = [e for e in day["events"] if not is_waste(e)]
    heights = [event_row(None, draw, 0, 0, w, e, draw_it=False, **ROW) for e in events]
    f_none = f_body(14)
    total = hdr_h + sum(heights) + (5 if events else cap_height(draw, f_none) + 11)
    if measure:
        return total

    draw.rectangle([x, y, x + w, y + 1], fill=col)
    ty = y + 7
    label = day.get("label")              # e.g. "I kveld": no date
    wd = label or WEEKDAYS_SHORT[d.weekday()]
    draw_text_top(draw, (x, ty), wd, fh, col)
    lx = x + text_w(draw, wd, fh) + 6
    if not label:
        rest, fr = f"{d.day}. {MONTHS_SHORT[d.month - 1]}", f_body(16)
        draw_text_top(draw, (lx, ty), rest, fr, col)
        lx += text_w(draw, rest, fr) + 6
    cy = ty + cap_height(draw, fh) // 2

    f_w = f_tiny(12)
    for e in waste:                       # waste pickup as a small outlined tag
        tw = _waste_tag_w(draw, e)
        if lx + 2 + tw > x + w:
            break
        draw.rounded_rectangle([lx + 2, cy - 8, lx + 2 + tw, cy + 8], 3, outline=col, width=1)
        paste_icon(img, "trash-2", lx + 4, cy - 6, 12, col)
        draw_text_top(draw, (lx + 19, cy - cap_height(draw, f_w) // 2), waste_label(e), f_w, col)
        lx += tw + 6

    wthr = day.get("weather")
    if wthr:                              # icon + temp right; rain (>= 1 mm) in blue in front
        f_t = f_bold(14)
        txt = f"{wthr['tmax']:.0f}°"
        if morning and wthr.get("morning") is not None:
            txt = f"kl 8: {wthr['morning']:.0f}°"
        p = f"{wthr['precip']:.0f} mm" if (wthr.get("precip") or 0) >= 1 else ""
        need = text_w(draw, txt, f_t) + 20 + (text_w(draw, p, f_w) + 6 if p else 0)
        if p and x + w - need < lx:
            p, need = "", text_w(draw, txt, f_t) + 20
        if x + w - need >= lx:
            rx = x + w - text_w(draw, txt, f_t)
            draw_text_top(draw, (rx, cy - cap_height(draw, f_t) // 2), txt, f_t, col)
            paste_icon(img, weather_icon_name(wthr.get("symbol")), rx - 20, cy - 8, 16, col)
            rx -= 20
            if p:
                rx -= text_w(draw, p, f_w) + 6
                draw_text_top(draw, (rx, cy - cap_height(draw, f_w) // 2), p, f_w, BLUE)

    yy = y + hdr_h
    if not events:
        draw_text_top(draw, (x, yy + 2), "Ingen avtaler", f_none, col)
    for e, h in zip(events, heights):
        event_row(img, draw, x, yy, w, e, **ROW)
        yy += h
    return total


# ------------------------------------------------------------------ options
def run_label(start, end):
    """'tir–fre', 'hele uka' or 'til 28.11' for a run of daily all-day events."""
    wd = lambda d: WEEKDAYS_SHORT[d.weekday()].lower()
    if (end - start).days <= 6:
        if start.weekday() == 0 and end.weekday() >= 4:
            return "hele uka"
        return f"{wd(start)}–{wd(end)}"
    return f"til {end.day}.{end.month}"


def collapse_repeats(days, min_run=3):
    """
    All-day events with the same title on >= min_run consecutive days are shown once,
    on the first day, as 'Juleboden (til man 23.)'. Timed occurrences stay as they are.
    """
    titles = {}
    for i, day in enumerate(days):
        for ev in day["events"]:
            if not ev.get("time") and not is_waste(ev):
                titles.setdefault(ev["title"], []).append(i)
    remove = {}   # day index -> titles to drop
    label = {}    # (day index, title) -> new title
    for title, idxs in titles.items():
        run = [idxs[0]]
        for i in idxs[1:] + [None]:
            if i is not None and i == run[-1] + 1:
                run.append(i)
                continue
            if len(run) >= min_run:
                start, end = days[run[0]]["date"], days[run[-1]]["date"]
                label[(run[0], title)] = f"{title} ({run_label(start, end)})"
                for j in run[1:]:
                    remove.setdefault(j, set()).add(title)
            if i is not None:
                run = [i]
    out = []
    for i, day in enumerate(days):
        evs = []
        for ev in day["events"]:
            if not ev.get("time") and ev["title"] in remove.get(i, ()):
                continue
            if not ev.get("time") and (i, ev["title"]) in label:
                ev = dict(ev, title=label[(i, ev["title"])])
            evs.append(ev)
        out.append(dict(day, events=evs))
    return out


WX_LINE_H = 20


def _tomorrow_weather(img, draw, w, x0, x1, y, inline_xl=None):
    """Tomorrow's weather. As its own line at y: '[icon] 1° / -3°  [rain] 4 mm  [wind] 6 m/s N'
    (rain only if >= 1 mm; parts dropped from the right until it fits). With inline_xl: just
    '[icon] 1°' right-aligned on the heading line (y is then the line's vertical centre)."""
    if not w:
        return
    f = f_bold(14)
    sym = weather_icon_name(w.get("symbol"))
    if inline_xl is not None:
        t = f"{w['tmax']:.0f}°"
        tx = x1 - text_w(draw, t, f)
        if tx - 19 >= inline_xl:
            paste_icon(img, sym, tx - 19, y - 8, 16, WHITE)
            draw_text_top(draw, (tx, y - cap_height(draw, f) // 2), t, f, WHITE)
        return
    temp = f"{w['tmax']:.0f}°" + (f" / {w['tmin']:.0f}°" if w.get("tmin") is not None else "")
    parts = [(sym, temp)]
    if (w.get("precip") or 0) >= 1:
        parts.append(("droplet", f"{w['precip']:.0f} mm"))
    if w.get("wind") is not None:
        parts.append(("wind", f"{w['wind']:.0f} m/s {w.get('wind_dir') or ''}".strip()))
    gap = 12
    while len(parts) > 1 and sum(19 + text_w(draw, t, f) for _i, t in parts) + gap * (len(parts) - 1) > x1 - x0:
        parts.pop(-2 if len(parts) == 3 else -1)   # drop rain before wind
    cx = x0
    for ic, t in parts:
        paste_icon(img, ic, cx - (2 if ic == sym else 0), y - 2, 16, WHITE)
        draw_text_top(draw, (cx + 19, y), t, f, WHITE)
        cx += 19 + text_w(draw, t, f) + gap


def _tomorrow(img, draw, day, y, bottom, label="I morgen"):
    """'I morgen' block in the black panel. Returns True if drawn."""
    x0, x1 = 18, HERO_W - 16
    if not day["events"] or bottom - y < 56:
        return False
    # Only show the block if ALL of tomorrow's events fit: the day list then skips
    # tomorrow, so a partial block would hide events.
    kw = dict(size=15, icon_size=16, chip_d=16, max_lines=1, pad=3)
    need = 4 + 8 + cap_height(draw, f_bold(15)) + 8 + sum(
        event_row(img, draw, x0, 0, x1 - x0, ev, draw_it=False, **kw) for ev in day["events"])
    wx = day.get("weather")
    wx_line = bool(wx) and y + need + WX_LINE_H <= bottom   # own weather line, else temp on the heading
    if y + need > bottom:
        return False
    y += 4
    draw.rectangle([x0, y, x1, y], fill=WHITE)
    y += 8
    fh = f_bold(15)
    d = day["date"]
    head = f"{label} · {WEEKDAYS_SHORT[d.weekday()]} {d.day}."
    draw_text_top(draw, (x0, y), head, fh, YELLOW)
    if wx and not wx_line:
        _tomorrow_weather(img, draw, wx, x0, x1, y + cap_height(draw, fh) // 2,
                          inline_xl=x0 + text_w(draw, head, fh) + 10)
    y += cap_height(draw, fh) + 8
    if wx_line:
        _tomorrow_weather(img, draw, wx, x0, x1, y)
        y += WX_LINE_H
    kw = dict(size=15, icon_size=16, chip_d=16, max_lines=1, pad=3)
    shown = 0
    for ev in day["events"]:
        h = event_row(img, draw, x0, y, x1 - x0, ev, draw_it=False, **kw)
        if y + h > bottom - (18 if shown < len(day["events"]) - 1 else 0):
            break
        event_row(img, draw, x0, y, x1 - x0, ev, color=WHITE, bg=BLACK, **kw)
        y += h
        shown += 1
    if len(day["events"]) > shown:
        draw_text_top(draw, (x0, y + 2), f"+ {len(day['events']) - shown} til", f_tiny(13), YELLOW)
    return True


def month_height(today):
    """Height of the mini month block: header + weekday row + one row per week."""
    import calendar
    weeks = len(calendar.Calendar(0).monthdatescalendar(today.year, today.month))
    return 7 + 17 + 15 + weeks * 13 + 6


def _month(draw, today, event_dates, top):
    """Mini month calendar in the black panel, from y=top (height month_height())."""
    import calendar
    x0, x1 = 18, HERO_W - 16
    cw = (x1 - x0) // 7
    f_h, f_d = f_bold(13), f_tiny(12)
    draw.rectangle([x0, top, x1, top], fill=WHITE)
    y = top + 7
    from designs.common import MONTHS
    draw_text_top(draw, (x0, y), MONTHS[today.month - 1].capitalize(), f_h, WHITE)
    y += 17
    for i, wd in enumerate("MTOTFLS"):
        draw_text_top(draw, (x0 + i * cw + cw // 2 - text_w(draw, wd, f_d) // 2, y), wd, f_d,
                      RED if i >= 5 else WHITE)
    y += 15
    rh = 13
    for week in calendar.Calendar(0).monthdatescalendar(today.year, today.month):
        for i, d in enumerate(week):
            if d.month != today.month:
                continue
            cx = x0 + i * cw + cw // 2
            txt = str(d.day)
            tw = text_w(draw, txt, f_d)
            if d == today:
                draw.rectangle([cx - 10, y - 2, cx + 10, y + 11], fill=WHITE)
                draw_text_top(draw, (cx - tw // 2, y), txt, f_d, BLACK)
            else:
                draw_text_top(draw, (cx - tw // 2, y), txt, f_d, RED if i >= 5 else WHITE)
            if d in event_dates and d != today and d > today:
                draw.rectangle([cx + tw // 2 + 2, y + 1, cx + tw // 2 + 4, y + 3], fill=YELLOW)
        y += rh


ROLLING_WEEKS = 5


def month_weeks(today, rolling=False):
    """The weeks the month calendar shows: the calendar month, or (rolling) five weeks
    starting with the current week, so there are no dead past weeks."""
    import calendar
    if not rolling:
        return calendar.Calendar(0).monthdatescalendar(today.year, today.month)
    start = today - timedelta(days=today.weekday())
    return [[start + timedelta(days=7 * k + i) for i in range(7)] for k in range(ROLLING_WEEKS)]


def month_heading(today, rolling=False):
    """'November 2026', or for rolling weeks over two months 'November – desember'
    ('Desember – januar 2027' over New Year)."""
    if not rolling:
        return f"{MONTHS[today.month - 1].capitalize()} {today.year}"
    weeks = month_weeks(today, True)
    a, b = weeks[0][0], weeks[-1][-1]
    if (a.year, a.month) == (b.year, b.month):
        return f"{MONTHS[a.month - 1].capitalize()} {a.year}"
    return f"{MONTHS[a.month - 1].capitalize()} – {MONTHS[b.month - 1]}" + (f" {b.year}" if b.year != a.year else "")


def _light_month_metrics(today, big, mid=False, rolling=False):
    weeks = len(month_weeks(today, rolling))
    rh = 40 if big else 22 if mid else 16
    return weeks, rh, 26 + 18 + weeks * rh + 6


WEEKDAY_HEAD = ["Ma", "Ti", "On", "To", "Fr", "Lø", "Sø"]


def _month_light(img, draw, today, days, x, y, w, big=False, mid=False, rolling=False):
    """Month calendar on the white side. Big: week numbers and a dot per person with events.
    Mid: the small one with more space between the weeks (above the 'Skoledag' box).
    Rolling: five weeks from the current week instead of the calendar month; days already
    past are lighter, and (big) the first of the next month gets a small month label."""
    weeks, rh, h = _light_month_metrics(today, big, mid, rolling)
    fh = f_bold(18 if big else 15)
    draw_text_top(draw, (x, y + 2), ellipsize(draw, month_heading(today, rolling), fh, w), fh, BLACK)
    draw.rectangle([x, y + 22, x + w, y + 23], fill=BLACK)
    wk_w = 26 if big else 0
    cw = (w - wk_w) / 7
    f_wd = f_tiny(13 if big else 12)
    f_d = f_bold(17) if big else f_tiny(13)
    f_past = f_body(15) if big else f_light(13)
    yy = y + 30
    if big:
        draw_text_top(draw, (x, yy), "uke", f_tiny(11), BLACK)
    for i, wd in enumerate(WEEKDAY_HEAD):
        cx = x + wk_w + i * cw + cw / 2
        draw_text_top(draw, (cx - text_w(draw, wd, f_wd) / 2, yy), wd, f_wd, RED if i >= 5 else BLACK)
    yy += 18
    info = {}
    for d in days:
        people = []
        for e in d["events"]:
            for _l, col in e.get("people") or []:
                if col not in people:
                    people.append(col)
        info[d["date"]] = (people, bool(d["events"]), any(e.get("is_holiday") for e in d["events"]))
    for k, week in enumerate(month_weeks(today, rolling)):
        if big:
            wn = str(week[0].isocalendar()[1])
            draw_text_top(draw, (x + 2, yy + 3), wn, f_tiny(12), BLACK)
        for i, d in enumerate(week):
            if not rolling and d.month != today.month:
                continue
            cx = x + wk_w + i * cw + cw / 2
            people, any_ev, off = info.get(d, ([], False, False))
            weekend = RED if i >= 5 or off else BLACK
            if rolling and big and d.day == 1 and k > 0:     # (not in the top row: the weekday names are there)
                ml, fm = MONTHS_SHORT[d.month - 1], f_tiny(11)
                draw_text_top(draw, (cx - text_w(draw, ml, fm) / 2, yy - 12), ml, fm, weekend)
            txt = str(d.day)
            fd = f_past if rolling and d < today else f_d
            tw = text_w(draw, txt, fd)
            th = cap_height(draw, f_d)
            if d == today:
                pad = 4 if big else 2
                draw.rectangle([cx - tw / 2 - pad - 2, yy - pad, cx + tw / 2 + pad + 2, yy + th + pad], fill=BLACK)
                draw_text_top(draw, (cx - tw / 2, yy), txt, fd, WHITE)
            else:
                draw_text_top(draw, (cx - tw / 2, yy + th - cap_height(draw, fd)), txt, fd, weekend)
            if d > today and any_ev:
                if big:
                    cols = people[:4] or [BLACK]
                    step = 9 if len(cols) < 4 else 8          # four dots still stay inside the cell
                    dx0 = cx - (len(cols) * step - step + 7) / 2
                    for j, col in enumerate(cols):
                        draw.ellipse([dx0 + j * step, yy + th + 5, dx0 + j * step + 7, yy + th + 12], fill=col,
                                     outline=chip_ring(col), width=1)
                else:
                    draw.rectangle([cx + tw / 2 + 2, yy + 1, cx + tw / 2 + 4, yy + 3], fill=BLACK)
        yy += rh
    return h


def _upcoming(img, draw, x, y, w, bottom, days):
    """'Kommer': one line per event on days not shown in the list. Returns y after."""
    fh = f_bold(15)
    if bottom - y < 44:
        return y
    draw_text_top(draw, (x, y + 2), "Kommer", fh, BLACK)
    draw.rectangle([x, y + 21, x + w, y + 22], fill=BLACK)
    y += 28
    f, ft = f_body(14), f_tiny(13)
    shown = 0
    for day in days:
        for ev in day["events"]:
            if y + 20 > bottom:
                return y
            d = day["date"]
            red = is_red_day(d, day["events"])
            lab = f"{WEEKDAYS_SHORT[d.weekday()].lower()} {d.day}."
            draw_text_top(draw, (x, y + 2), lab, ft, RED if red else BLACK)
            chips = ev.get("people") or []
            tx = x + 52
            title_w = x + w - tx - len(chips) * 17
            draw_text_top(draw, (tx, y), ellipsize(draw, ev["title"], f, title_w), f, BLACK)
            cx = x + w - len(chips) * 17 + 1
            for letter, col in chips:
                person_chip(draw, cx, y + cap_height(draw, f) // 2, letter, col, 15)
                cx += 17
            y += 20
            shown += 1
    if not shown:
        draw_text_top(draw, (x, y), "Ingenting mer de neste dagene", f_body(14), BLACK)
        y += 20
    return y + 6


def _chores(img, draw, x, y, w, bottom, chores):
    """'Denne uka': the rota from the admin page, one line per task with the person's chip."""
    from designs.moments import COLOR
    if not chores or bottom - y < 44:
        return y
    fh = f_bold(15)
    draw_text_top(draw, (x, y + 2), "Denne uka", fh, BLACK)
    draw.rectangle([x, y + 21, x + w, y + 22], fill=BLACK)
    y += 28
    f = f_body(14)
    for c in chores:
        if y + 20 > bottom:
            break
        draw_text_top(draw, (x, y), ellipsize(draw, c["task"], f, w // 2 - 4), f, BLACK)
        person_chip(draw, x + w // 2, y + cap_height(draw, f) // 2, c["letter"], COLOR.get(c["color"], BLACK), 15)
        draw_text_top(draw, (x + w // 2 + 22, y), ellipsize(draw, c["name"], f, w // 2 - 24), f, BLACK)
        y += 20
    return y + 6


def _bolt(draw, x, y, s, col):
    draw.polygon([(x + s * .55, y), (x + s * .15, y + s * .55), (x + s * .45, y + s * .55), (x + s * .3, y + s),
                  (x + s * .85, y + s * .4), (x + s * .55, y + s * .4), (x + s * .75, y)], fill=col)


def _energy(img, draw, x, y, w, bottom, energy, car=None):
    """Evening view: 'Strøm og bil' - the car's battery (if known) and electricity, 30 days vs. last year."""
    from designs.common import BLUE, GREEN
    if not energy or bottom - y < 90:
        return y
    draw_text_top(draw, (x, y + 2), "Strøm og bil" if car else "Strøm", f_bold(15), BLACK)
    draw.rectangle([x, y + 21, x + w, y + 22], fill=BLACK)
    y += 30
    if car and car.get("pct") is not None:
        _bolt(draw, x, y - 1, 16, BLACK)
        draw_text_top(draw, (x + 20, y), "Bilen", f_body(14), BLACK)
        draw.rectangle([x + 70, y - 2, x + 140, y + 16], outline=BLACK, width=2)
        draw.rectangle([x + 141, y + 4, x + 144, y + 10], fill=BLACK)
        draw.rectangle([x + 73, y + 1, x + 73 + int(64 * car["pct"] / 100), y + 13],
                       fill=GREEN if car["pct"] >= 30 else RED)
        draw_text_top(draw, (x + 150, y), f"{car['pct']:.0f} %", f_bold(15), BLACK)
        y += 22
        if car.get("note"):
            draw_text_top(draw, (x + 20, y), car["note"], f_tiny(13), BLACK)
            y += 18
        y += 6
    f = f_body(14)
    draw_text_top(draw, (x, y), f"Siste 30 dager: {energy['kwh']:,} kWh".replace(",", " "), f, BLACK)
    if energy.get("pct") is not None:
        pct = f"{energy['pct']:+d} %".replace("-", "−")
        draw_text_top(draw, (x + w - text_w(draw, pct, f_bold(15)), y), pct, f_bold(15),
                      GREEN if energy["pct"] <= 0 else RED)
        y += 18
        draw_text_top(draw, (x, y), "mot samme periode i fjor" if energy.get("against", "i fjor") == "i fjor"
                      else f"mot {energy['against']}", f_tiny(12), BLACK)
    y += 20
    yc = energy.get("year_cost")
    if yc and bottom - y >= 36 + 18 + 40:      # only if the chart still gets 40 px below it
        kr = lambda v: f"{v:,} kr".replace(",", " ")     # noqa: E731
        y += 2
        draw_text_top(draw, (x, y), f"Hittil i år: {kr(yc['cost'])}", f, BLACK)
        if yc.get("estimate"):
            est = f"ca. {kr(round(yc['estimate'], -2))}"
            draw_text_top(draw, (x + w - text_w(draw, est, f_bold(15)), y), est, f_bold(15), BLACK)
            note = f"anslag hele {yc['year']}"
            draw_text_top(draw, (x + w - text_w(draw, note, f_tiny(12)), y + 18), note, f_tiny(12), BLACK)
        draw_text_top(draw, (x, y + 18), "Norgespris + nettleie" if yc.get("nettleie")
                      else "Norgespris, uten nettleie", f_tiny(12), BLACK)
        y += 38
    this, last = energy.get("days") or [], energy.get("last_year") or []
    vals = [v for v in this + last if v]
    ch = min(70, bottom - y - 18)
    if vals and ch >= 24:
        mx, bw = max(vals), w / max(1, len(this))
        for i, v in enumerate(this):
            bx = x + i * bw
            if v:
                draw.rectangle([bx + 1, y + ch - ch * v / mx, bx + bw - 1, y + ch], fill=BLUE)
            ly = last[i] if i < len(last) else None
            if ly:
                draw.line([bx, y + ch - ch * ly / mx, bx + bw, y + ch - ch * ly / mx], fill=BLACK, width=2)
        y += ch + 3
        draw.rectangle([x, y + 2, x + 9, y + 11], fill=BLUE)
        draw_text_top(draw, (x + 13, y), "i år", f_tiny(12), BLACK)
        if any(last):
            draw.line([x + 50, y + 6, x + 62, y + 6], fill=BLACK, width=2)
            draw_text_top(draw, (x + 66, y), "i fjor", f_tiny(12), BLACK)
        y += 18
    return y + 4


HUSK_RE = re.compile(r"\b(husk|ta med|ha med|ta på|må ha)\b", re.I)


def _husk(img, draw, x, y, w, bottom, days):
    """'Husk denne uka': reminders/things to bring until Sunday + next waste pickups. Returns y after."""
    if bottom - y < 50:
        return y
    today = days[0]["date"]
    end = today + timedelta(days=6 - today.weekday())       # this week (until Sunday)
    items, seen = [], set()
    for day in days:
        if day["date"] > end:
            break
        for ev in day["events"]:
            t = ev["title"]
            if not HUSK_RE.search(t) or t in seen:
                continue
            seen.add(t)
            t = re.sub(r"^husk denne uka:\s*", "", t, flags=re.I)
            t = re.sub(r"^.*?\b(husk|ta med)\b\s*", lambda m: m.group(1).capitalize() + " ", t, count=1, flags=re.I) \
                if not t.lower().startswith(("ta med", "husk")) else t
            when = "" if day["date"] == today or "denne uka" in ev["title"].lower() \
                else f"{WEEKDAYS_SHORT[day['date'].weekday()].lower()}: "
            items.append((when + t[0].upper() + t[1:], ev.get("people") or []))
    pickups = []
    for day in days:
        for ev in day["events"]:
            if is_waste(ev):
                lab = waste_label(ev)
                if lab not in [p[0] for p in pickups]:
                    pickups.append((lab, day["date"]))
    if not items and not pickups:
        return y
    fh = f_bold(15)
    draw_text_top(draw, (x, y + 2), "Husk denne uka", fh, BLACK)
    draw.rectangle([x, y + 21, x + w, y + 22], fill=BLACK)
    y += 31
    f = f_body(14)
    ch = cap_height(draw, f)
    line_h, gap = ch + 9, 9            # line height within a point, space between points
    for text, people in items:
        cw = len(people) * 17
        lines = wrap(draw, text, f, w - 14 - cw, 2)
        need = len(lines) * line_h - 9 + ch // 2 + gap
        if y + need > bottom - (24 if pickups else 0):
            break
        draw.ellipse([x + 1, y + ch // 2 - 2, x + 6, y + ch // 2 + 3], fill=BLACK)
        for k, ln in enumerate(lines):
            draw_text_top(draw, (x + 12, y + k * line_h), ln, f, BLACK)
        cx = x + w - cw + 1
        for letter, col in people:
            person_chip(draw, cx, y + ch // 2, letter, col, 15)
            cx += 17
        y += need
    pickups = pickups[:3]
    if pickups and items:
        y += 2
    labels = [f"{lab} {WEEKDAYS_SHORT[d.weekday()].lower()} {d.day}." for lab, d in pickups]
    if pickups and y + 21 * len(pickups) <= bottom:      # one pickup per line when there is room
        for t in labels:
            paste_icon(img, "trash-2", x, y - 1, 15, BLACK)
            draw_text_top(draw, (x + 20, y + 1), ellipsize(draw, t, f_body(14), w - 20), f_body(14), BLACK)
            y += 21
    elif pickups and y + 20 <= bottom:
        txt = "  ·  ".join(labels)
        paste_icon(img, "trash-2", x, y - 1, 15, BLACK)
        draw_text_top(draw, (x + 20, y + 1), ellipsize(draw, txt, f_tiny(13), w - 20), f_tiny(13), BLACK)
        y += 22
    return y + 6


def _school(img, draw, x, y, w, bottom, rows, title):
    """'Skoledag i dag/i morgen': per child start, lunch and end, then the lessons. Returns y after."""
    if not rows or bottom - y < 60:
        return y
    draw_text_top(draw, (x, y + 2), title, f_bold(15), BLACK)
    draw.rectangle([x, y + 21, x + w, y + 22], fill=BLACK)
    y += 30
    fb, fl, ft = f_bold(15), f_body(14), f_tiny(13)
    ch = cap_height(draw, fb)
    for r in rows:
        if y + 22 > bottom:
            break
        person_chip(draw, x, y + ch // 2, r["letter"], r["color"], 17)
        draw_text_top(draw, (x + 22, y), r["name"], fb, BLACK)
        if r["off"]:
            draw_text_top(draw, (x + w - text_w(draw, "Fri", fb), y), "Fri", fb, RED)
            y += 21
            note = r["note"] if r["note"] and r["note"].lower() != "fri" else ""
            if note and y + 17 <= bottom:
                draw_text_top(draw, (x + 22, y), ellipsize(draw, note, ft, w - 22), ft, BLACK)
                y += 17
            y += 6
            continue
        # right-aligned: 09:00  [food] 10:50  14:45  - the end inverted when earlier than usual
        xr = x + w
        if r["end"]:
            tw = text_w(draw, r["end"], fb)
            if r["early"]:
                draw.rectangle([xr - tw - 6, y - 3, xr, y + ch + 4], fill=BLACK)
                draw_text_top(draw, (xr - tw - 3, y), r["end"], fb, WHITE)
                xr -= tw + 6
            else:
                draw_text_top(draw, (xr - tw, y), r["end"], fb, BLACK)
                xr -= tw
        if r["lunch"]:
            tw = text_w(draw, r["lunch"], fl)
            draw_text_top(draw, (xr - 10 - tw, y), r["lunch"], fl, BLACK)
            paste_icon(img, "food", xr - 10 - tw - 17, y - 2, 15, BLACK)
            xr -= 10 + tw + 17
        if r["start"]:
            sep = "–" if not r["lunch"] and r["end"] else ""
            t = r["start"] + sep
            draw_text_top(draw, (xr - (8 if not sep and r["end"] else 0) - text_w(draw, t, fb), y), t, fb, BLACK)
        y += 21
        lines = wrap(draw, " · ".join(r["lessons"]), ft, w - 22, 2) if r["lessons"] else []
        for ln in lines:
            if y + 17 > bottom:
                break
            draw_text_top(draw, (x + 22, y), ln, ft, BLACK)
            y += 17
        for kind, text in r.get("notes", [])[:3]:      # turdag, gym, things to bring
            if y + 17 > bottom:
                break
            paste_icon(img, SCHOOL_ICONS.get(kind, "bell"), x + 22, y - 1, 14, BLACK)
            draw_text_top(draw, (x + 40, y), ellipsize(draw, text, ft, w - 40), ft, BLACK)
            y += 17
        y += 6
    return y + 2


SCHOOL_ICONS = {"trip": "map", "gym": "gymnastics", "bring": "shopping-bag"}


def _with_school_husk(days, data, skip):
    """The weekly letters' reminders and things to bring (kept out of Google Calendar) added to the
    days for 'Husk denne uka'; `skip` = the day already shown in the 'Skoledag' box."""
    if not data.get("timetable") or not days:
        return days
    from school.timetable import husk_events
    start = days[0]["date"]
    extra = husk_events(data["timetable"], data.get("people") or [], start,
                        start + timedelta(days=6 - start.weekday()), skip=skip)
    return [dict(d, events=extra.get(d["date"], []) + d["events"]) if d["date"] in extra else d for d in days]


def _weather_strip(img, draw, x, y, w, bottom, days):
    """Next five days: weekday, icon, max/min. Returns y after."""
    days = [d for d in days if d.get("weather")][:5]
    if not days or bottom - y < 28 + 78:     # heading + labels, icons, max and min
        return y
    fh = f_bold(15)
    draw_text_top(draw, (x, y + 2), "Været", fh, BLACK)
    draw.rectangle([x, y + 21, x + w, y + 22], fill=BLACK)
    y += 28
    cw = w / len(days)
    for i, day in enumerate(days):
        cx = x + i * cw + cw / 2
        d, wt = day["date"], day["weather"]
        lab = WEEKDAYS_SHORT[d.weekday()]
        f = f_tiny(13)
        draw_text_top(draw, (cx - text_w(draw, lab, f) / 2, y), lab, f, RED if d.weekday() >= 5 else BLACK)
        paste_icon(img, weather_icon_name(wt.get("symbol")), cx - 12, y + 16, 24, BLACK)
        t = f"{wt['tmax']:.0f}°"
        fb = f_bold(14)
        draw_text_top(draw, (cx - text_w(draw, t, fb) / 2, y + 45), t, fb, BLACK)
        t2 = f"{wt['tmin']:.0f}°"
        draw_text_top(draw, (cx - text_w(draw, t2, f) / 2, y + 63), t2, f, BLACK)
    return y + 82


def render(data, opts=None):
    """
    opts (all optional, default off):
      collapse  - repeated all-day events shown once with '(til ...)'
      tomorrow  - 'I morgen' block in the black panel when there is room
      month     - mini month calendar at the bottom of the black panel
      morning   - day headers show the temperature at 08 instead of the max
      evening_upcoming - keep «Kommer» in the evening instead of electricity (Tibber)
      energy_allday    - show electricity instead of «Kommer» all day, not only in the evening
      school    - 'Skoledag' box (timetable from the weekly letters) under a smaller month (month_column)
      month_classic - the white-side month shows the calendar month instead of five weeks from this week
    """
    import os
    if opts is None:
        raw = (os.environ.get("DESIGN_OPTIONS") or "").replace("+", ",").replace(" ", ",")
        opts = {k: True for k in raw.split(",") if k}
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    days = [dict(d) for d in data["days"]]
    if not opts.get("advice"):
        for d in days[:2]:
            if d.get("weather") and d["weather"].get("advice"):
                d["weather"] = {k: v for k, v in d["weather"].items() if k != "advice"}

    # Evening mode: after EVENING_HOUR the big panel shows tomorrow
    evening = False
    tonight = None
    now = data.get("now")
    if opts.get("evening") and now is not None and len(days) > 1:
        if now.hour >= int(os.environ.get("EVENING_HOUR", "17")):
            evening = True
            # what's left of today (timed events from now on) stays visible as "I kveld"
            left = [e for e in days[0]["events"]
                    if (e.get("sort_time") or e.get("time")) and (e.get("sort_time") or e.get("time")) >= now.strftime("%H:%M")]
            if left:
                tonight = dict(days[0], events=left, label="I kveld", weather=None)
            days = days[1:]
            days[0] = dict(days[0], heading="I morgen")

    husk_days = days
    if opts.get("husk") and opts.get("month_column"):
        # week reminders live in the "Husk denne uka" box, not in the day panels
        days = [dict(d, events=[e for e in d["events"] if not e["title"].lower().startswith("husk denne uka")])
                for d in days]

    # Birthdays, holidays and other special days ("moments"); weather warnings always
    banner, extra = None, []
    from designs import moments as _mo
    warn_banner = _mo.warning_banner(data.get("warnings"), days[0]["date"])
    if opts.get("moments"):
        from designs import moments
        people = data.get("people") or []
        banner = None if evening else moments.banner(days[0], people, dates=data.get("dates"),
                                                     first_snow=bool(data.get("first_snow")))
        if banner and banner.get("birthday"):   # the banner says it; drop "Nora 10 år" from today's list
            names = [n.lower() for n in banner["birthday"]]
            days[0] = dict(days[0], events=[e for e in days[0]["events"] if not (
                any(n in e["title"].lower() for n in names)
                and ("år" in e["title"] or "bursdag" in e["title"].lower()))])
        extra = moments.lines(days, people, now=now, dinner_question=data.get("dinner_question", ""),
                              evening=evening, spond_pending=data.get("spond_pending") or [],
                              countdowns=data.get("countdowns") or [], aurora_kp=data.get("aurora_kp"),
                              dates=data.get("dates") or [])
        days = moments.birthday_events(days, people, skip=days[0]["date"] if banner and banner.get("birthday")
                                       else None)
    # a red warning beats everything, an orange one everything but a birthday
    if warn_banner and (warn_banner["warning_level"] == 3 or not (banner and banner.get("birthday"))):
        banner = warn_banner
    extra = (_mo.warning_lines(data.get("warnings"), days[0]["date"],
                               skip_banner=banner if banner is warn_banner else None) + extra)[:2]

    if opts.get("collapse"):
        days = collapse_repeats(days)

    # The black panel fills in priority order: today's events (all of them if
    # possible), then the month calendar, then "I morgen" - each only if it fits.
    reserve = 0
    month_white = opts.get("month_right") or opts.get("month_column")
    rolling = not opts.get("month_classic")     # five weeks from this week, unless the calendar month is chosen
    if opts.get("month") and not month_white:
        scratch = Image.new("RGB", (W, H), WHITE)
        y_full = _today(scratch, ImageDraw.Draw(scratch), days[0], "", battery=None, banner=banner,
                        extra_lines=extra)
        mh = month_height(data["today"])
        if (H - 26) - y_full >= mh + 4:
            reserve = mh
    y_end = _today(img, draw, days[0], data.get("updated", ""), battery=data.get("battery"),
                   reserve_bottom=reserve, banner=banner, extra_lines=extra, car=data.get("car"))
    if reserve:
        _month(draw, data["today"], {d["date"] for d in days if d["events"]}, H - 26 - reserve)

    list_days = days[1:]
    if opts.get("tomorrow") and len(days) > 1:
        if _tomorrow(img, draw, days[1], y_end, H - 26 - reserve,
                     label="Overmorgen" if evening else "I morgen"):
            list_days = days[2:]

    if tonight is not None:
        list_days = [tonight] + list_days

    gap = 12
    left = HERO_W + gap
    col_w = (W - left - gap - 8) // 2
    cols = [left, left + col_w + gap]
    bottoms = [H - 6, H - 6]
    below = None
    school_rows = []
    if opts.get("school") and opts.get("month_column") and data.get("timetable"):
        from school.timetable import day_rows
        school_rows = day_rows(data["timetable"], data.get("people") or [], days[0])
    if opts.get("month_column"):
        # the whole right column is a large month calendar; the day list uses the left column
        # (a smaller one on school days when the 'Skoledag' box is on)
        mh = _month_light(img, draw, data["today"], days, cols[1], 8, col_w, big=not school_rows,
                          mid=bool(school_rows), rolling=rolling)
        below = (cols[1], 8 + mh + 10)
        cols, bottoms = cols[:1], bottoms[:1]
    elif opts.get("month_right"):
        _w, _r, mh = _light_month_metrics(data["today"], False, rolling=rolling)
        _month_light(img, draw, data["today"], days, cols[1], H - mh - 4, col_w, rolling=rolling)
        bottoms[1] = H - mh - 12
    col_i, y = 0, 8
    last_shown = None
    for day in list_days:
        h = _day_section(img, draw, 0, 0, col_w, day, measure=True)
        if y + h > bottoms[col_i]:
            col_i += 1
            y = 8
            if col_i >= len(cols):
                break
        _day_section(img, draw, cols[col_i], y, col_w, day, morning=bool(opts.get("morning")))
        last_shown = day["date"]
        y += h

    # Space under the large month: "Kommer" (events after the listed days) and/or weather
    if below is not None:
        bx, by = below
        later = [d for d in days if last_shown is None or d["date"] > last_shown]
        by = _school(img, draw, bx, by, col_w, H - 6, school_rows,
                     "Skoledag i morgen" if evening else "Skoledag i dag")
        by = _chores(img, draw, bx, by, col_w, H - 6, data.get("chores") or [])
        for key in [k for k in ("husk", "upcoming", "weather5") if opts.get(k)]:
            if key == "husk":
                by = _husk(img, draw, bx, by, col_w, H - 6,
                           _with_school_husk(husk_days, data, days[0]["date"] if school_rows else None))
            elif key == "upcoming" and data.get("energy") and not opts.get("evening_upcoming") \
                    and (evening or opts.get("energy_allday")):
                # evening: electricity and car instead (unless the admin page keeps «Kommer»)
                by = _energy(img, draw, bx, by, col_w, H - 6, data["energy"], data.get("car"))
            elif key == "upcoming":
                by = _upcoming(img, draw, bx, by, col_w, H - 6, later)
            else:
                by = _weather_strip(img, draw, bx, by, col_w, H - 6, days[1:])
    return quantize(img)
