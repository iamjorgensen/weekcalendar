"""
Draws a moments.banner() at the top of the black panel: a tall coloured banner
with decorations (confetti and bunting, snow, Easter eggs, fireworks, leaves,
sun and waves, Advent candles), a big title, a big number/word and an icon.
"""
import math
import random

from designs.common import (BLACK, BLUE, GREEN, RED, WHITE, YELLOW, cap_height, draw_text_top, f_bold,
                            f_tiny, paste_icon, text_w)

PALETTE = [YELLOW, RED, GREEN, BLUE, WHITE, BLACK]
BANNER_H = 168      # coloured area incl. the zigzag edge
DATE_H = 22         # the small date line under it


def text_on(bg):
    return WHITE if bg in (RED, BLUE, BLACK) else BLACK


def _bunting(draw, w, cols, line, y=2):
    draw.line([0, y + 1, w, y + 1], fill=line, width=2)
    x, k = 0, 0
    while x + 18 <= w:
        draw.polygon([(x, y + 1), (x + 18, y + 1), (x + 9, y + 17)], fill=cols[k % len(cols)])
        x += 21
        k += 1


def _confetti(draw, rnd, bg, fg, box, n):
    cols = [c for c in PALETTE if c not in (bg, fg)] or [WHITE]
    x0, y0, x1, y1 = box
    for _ in range(n):
        x, y, c, kind = rnd.randint(x0, x1), rnd.randint(y0, y1), rnd.choice(cols), rnd.random()
        if kind < 0.45:
            r = rnd.randint(2, 4)
            draw.ellipse([x - r, y - r, x + r, y + r], fill=c)
        elif kind < 0.8:
            a, b = rnd.choice([(7, 3), (3, 7), (6, 4)])
            draw.rectangle([x, y, x + a, y + b], fill=c)
        else:
            draw.line([x, y, x + 4, y + 4, x + 8, y, x + 12, y + 4], fill=c, width=2)


def _decorate(draw, rnd, w, bg, fg, decor, candles=0):
    h = BANNER_H
    if decor == "party":
        _confetti(draw, rnd, bg, fg, (6, 24, w - 8, h - 16), 34)
        _bunting(draw, w, [c for c in (RED, BLUE, GREEN, YELLOW, WHITE, BLACK) if c != bg], text_on(bg))
    elif decor == "flags":      # 17. mai, match day: a clean row of flags, no confetti
        _bunting(draw, w, [c for c in (WHITE, BLUE, RED) if c != bg], WHITE)
    elif decor == "snow":
        for _ in range(60):
            x, y, r = rnd.randint(4, w - 4), rnd.randint(4, h - 14), rnd.choice([1, 2, 2, 3])
            draw.ellipse([x - r, y - r, x + r, y + r], fill=WHITE if bg != WHITE else BLUE)
    elif decor == "eggs":
        cols = [c for c in (RED, GREEN, BLUE, WHITE) if c != bg]
        for k, x in enumerate(range(6, w - 12, 22)):
            draw.ellipse([x, 4, x + 13, 21], fill=cols[k % len(cols)])
        for _ in range(16):
            x, y = rnd.randint(8, w - 20), rnd.randint(28, h - 30)
            draw.ellipse([x, y, x + 9, y + 12], fill=rnd.choice(cols))
    elif decor == "fireworks":
        for cx, cy, r in ((w - 40, 28, 22), (w - 120, 136, 16), (180, 140, 14), (40, 142, 12)):
            c = rnd.choice([YELLOW, RED, GREEN, WHITE])
            for k in range(14):
                a = k * math.pi / 7
                ex, ey = cx + math.cos(a) * r, cy + math.sin(a) * r
                draw.line([cx + math.cos(a) * r * 0.35, cy + math.sin(a) * r * 0.35, ex, ey], fill=c, width=2)
                draw.ellipse([ex - 2, ey - 2, ex + 2, ey + 2], fill=c)
    elif decor == "leaves":
        cols = [c for c in (RED, YELLOW, GREEN) if c != bg]
        for _ in range(22):
            x, y, c = rnd.randint(6, w - 14), rnd.randint(6, h - 22), rnd.choice(cols)
            draw.polygon([(x, y + 6), (x + 6, y), (x + 12, y + 6), (x + 6, y + 12)], fill=c)
            draw.line([x + 6, y + 12, x + 6, y + 16], fill=c, width=1)
    elif decor == "sun":
        for row in range(2):
            yy = h - 34 + row * 9
            draw.line([(x, yy + (3 if (x // 8) % 2 else 0)) for x in range(0, w + 8, 8)], fill=WHITE, width=2)


def _candles(draw, x1, y, lit):
    """Four Advent candles, right-aligned at x1; the first `lit` burn."""
    for k in range(4):
        x = x1 - (4 - k) * 18
        draw.rectangle([x, y + 22, x + 10, y + 62], fill=WHITE)
        draw.line([x + 5, y + 16, x + 5, y + 22], fill=BLACK, width=1)
        if k < lit:
            draw.ellipse([x + 1, y + 2, x + 9, y + 17], fill=YELLOW)
            draw.ellipse([x + 3, y + 8, x + 7, y + 16], fill=RED)
    draw.rectangle([x1 - 76, y + 62, x1 - 2, y + 68], fill=RED)


def draw_banner(img, draw, w, b, date_line, seed=0):
    """Draw banner dict `b` (see moments.banner) at the top of the panel. Returns the y below it."""
    bg = b["bg"]
    fg = b.get("fg") or text_on(bg)
    rnd = random.Random(seed)
    draw.rectangle([0, 0, w, BANNER_H - 8], fill=bg)
    _decorate(draw, rnd, w, bg, fg, b["decor"])
    boxed = b["decor"] in ("party", "eggs", "fireworks", "snow", "leaves")
    x0 = 16

    title = b["title"]
    f_h = f_bold(28)
    while text_w(draw, title, f_h) > w - 2 * x0 and f_h.size > 18:
        f_h = f_bold(f_h.size - 2)
    th = cap_height(draw, f_h)
    if boxed:
        draw.rectangle([x0 - 4, 30, x0 + text_w(draw, title, f_h) + 4, 30 + th + 10], fill=bg)
    draw_text_top(draw, (x0, 34), title, f_h, fg)

    big, small = b.get("big") or "", b.get("small") or ""
    y_big = 34 + th + 16
    short = len(big) <= 3
    has_side = bool(b.get("icon") or b.get("candles"))
    room = w - x0 - 16 - (80 if has_side else 0)
    f_big = f_bold(64 if short else 34)
    while text_w(draw, big, f_big) > room and f_big.size > 18:
        f_big = f_bold(f_big.size - 2)
    bw, bh = text_w(draw, big, f_big), cap_height(draw, f_big)
    if short:
        f_s = f_bold(22)
        if boxed:
            draw.rectangle([x0 - 4, y_big - 4, x0 + bw + 16 + text_w(draw, small, f_s), y_big + bh + 4], fill=bg)
        draw_text_top(draw, (x0, y_big), big, f_big, fg)
        draw_text_top(draw, (x0 + bw + 12, y_big + bh - cap_height(draw, f_s)), small, f_s, fg)
    else:
        f_s = f_bold(16)
        sy = y_big + bh + 12
        s_room = w - 2 * x0 - (80 if has_side and sy < y_big + 54 else 0)   # keep clear of the icon
        while text_w(draw, small, f_s) > s_room and f_s.size > 12:
            f_s = f_bold(f_s.size - 1)
        if boxed:
            draw.rectangle([x0 - 4, y_big - 4, x0 + bw + 4, y_big + bh + 4], fill=bg)
            if small:
                draw.rectangle([x0 - 4, sy - 4, x0 + text_w(draw, small, f_s) + 4, sy + cap_height(draw, f_s) + 4],
                               fill=bg)
        draw_text_top(draw, (x0, y_big), big, f_big, fg)
        if small:
            draw_text_top(draw, (x0, sy), small, f_s, fg)

    if b.get("candles"):
        _candles(draw, w - 14, y_big - 16, b["candles"])
    elif b.get("icon"):
        if boxed:
            draw.rectangle([w - 16 - 70, y_big - 16, w - 12, y_big + 58], fill=bg)
        paste_icon(img, b["icon"], w - 16 - 66, y_big - 12, 66, b.get("icon_col") or fg)

    edge = BANNER_H - 8
    if b.get("edge") == "rainbow" or bg == BLACK:     # black on the black panel needs a visible edge
        cols = [RED, YELLOW, GREEN, BLUE]
        for k, x in enumerate(range(0, w, 12)):
            draw.rectangle([x, edge, x + 11, edge + 4], fill=cols[k % 4])
    else:
        pts = [(0, edge)]
        for x in range(0, w, 12):
            pts += [(x + 6, edge + 7), (x + 12, edge)]
        draw.polygon(pts + [(w, edge), (0, edge)], fill=bg)
    draw_text_top(draw, (x0, BANNER_H + 4), date_line, f_tiny(14), WHITE)
    return BANNER_H + DATE_H
