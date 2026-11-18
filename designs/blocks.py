"""Reusable building blocks for the designs: event rows, day headers, weather."""
from designs.common import (
    BLACK, RED, WHITE, WEEKDAYS, WEEKDAYS_SHORT, MONTHS, MONTHS_SHORT,
    cap_height, draw_text_top, ellipsize, f_body, f_bold, f_tiny, paste_icon,
    person_chip, text_w, weather_icon_name, wrap,
)


def event_row(img, draw, x, y, w, ev, size=17, icon_size=18, max_lines=2,
              time_w=None, chip_d=18, draw_it=True, color=BLACK, bg=WHITE, pad=5):
    """
    One event. Timed:   [time] [icon] title........ (A)(S)
               All-day: [icon] title.............. (A)(S)
    The time is right-aligned in a fixed column, so the titles of timed events share one
    left edge; a timed event with no icon gets a small dot in the icon slot. All-day events
    are not on the timeline and start at x, using the full width.
    Returns the row height. With draw_it=False it only measures (same height as drawn).
    """
    fb = f_body(size)
    ft = f_tiny(size - 2)
    ch = cap_height(draw, fb)
    line_gap = int(size * 0.45)

    time = ev.get("time") or ""
    tw = time_w if time_w is not None else text_w(draw, "00:00", ft)
    ix = x + tw + 7 if time else x            # icon slot
    tx = ix + icon_size + 6                   # title

    chips = ev.get("people") or []
    chips_w = len(chips) * (chip_d + 3)
    title_w = max(30, x + w - tx - chips_w - (4 if chips else 0))

    lines = wrap(draw, ev.get("title", ""), fb, title_w, max_lines)
    block_h = ch * len(lines) + line_gap * (len(lines) - 1)
    row_h = max(block_h, icon_size, chip_d if chips else 0) + pad * 2

    if not draw_it:
        return row_h

    top = y + (row_h - block_h) // 2
    mid = top + ch // 2                       # icon, dot and chips centre on the first line
    if time:
        draw_text_top(draw, (x + tw - text_w(draw, time, ft), top + ch - cap_height(draw, ft)), time, ft, color)
    drawn = ev.get("icon") and paste_icon(img, ev["icon"], ix, mid - icon_size // 2, icon_size, color)
    if not drawn and time:
        c = ix + icon_size // 2
        draw.ellipse([c - 2, mid - 2, c + 2, mid + 2], fill=color)
    for i, ln in enumerate(lines):
        draw_text_top(draw, (tx, top + i * (ch + line_gap)), ln, fb, color)
    chip_x = x + w - chips_w + 3
    for letter, col in chips:
        person_chip(draw, chip_x, mid, letter, col, chip_d, bg=bg)
        chip_x += chip_d + 3
    return row_h


def day_label(d, short=True):
    if short:
        return f"{WEEKDAYS_SHORT[d.weekday()]} {d.day}. {MONTHS_SHORT[d.month - 1]}"
    return f"{WEEKDAYS[d.weekday()]} {d.day}. {MONTHS[d.month - 1]}"


def weather_inline(img, draw, right_x, cy, weather, size=15, color=BLACK, show_precip=True):
    """Right-aligned 'icon  -2° / -7°  4 mm' ending at right_x. Returns left x used."""
    if not weather:
        return right_x
    f = f_body(size)
    ch = cap_height(draw, f)
    parts = []
    if show_precip and weather.get("precip", 0) >= 0.5:
        parts.append(f"{weather['precip']:.0f} mm")
    parts.append(f"{weather['tmax']:.0f}° / {weather['tmin']:.0f}°")
    txt = "   ".join(parts)
    tw = text_w(draw, txt, f)
    x = right_x - tw
    draw_text_top(draw, (x, cy - ch // 2), txt, f, color)
    isz = size + 5
    x -= isz + 5
    paste_icon(img, weather_icon_name(weather.get("symbol")), x, cy - isz // 2, isz, color)
    return x
