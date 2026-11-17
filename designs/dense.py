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
import re
from datetime import timedelta

from PIL import Image, ImageDraw

from designs import hero
from designs.blocks import event_row
from designs.common import (
    draw_battery,
    BLACK, RED, WHITE, YELLOW, W, H, MONTHS, WEEKDAYS, WEEKDAYS_SHORT, MONTHS_SHORT,
    cap_height, draw_text_top, ellipsize, f_body, f_bold, f_tiny, is_red_day, paste_icon,
    person_chip, quantize, text_w, weather_icon_name, wrap,
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


def _today_body(img, draw, day, y, x0, x1, updated, battery, reserve_bottom, extra_lines, car=None):
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
        if battery < LOW_BATTERY:     # "Bytt batteri!" next to the battery
            draw_text_top(draw, (x0 + 66, H - 17), "Bytt batteri!", f_bold(12), YELLOW)
    if car and car.get("pct") is not None and not (battery is not None and battery < LOW_BATTERY):
        cx = x0 + 70                  # the car's battery, e.g. "⚡ Bil 64 %"
        _bolt(draw, cx, H - 19, 13, YELLOW)
        draw_text_top(draw, (cx + 16, H - 17), f"Bil {car['pct']:.0f} %", f_bold(12), WHITE)
    return y


LOW_BATTERY = 15


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
        if (b is not None and not a.get("is_holiday") and not b.get("is_holiday")   # days off keep their icon
                and _compact_width(draw, a) <= half and _compact_width(draw, b) <= half):
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
    f_none = f_body(14)
    none_h = 0 if rows else cap_height(draw, f_none) + 10   # "Ingen avtaler" keeps the days apart
    total = hdr_h + sum(h for _, _, h in rows) + (6 if rows else 2) + none_h
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
    if not rows:
        draw_text_top(draw, (x + 2, cy + 3), "Ingen avtaler", f_none, col)
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


def _light_month_metrics(today, big):
    import calendar
    weeks = len(calendar.Calendar(0).monthdatescalendar(today.year, today.month))
    rh = 40 if big else 16
    return weeks, rh, 26 + 18 + weeks * rh + 6


def _month_light(img, draw, today, days, x, y, w, big=False):
    """Month calendar on the white side. Big: week numbers and a dot per person with events."""
    import calendar
    from designs.common import MONTHS
    weeks, rh, h = _light_month_metrics(today, big)
    fh = f_bold(18 if big else 15)
    draw_text_top(draw, (x, y + 2), f"{MONTHS[today.month - 1].capitalize()} {today.year}", fh, BLACK)
    draw.rectangle([x, y + 22, x + w, y + 23], fill=BLACK)
    wk_w = 26 if big else 0
    cw = (w - wk_w) / 7
    f_wd = f_tiny(13 if big else 12)
    f_d = f_bold(17) if big else f_tiny(13)
    yy = y + 30
    if big:
        draw_text_top(draw, (x, yy), "uke", f_tiny(11), BLACK)
    for i, wd in enumerate("MTOTFLS"):
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
    for week in calendar.Calendar(0).monthdatescalendar(today.year, today.month):
        if big:
            wn = str(week[0].isocalendar()[1])
            draw_text_top(draw, (x + 2, yy + 3), wn, f_tiny(12), BLACK)
        for i, d in enumerate(week):
            if d.month != today.month:
                continue
            cx = x + wk_w + i * cw + cw / 2
            txt = str(d.day)
            tw = text_w(draw, txt, f_d)
            th = cap_height(draw, f_d)
            if d == today:
                pad = 4 if big else 2
                draw.rectangle([cx - tw / 2 - pad - 2, yy - pad, cx + tw / 2 + pad + 2, yy + th + pad], fill=BLACK)
                draw_text_top(draw, (cx - tw / 2, yy), txt, f_d, WHITE)
            else:
                off = info.get(d, ([], False, False))[2]
                draw_text_top(draw, (cx - tw / 2, yy), txt, f_d, RED if i >= 5 or off else BLACK)
            people, any_ev, _off = info.get(d, ([], False, False))
            if d > today and any_ev:
                if big and people:
                    n = min(4, len(people))
                    dx0 = cx - (n * 8 - 2) / 2
                    for k, col in enumerate(people[:4]):
                        draw.ellipse([dx0 + k * 8, yy + th + 6, dx0 + k * 8 + 6, yy + th + 12], fill=col)
                elif big:
                    draw.ellipse([cx - 3, yy + th + 6, cx + 3, yy + th + 12], fill=BLACK)
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
    y += 29
    f = f_body(14)
    ch = cap_height(draw, f)
    for text, people in items:
        cw = len(people) * 17
        lines = wrap(draw, text, f, w - 14 - cw, 2)
        need = len(lines) * (ch + 7) + 4
        if y + need > bottom - (22 if pickups else 0):
            break
        draw.ellipse([x + 1, y + ch // 2 - 2, x + 6, y + ch // 2 + 3], fill=BLACK)
        for k, ln in enumerate(lines):
            draw_text_top(draw, (x + 12, y + k * (ch + 7)), ln, f, BLACK)
        cx = x + w - cw + 1
        for letter, col in people:
            person_chip(draw, cx, y + ch // 2, letter, col, 15)
            cx += 17
        y += need
    if pickups and y + 20 <= bottom:
        txt = "  ·  ".join(f"{lab} {WEEKDAYS_SHORT[d.weekday()].lower()} {d.day}." for lab, d in pickups[:3])
        paste_icon(img, "trash-2", x, y - 1, 15, BLACK)
        draw_text_top(draw, (x + 20, y + 1), ellipsize(draw, txt, f_tiny(13), w - 20), f_tiny(13), BLACK)
        y += 22
    return y + 6


def _weather_strip(img, draw, x, y, w, bottom, days):
    """Next five days: weekday, icon, max/min. Returns y after."""
    days = [d for d in days if d.get("weather")][:5]
    if not days or bottom - y < 78:
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
    if opts.get("month_column"):
        # the whole right column is a large month calendar; the day list uses the left column
        mh = _month_light(img, draw, data["today"], days, cols[1], 8, col_w, big=True)
        below = (cols[1], 8 + mh + 10)
        cols, bottoms = cols[:1], bottoms[:1]
    elif opts.get("month_right"):
        _w, _r, mh = _light_month_metrics(data["today"], False)
        _month_light(img, draw, data["today"], days, cols[1], H - mh - 4, col_w)
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
        by = _chores(img, draw, bx, by, col_w, H - 6, data.get("chores") or [])
        for key in [k for k in ("husk", "upcoming", "weather5") if opts.get(k)]:
            if key == "husk":
                by = _husk(img, draw, bx, by, col_w, H - 6, husk_days)
            elif key == "upcoming" and evening and data.get("energy"):   # evening: electricity and car instead
                by = _energy(img, draw, bx, by, col_w, H - 6, data["energy"], data.get("car"))
            elif key == "upcoming":
                by = _upcoming(img, draw, bx, by, col_w, H - 6, later)
            else:
                by = _weather_strip(img, draw, bx, by, col_w, H - 6, days[1:])
    return quantize(img)
