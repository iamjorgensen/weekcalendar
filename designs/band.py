"""
Concept C — "Today band + week strip"

Top band: today with big date, rich weather and today's events side by side.
Below: the next six days as narrow columns, like a paper week planner.
"""
from PIL import Image, ImageDraw

from designs.blocks import day_label
from designs.common import (
    BLACK, RED, WHITE, YELLOW, W, H, MONTHS, WEEKDAYS, WEEKDAYS_SHORT,
    cap_height, draw_text_top, ellipsize, f_body, f_bold, f_tiny, is_red_day,
    paste_icon, person_chip, quantize, text_w, weather_icon_name, wrap,
)
from designs.blocks import event_row

BAND_H = 196


def _band(img, draw, day, updated):
    draw.rectangle([0, 0, W, BAND_H], fill=BLACK)
    d = day["date"]
    red = is_red_day(d, day["events"])
    x0 = 18
    # date block
    f_wd, f_num, f_mon = f_bold(24), f_bold(70), f_body(20)
    draw_text_top(draw, (x0, 18), WEEKDAYS[d.weekday()], f_wd, RED if red else YELLOW)
    draw_text_top(draw, (x0, 56), str(d.day), f_num, WHITE)
    draw_text_top(draw, (x0, 56 + cap_height(draw, f_num) + 14), MONTHS[d.month - 1], f_mon, WHITE)

    # weather block
    w = day.get("weather") or {}
    wx = 170
    if w:
        paste_icon(img, weather_icon_name(w.get("symbol")), wx, 18, 52, WHITE)
        f_t = f_bold(32)
        draw_text_top(draw, (wx + 62, 22), f"{w['tmax']:.0f}°", f_t, WHITE)
        draw_text_top(draw, (wx + 62, 22 + cap_height(draw, f_t) + 8), f"min {w['tmin']:.0f}°", f_body(15), WHITE)
        py = 88
        for i, (label, ic, temp) in enumerate(w.get("periods") or []):
            px = wx + i * 62
            draw_text_top(draw, (px, py), label, f_tiny(13), WHITE)
            paste_icon(img, ic, px, py + 18, 22, WHITE)
            draw_text_top(draw, (px + 26, py + 22), f"{temp:.0f}°", f_bold(16), WHITE)
        f_det = f_tiny(14)
        dy = 148
        paste_icon(img, "droplet", wx, dy - 3, 16, WHITE)
        draw_text_top(draw, (wx + 20, dy), f"{w.get('precip', 0):.1f} mm", f_det, WHITE)
        paste_icon(img, "wind", wx + 92, dy - 3, 16, WHITE)
        draw_text_top(draw, (wx + 112, dy), f"{w.get('wind', 0):.0f} m/s {w.get('wind_dir', '')}", f_det, WHITE)
        if w.get("sunrise"):
            paste_icon(img, "sun", wx, dy + 21, 16, WHITE)
            draw_text_top(draw, (wx + 20, dy + 24), f"{w['sunrise']} – {w['sunset']}", f_det, WHITE)

    # today's events
    ex, ew = 380, W - 380 - 16
    draw.rectangle([ex - 14, 16, ex - 13, BAND_H - 16], fill=WHITE)
    y = 14
    shown = 0
    for ev in day["events"]:
        h = event_row(img, draw, ex, y, ew, ev, size=18, icon_size=20, chip_d=20, max_lines=1, draw_it=False)
        if y + h > BAND_H - 8:
            break
        event_row(img, draw, ex, y, ew, ev, size=18, icon_size=20, chip_d=20, max_lines=1,
                  color=WHITE, bg=BLACK)
        y += h
        shown += 1
    if len(day["events"]) > shown:
        draw_text_top(draw, (ex, BAND_H - 18), f"+ {len(day['events']) - shown} til", f_tiny(13), YELLOW)
    if not day["events"]:
        draw_text_top(draw, (ex, 20), "Ingen avtaler i dag", f_body(18), WHITE)


def _column(img, draw, x, y, w, h, day):
    d = day["date"]
    red = is_red_day(d, day["events"])
    col = RED if red else BLACK
    fh = f_bold(17)
    draw_text_top(draw, (x + 4, y + 8), f"{WEEKDAYS_SHORT[d.weekday()]} {d.day}.", fh, col)
    wthr = day.get("weather")
    if wthr:
        txt = f"{wthr['tmax']:.0f}°"
        ft = f_body(15)
        tw = text_w(draw, txt, ft)
        draw_text_top(draw, (x + w - 4 - tw, y + 9), txt, ft, col)
        paste_icon(img, weather_icon_name(wthr.get("symbol")), x + w - 4 - tw - 24, y + 4, 20, col)
    draw.rectangle([x, y + 32, x + w, y + 34], fill=col)

    cy = y + 42
    f_t, f_e = f_tiny(13), f_body(15)
    ch_e = cap_height(draw, f_e)
    for ev in day["events"]:
        lines = wrap(draw, ev["title"], f_e, w - 8, 2)
        need = (16 if ev.get("time") or ev.get("people") else 0) + len(lines) * (ch_e + 7) + 8
        if cy + need > y + h:
            draw_text_top(draw, (x + 4, y + h - 14), "…", f_e, BLACK)
            break
        if ev.get("time") or ev.get("people"):
            if ev.get("time"):
                draw_text_top(draw, (x + 4, cy), ev["time"], f_t, BLACK)
            px = x + w - 4
            for letter, pc in reversed(ev.get("people") or []):
                px -= 16
                person_chip(draw, px, cy + 5, letter, pc, 15)
                px -= 2
            cy += 16
        for ln in lines:
            draw_text_top(draw, (x + 4, cy), ln, f_e, BLACK)
            cy += ch_e + 7
        cy += 8


def render(data):
    img = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)
    _band(img, draw, data["days"][0], data.get("updated", ""))
    n = 6
    gap = 6
    top = BAND_H + 6
    col_w = (W - 12 - gap * (n - 1)) // n
    for i, day in enumerate(data["days"][1:1 + n]):
        x = 6 + i * (col_w + gap)
        _column(img, draw, x, top, col_w, H - top - 4, day)
        if i:
            for yy in range(top + 40, H - 6, 4):
                draw.point((x - gap // 2, yy), fill=BLACK)
    return quantize(img)
