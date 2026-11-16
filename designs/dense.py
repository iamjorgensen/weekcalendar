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
def _today(img, draw, day, updated, accent=RED, battery=None):
    draw.rectangle([0, 0, HERO_W, H], fill=BLACK)
    x0, x1 = 18, HERO_W - 16
    d = day["date"]
    red = is_red_day(d, day["events"])

    f_day, f_num, f_mon = f_bold(26), f_bold(50), f_body(21)
    y = 14
    draw_text_top(draw, (x0, y), WEEKDAYS[d.weekday()], f_day, accent if red else WHITE)
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

    draw.rectangle([x0, y, x1, y + 1], fill=WHITE)
    y += 7

    bottom = H - 26
    shown = 0
    for ev in day["events"]:
        kw = dict(size=16, icon_size=18, chip_d=18, max_lines=2, pad=3)
        h = event_row(img, draw, x0, y, x1 - x0, ev, draw_it=False, **kw)
        if y + h > bottom:
            break
        event_row(img, draw, x0, y, x1 - x0, ev, color=WHITE, bg=BLACK, **kw)
        y += h
        shown += 1
    rest = len(day["events"]) - shown
    if rest:
        draw_text_top(draw, (x0, y + 2), f"+ {rest} til", f_tiny(14), YELLOW)
    if not day["events"]:
        draw_text_top(draw, (x0, y + 4), "Ingen avtaler i dag", f_body(16), WHITE)

    f_up = f_tiny(12)
    up = f"Oppdatert {updated}"
    draw_text_top(draw, (x1 - text_w(draw, up, f_up), H - 17), up, f_up, WHITE)
    if battery is not None:
        draw_battery(draw, x0, H - 17 + cap_height(draw, f_up) // 2, battery, WHITE)


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


def _day_section(img, draw, x, y, w, day, measure=False):
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

    label = f"{WEEKDAYS_SHORT[d.weekday()]} {d.day}. {MONTHS_SHORT[d.month - 1]}"
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


def render(data):
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    days = data["days"]
    _today(img, draw, days[0], data.get("updated", ""), battery=data.get("battery"))

    gap = 12
    left = HERO_W + gap
    col_w = (W - left - gap - 8) // 2
    cols = [left, left + col_w + gap]
    col_i, y = 0, 8
    for day in days[1:]:
        h = _day_section(img, draw, 0, 0, col_w, day, measure=True)
        if y + h > H - 6:
            col_i += 1
            y = 8
            if col_i >= len(cols):
                break
        _day_section(img, draw, cols[col_i], y, col_w, day)
        y += h
    return quantize(img)
