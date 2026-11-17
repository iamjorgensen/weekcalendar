"""
Concept A2 — "Dense hero": the hero layout squeezed for maximum information.

Differences from hero.py:
  - Today's weather: icon + temp, then morning/day/evening on ONE line, then
    precipitation + wind.
  - Day headers are thinner: date left; waste pickup as a small icon + type
    right after it; weather icon + max temp (+ precipitation if >= 1 mm) right.
  - Waste pickup events are not separate rows in the day list.
  - Two short consecutive events share one line (no icon, time + title + people).
"""
from PIL import Image, ImageDraw

from designs import hero
from designs.blocks import event_row
from designs.common import (
    draw_battery,
    BLACK, RED, WHITE, YELLOW, W, H, MONTHS, WEEKDAYS, WEEKDAYS_SHORT, MONTHS_SHORT,
    cap_height, draw_text_top, ellipsize, f_body, f_bold, f_tiny, is_red_day, paste_icon,
    person_chip, quantize, text_w, weather_icon_name,
)

HERO_W = hero.HERO_W
ROW = dict(size=15, icon_size=15, chip_d=16, max_lines=2, pad=3)

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
def _today(img, draw, day, updated, accent=RED, battery=None, reserve_bottom=0):
    draw.rectangle([0, 0, HERO_W, H], fill=BLACK)
    x0, x1 = 18, HERO_W - 16
    d = day["date"]
    red = is_red_day(d, day["events"])

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

    w = day.get("weather") or {}
    if w:
        isz = 40
        paste_icon(img, weather_icon_name(w.get("symbol")), x0 - 2, y, isz, WHITE)
        f_t = f_bold(28)
        tx = x0 + isz + 10
        draw_text_top(draw, (tx, y + 1), f"{w['tmax']:.0f}°", f_t, WHITE)
        f_s = f_body(15)
        draw_text_top(draw, (tx, y + 1 + cap_height(draw, f_t) + 7),
                      ellipsize(draw, f"{w.get('symbol', '')}  ·  min {w['tmin']:.0f}°", f_s, x1 - tx), f_s, WHITE)
        y += isz + 8

        # morning / day / evening on one line: "Morg. [icon] 4°", spread evenly
        periods = w.get("periods") or []
        if periods:
            f_lbl, f_pt = f_tiny(13), f_bold(15)
            short = {"Morgen": "Morg."}
            parts = []
            for label, ic, temp in periods:
                lab = short.get(label, label)
                t = f"{temp:.0f}°"
                parts.append((lab, ic, t, text_w(draw, lab, f_lbl) + 3 + 18 + 2 + text_w(draw, t, f_pt)))
            space = max(4, ((x1 - x0) - sum(p[3] for p in parts)) // max(1, len(parts) - 1))
            cx = x0
            for lab, ic, t, pw in parts:
                draw_text_top(draw, (cx, y + 4), lab, f_lbl, WHITE)
                lx = cx + text_w(draw, lab, f_lbl) + 3
                paste_icon(img, weather_icon_name(ic), lx, y, 18, WHITE)
                draw_text_top(draw, (lx + 20, y + 3), t, f_pt, WHITE)
                cx += pw + space
            y += 24

        f_det = f_tiny(14)
        items = [("droplet", f"{w.get('precip', 0):.1f} mm"),
                 ("wind", f"{w.get('wind', 0):.0f} m/s {w.get('wind_dir', '')}".strip())]
        col_w = (x1 - x0) // 2
        for i, (ic, txt) in enumerate(items):
            dx = x0 + i * col_w
            paste_icon(img, ic, dx, y - 3, 16, WHITE)
            draw_text_top(draw, (dx + 21, y), txt, f_det, WHITE)
        y += 20
        if w.get("advice"):
            f_adv = f_body(14)
            draw_text_top(draw, (x0, y), ellipsize(draw, w["advice"], f_adv, x1 - x0), f_adv, YELLOW)
            y += 20

    draw.rectangle([x0, y, x1, y + 1], fill=WHITE)
    y += 7

    bottom = H - 26 - reserve_bottom
    shown = 0
    n = len(day["events"])
    for k, ev in enumerate(day["events"]):
        kw = dict(size=16, icon_size=18, chip_d=18, max_lines=2, pad=3)
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
    return y


# ------------------------------------------------------------------ day list
def _compact_width(draw, ev):
    """Width needed to draw ev on one line without icon: 'HH:MM Title (A)(S)'."""
    fb, ft = f_body(ROW["size"]), f_tiny(ROW["size"] - 2)
    w = text_w(draw, ev.get("title", ""), fb)
    if ev.get("time"):
        w += text_w(draw, ev["time"], ft) + 5
    n = len(ev.get("people") or [])
    if n:
        w += 4 + n * (ROW["chip_d"] + 2)
    return w


def _draw_compact(draw, x, y, row_h, ev):
    fb, ft = f_body(ROW["size"]), f_tiny(ROW["size"] - 2)
    ch = cap_height(draw, fb)
    top = y + (row_h - ch) // 2
    cx = x
    if ev.get("time"):
        draw_text_top(draw, (cx, top + ch - cap_height(draw, ft)), ev["time"], ft, BLACK)
        cx += text_w(draw, ev["time"], ft) + 5
    draw_text_top(draw, (cx, top), ev["title"], fb, BLACK)
    cx += text_w(draw, ev["title"], fb) + 4
    for letter, col in ev.get("people") or []:
        person_chip(draw, cx, top + ch // 2, letter, col, ROW["chip_d"])
        cx += ROW["chip_d"] + 2


def _layout_rows(draw, events, w):
    """[(kind, payload, height)] where kind is 'one' (event_row) or 'pair' (two compact events)."""
    half = (w - 10) // 2
    one_h = cap_height(draw, f_body(ROW["size"])) + 2 * ROW["pad"]
    one_h = max(one_h, ROW["chip_d"] + 2 * ROW["pad"])
    rows, i = [], 0
    while i < len(events):
        a = events[i]
        b = events[i + 1] if i + 1 < len(events) else None
        if b is not None and _compact_width(draw, a) <= half and _compact_width(draw, b) <= half:
            rows.append(("pair", (a, b), one_h))
            i += 2
            continue
        rows.append(("one", a, event_row(None, draw, 0, 0, w, a, draw_it=False, **ROW)))
        i += 1
    return rows


def _day_section(img, draw, x, y, w, day, measure=False, morning=False):
    d = day["date"]
    red = is_red_day(d, day["events"])
    col = RED if red else BLACK
    fh = f_bold(15)
    hdr_h = cap_height(draw, fh) + 9

    waste = [e for e in day["events"] if is_waste(e)]
    events = [e for e in day["events"] if not is_waste(e)]
    rows = _layout_rows(draw, events, w)
    total = hdr_h + sum(h for _, _, h in rows) + (6 if rows else 2)
    if measure:
        return total

    label = day.get("label") or f"{WEEKDAYS_SHORT[d.weekday()]} {d.day}. {MONTHS_SHORT[d.month - 1]}"
    draw_text_top(draw, (x, y + 2), label, fh, col)
    cy_mid = y + 2 + cap_height(draw, fh) // 2

    # waste pickup right after the date
    wx = x + text_w(draw, label, fh) + 8
    f_w = f_tiny(12)
    for e in waste:
        paste_icon(img, "trash-2", wx, cy_mid - 7, 14, col)
        lab = waste_label(e)
        draw_text_top(draw, (wx + 15, cy_mid - cap_height(draw, f_w) // 2), lab, f_w, col)
        wx += 15 + text_w(draw, lab, f_w) + 6

    # weather: icon + max temp (+ precipitation if notable), right-aligned
    wthr = day.get("weather")
    if wthr:
        f_t = f_body(14)
        txt = f"{wthr['tmax']:.0f}°"
        if morning and wthr.get("morning") is not None:
            txt = f"kl 8: {wthr['morning']:.0f}°"
        if (wthr.get("precip") or 0) >= 1:
            txt = f"{wthr['precip']:.0f} mm  " + txt
        tw = text_w(draw, txt, f_t)
        tx = x + w - tw
        if tx - 20 > wx:
            draw_text_top(draw, (tx, cy_mid - cap_height(draw, f_t) // 2), txt, f_t, col)
            paste_icon(img, weather_icon_name(wthr.get("symbol")), tx - 19, cy_mid - 8, 16, col)

    draw.rectangle([x, y + hdr_h - 3, x + w, y + hdr_h - 3], fill=col)
    cy = y + hdr_h
    half = (w - 10) // 2
    for kind, payload, h in rows:
        if kind == "pair":
            _draw_compact(draw, x + 2, cy, h, payload[0])
            _draw_compact(draw, x + half + 10, cy, h, payload[1])
        else:
            event_row(img, draw, x, cy, w, payload, **ROW)
        cy += h
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
    if y + need > bottom:
        return False
    y += 4
    draw.rectangle([x0, y, x1, y], fill=WHITE)
    y += 8
    fh = f_bold(15)
    d = day["date"]
    draw_text_top(draw, (x0, y), f"{label} · {WEEKDAYS_SHORT[d.weekday()]} {d.day}.", fh, YELLOW)
    y += cap_height(draw, fh) + 8
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


def render(data, opts=None):
    """
    opts (all optional, default off):
      collapse  - repeated all-day events shown once with '(til ...)'
      tomorrow  - 'I morgen' block in the black panel when there is room
      month     - mini month calendar at the bottom of the black panel
      morning   - day headers show the temperature at 08 instead of the max
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

    if opts.get("collapse"):
        days = collapse_repeats(days)

    # The black panel fills in priority order: today's events (all of them if
    # possible), then the month calendar, then "I morgen" - each only if it fits.
    reserve = 0
    if opts.get("month"):
        scratch = Image.new("RGB", (W, H), WHITE)
        y_full = _today(scratch, ImageDraw.Draw(scratch), days[0], "", battery=None)
        mh = month_height(data["today"])
        if (H - 26) - y_full >= mh + 4:
            reserve = mh
    y_end = _today(img, draw, days[0], data.get("updated", ""), battery=data.get("battery"),
                   reserve_bottom=reserve)
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
    col_i, y = 0, 8
    for day in list_days:
        h = _day_section(img, draw, 0, 0, col_w, day, measure=True)
        if y + h > H - 6:
            col_i += 1
            y = 8
            if col_i >= len(cols):
                break
        _day_section(img, draw, cols[col_i], y, col_w, day, morning=bool(opts.get("morning")))
        y += h
    return quantize(img)
