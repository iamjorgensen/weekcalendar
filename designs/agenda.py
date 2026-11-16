"""
Concept B — "Agenda" (closest to today's layout, cleaned up)

Two columns of day cards. Solid black headers; red for weekends/holidays;
today's header is yellow so it stands out. Person initials instead of name chips.
"""
from PIL import Image, ImageDraw

from designs.blocks import day_label, event_row, weather_inline
from designs.common import (
    BLACK, RED, WHITE, YELLOW, W, H,
    cap_height, draw_text_top, f_bold, f_body, f_tiny, is_red_day, quantize, text_w,
)

HDR_H = 28


def _card(img, draw, x, y, w, day, today, measure=False):
    rows = [event_row(img, draw, x + 8, 0, w - 16, ev, size=17, icon_size=18, chip_d=18,
                      max_lines=2, draw_it=False) for ev in day["events"]]
    body_h = sum(rows) if rows else 28
    total = HDR_H + 6 + body_h + 6
    if measure:
        return total

    d = day["date"]
    is_today = d == today
    fill = YELLOW if is_today else (RED if is_red_day(d, day["events"]) else BLACK)
    fg = BLACK if is_today else WHITE
    draw.rounded_rectangle([x, y, x + w, y + total], radius=6, outline=BLACK, width=2)
    draw.rounded_rectangle([x, y, x + w, y + HDR_H], radius=6, fill=fill)
    draw.rectangle([x, y + HDR_H - 6, x + w, y + HDR_H], fill=fill)
    if is_today:
        draw.rectangle([x, y + HDR_H, x + w, y + HDR_H + 1], fill=BLACK)
    fh = f_bold(17)
    label = ("I dag · " if is_today else "") + day_label(d)
    draw_text_top(draw, (x + 10, y + (HDR_H - cap_height(draw, fh)) // 2), label, fh, fg)
    weather_inline(img, draw, x + w - 10, y + HDR_H // 2, day.get("weather"), size=14, color=fg)

    cy = y + HDR_H + 6
    for ev, h in zip(day["events"], rows):
        event_row(img, draw, x + 8, cy, w - 16, ev, size=17, icon_size=18, chip_d=18, max_lines=2)
        cy += h
    if not rows:
        draw_text_top(draw, (x + 12, cy + 8), "Ingen avtaler", f_body(16), BLACK)
    return total


def render(data):
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    gap, margin = 10, 6
    col_w = (W - 2 * margin - gap) // 2
    cols = [margin, margin + col_w + gap]
    col_i, y = 0, margin
    for day in data["days"]:
        h = _card(img, draw, 0, 0, col_w, day, data["today"], measure=True)
        if y + h > H - 18:
            col_i += 1
            y = margin
            if col_i >= len(cols):
                break
        _card(img, draw, cols[col_i], y, col_w, day, data["today"])
        y += h + gap
    f_up = f_tiny(12)
    up = f"Oppdatert {data.get('updated', '')}"
    draw_text_top(draw, (W - margin - text_w(draw, up, f_up), H - 14), up, f_up, BLACK)
    return quantize(img)
