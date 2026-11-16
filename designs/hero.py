"""
Concept A — "Today hero"

Left: a solid black panel for today (big date, rich weather, today's events in
white). Right: the following days as a compact agenda in two columns.
"""
from PIL import Image, ImageDraw

from designs.blocks import day_label, event_row, weather_inline
from designs.common import (
    ellipsize,
    BLACK, RED, WHITE, YELLOW, W, H, MONTHS, WEEKDAYS,
    cap_height, draw_text_top, f_body, f_bold, f_tiny, is_red_day, paste_icon,
    quantize, text_w, weather_icon_name,
)

HERO_W = 286


def _hero(img, draw, day, updated, accent=RED):
    draw.rectangle([0, 0, HERO_W, H], fill=BLACK)
    x0, x1 = 18, HERO_W - 16
    d = day["date"]
    red = is_red_day(d, day["events"])

    # Date: weekday, then big day number + month (compact)
    f_day = f_bold(26)
    f_num = f_bold(50)
    f_mon = f_body(21)
    y = 14
    wd = WEEKDAYS[d.weekday()]
    draw_text_top(draw, (x0, y), wd, f_day, accent if red else WHITE)
    f_wk = f_tiny(15)
    wk = f"uke {d.isocalendar()[1]}"
    draw_text_top(draw, (x1 - text_w(draw, wk, f_wk), y + cap_height(draw, f_day) - cap_height(draw, f_wk)),
                  wk, f_wk, WHITE)
    y += cap_height(draw, f_day) + 11
    num = str(d.day)
    draw_text_top(draw, (x0, y), num, f_num, WHITE)
    nx = x0 + text_w(draw, num, f_num) + 10
    nch = cap_height(draw, f_num)
    mch = cap_height(draw, f_mon)
    draw_text_top(draw, (nx, y + nch - mch), MONTHS[d.month - 1], f_mon, WHITE)
    y += nch + 16

    # Weather: icon + temps, morning/day/evening, then precipitation + wind on one line
    w = day.get("weather") or {}
    if w:
        isz = 46
        paste_icon(img, weather_icon_name(w.get("symbol")), x0 - 2, y, isz, WHITE)
        f_t = f_bold(30)
        tx = x0 + isz + 12
        draw_text_top(draw, (tx, y + 1), f"{w['tmax']:.0f}°", f_t, WHITE)
        f_s = f_body(16)
        draw_text_top(draw, (tx, y + 1 + cap_height(draw, f_t) + 8),
                      ellipsize(draw, f"{w.get('symbol', '')}  ·  min {w['tmin']:.0f}°", f_s, x1 - tx), f_s, WHITE)
        y += isz + 10

        periods = w.get("periods") or []
        if periods:
            cell = (x1 - x0) // len(periods)
            f_lbl = f_tiny(13)
            f_pt = f_bold(17)
            for i, (label, ic, temp) in enumerate(periods):
                cx = x0 + i * cell
                draw_text_top(draw, (cx, y), label, f_lbl, WHITE)
                paste_icon(img, weather_icon_name(ic), cx, y + 17, 22, WHITE)
                draw_text_top(draw, (cx + 27, y + 21), f"{temp:.0f}°", f_pt, WHITE)
            y += 46

        f_det = f_tiny(15)
        items = [("droplet", f"{w.get('precip', 0):.1f} mm"),
                 ("wind", f"{w.get('wind', 0):.0f} m/s {w.get('wind_dir', '')}".strip())]
        col_w = (x1 - x0) // 2
        for i, (ic, txt) in enumerate(items):
            dx = x0 + i * col_w
            paste_icon(img, ic, dx, y - 3, 18, WHITE)
            draw_text_top(draw, (dx + 24, y), txt, f_det, WHITE)
        y += 24

    # Divider
    draw.rectangle([x0, y, x1, y + 1], fill=WHITE)
    y += 8

    # Today's events
    bottom = H - 30
    shown = 0
    for ev in day["events"]:
        h = event_row(img, draw, x0, y, x1 - x0, ev, size=17, icon_size=19, chip_d=19,
                      max_lines=2, draw_it=False, pad=4)
        if y + h > bottom:
            break
        event_row(img, draw, x0, y, x1 - x0, ev, size=17, icon_size=19, chip_d=19,
                  max_lines=2, color=WHITE, bg=BLACK, pad=4)
        y += h
        shown += 1
    rest = len(day["events"]) - shown
    if rest:
        draw_text_top(draw, (x0, y + 2), f"+ {rest} til", f_tiny(14), YELLOW)
    if not day["events"]:
        draw_text_top(draw, (x0, y + 4), "Ingen avtaler i dag", f_body(17), WHITE)

    f_up = f_tiny(12)
    up = f"Oppdatert {updated}"
    draw_text_top(draw, (x1 - text_w(draw, up, f_up), H - 18), up, f_up, WHITE)


ROW = dict(size=15, icon_size=15, chip_d=16, max_lines=2, pad=3)


def _day_section(img, draw, x, y, w, day, measure=False):
    d = day["date"]
    red = is_red_day(d, day["events"])
    fh = f_bold(16)
    hdr_h = cap_height(draw, fh) + 10
    rows = [event_row(img, draw, x, 0, w, ev, draw_it=False, **ROW) for ev in day["events"]]
    gap_after = 7 if rows else 3          # empty days: header only
    total = hdr_h + sum(rows) + gap_after
    if measure:
        return total

    col = RED if red else BLACK
    draw_text_top(draw, (x, y + 2), day_label(d), fh, col)
    weather_inline(img, draw, x + w, y + 2 + cap_height(draw, fh) // 2, day.get("weather"),
                   size=13, color=col, show_precip=True)
    ly = y + hdr_h - 4
    draw.rectangle([x, ly, x + w, ly + 1], fill=col)
    cy = y + hdr_h
    for ev, h in zip(day["events"], rows):
        event_row(img, draw, x, cy, w, ev, **ROW)
        cy += h
    return total


def render(data):
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    days = data["days"]
    _hero(img, draw, days[0], data.get("updated", ""))

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
