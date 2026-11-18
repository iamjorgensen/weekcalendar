"""
Shared drawing helpers for the design experiments.

Everything is drawn at the panel's native 800x480 and quantized to the
six panel colours with no dithering, so what you see is what the panel gets.
"""
import os
import re
from datetime import date

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "assets", "fonts")
ICONS = os.path.join(ROOT, "assets", "icons")

W, H = 800, 480

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
YELLOW = (255, 255, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
PALETTE = [BLACK, WHITE, GREEN, BLUE, RED, YELLOW]

WEEKDAYS = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
WEEKDAYS_SHORT = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]
MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
          "august", "september", "oktober", "november", "desember"]
MONTHS_SHORT = ["jan", "feb", "mar", "apr", "mai", "jun", "jul", "aug", "sep", "okt", "nov", "des"]

_font_cache = {}


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    key = (name, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(os.path.join(FONTS, name), size)
    return _font_cache[key]


# Font roles. Change here to try other faces everywhere at once.
def f_body(size=17):
    return font("Roboto-SemiBold.ttf", size)


def f_bold(size=17):
    return font("NotoSans-Bold.ttf", size)


def f_tiny(size=13):
    return font("Roboto-SemiBold.ttf", size)


def text_w(draw, text, fnt):
    if not text:
        return 0
    b = draw.textbbox((0, 0), text, font=fnt)
    return b[2] - b[0]


def text_box(draw, text, fnt):
    """(left, top, right, bottom) of text drawn at (0,0)."""
    return draw.textbbox((0, 0), text or "Hg", font=fnt)


def draw_text_top(draw, xy, text, fnt, fill):
    """Draw so the glyphs' visual top edge sits exactly at xy[1]."""
    top = draw.textbbox((0, 0), "H", font=fnt)[1]
    draw.text((xy[0], xy[1] - top), text, font=fnt, fill=fill)


def cap_height(draw, fnt):
    b = draw.textbbox((0, 0), "H", font=fnt)
    return b[3] - b[1]


def ellipsize(draw, text, fnt, max_w):
    if text_w(draw, text, fnt) <= max_w:
        return text
    while text and text_w(draw, text + "…", fnt) > max_w:
        text = text[:-1]
    return (text.rstrip() + "…") if text else "…"


def wrap(draw, text, fnt, max_w, max_lines):
    words = (text or "").split()
    lines, cur = [], ""
    for i, w in enumerate(words):
        cand = f"{cur} {w}".strip()
        if text_w(draw, cand, fnt) <= max_w:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        cur = w
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    shown = sum(len(l.split()) for l in lines)
    lines = [ellipsize(draw, l, fnt, max_w) for l in lines[:max_lines]]
    if shown < len(words) and lines and not lines[-1].endswith("…"):
        lines[-1] = ellipsize(draw, lines[-1] + "…", fnt, max_w)
    return lines or [""]


_icon_manager = None
_icon_cache = {}

# If an icon can't be found or downloaded, try these instead
ICON_FALLBACK = {
    "cloud-sun": "cloud", "cloud-moon": "moon", "cloud-lightning": "cloud-rain",
    "cloud-fog": "cloud", "cloud-drizzle": "cloud-rain", "trash-2": "trash",
    "sunrise": "sun", "sunset": "moon",
}

# Old icon names (still in stored configs and calendar events) -> the Lucide icon used now.
# The old name is still tried as a last resort, so its PNG works when offline.
ICON_ALIASES = {
    "school": "graduation-cap", "umbrella_beach": "tree-palm", "food": "utensils",
    "home": "house", "alert-circle": "circle-alert", "check-circle": "circle-check",
    "x-circle": "circle-x",
}


def set_icon_manager(manager):
    """Optional IconManager (inky_icons_package) used to download missing Lucide icons."""
    global _icon_manager
    _icon_manager = manager
    _icon_cache.clear()


def _icon_dirs():
    dirs = [ICONS]
    if os.environ.get("ICONS_CACHE_DIR"):
        dirs.append(os.environ["ICONS_CACHE_DIR"])
    return dirs


def _find_icon_file(name, ext):
    for d in _icon_dirs():
        p = os.path.join(d, name + ext)
        if os.path.isfile(p):
            return p
    return None


def _download_svg(name):
    """Have the IconManager fetch the Lucide SVG into its cache dir. Path or None."""
    dl = getattr(_icon_manager, "_download_icon", None)
    if dl is None:
        return None
    try:
        path = dl(name)
    except Exception:
        return None
    return path if path and str(path).endswith(".svg") and os.path.isfile(path) else None


_SVG_ROOT = re.compile(r"<svg\b[^>]*>", re.S)


def stroke_px(size):
    """Line width in panel pixels: 1.5 px below 20 px, 2 px from 20 px up, 3 px for the big
    banner icons (48 px and up), where 2 px looks spindly."""
    return 3.0 if size >= 48 else 2.0 if size >= 20 else 1.5


def fit_stroke(svg, size):
    """Set the stroke width on the root <svg> so lines land on whole/half pixels at `size`.
    Only for outline icons (root has a stroke and fill="none"); fill-based artwork is left alone."""
    m = _SVG_ROOT.search(svg)
    if not m:
        return svg
    root = m.group(0)
    attr = lambda k: (re.search(r'\s%s="([^"]*)"' % k, root) or [None, None])[1]   # noqa: E731
    if attr("fill") != "none" or attr("stroke") in (None, "none"):
        return svg
    vb = re.search(r'\sviewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', root)
    units = float(vb.group(1)) if vb else 24.0
    sw = stroke_px(size) * units / size
    new_root = re.sub(r'\sstroke-width="[^"]*"', "", root)
    new_root = new_root[:-1].rstrip() + f' stroke-width="{sw:.3f}">'
    return svg[:m.start()] + new_root + svg[m.end():]


def render_svg(path, size):
    import io
    import resvg_py
    with open(path, "r", encoding="utf-8") as f:
        svg = fit_stroke(f.read(), size).replace("currentColor", "#000")
    return Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg, width=size, height=size))))


def _load_icon(names, size):
    """SVG (bundled, then cached, then downloaded) before the old PNGs, for each candidate name."""
    for n in names:
        p = _find_icon_file(n, ".svg")
        if p:
            return p
    for n in names:
        if re.fullmatch(r"[a-z0-9-]+", n):
            p = _download_svg(n)
            if p:
                return p
    for n in names:
        p = _find_icon_file(n, ".png")
        if p:
            return p
    return None


def icon(name, size, color=BLACK, _depth=0):
    """Load an icon tinted to a solid colour (alpha-thresholded: no grey edges)."""
    if not name:
        return None
    name = str(name).strip().lower()
    key = (name, size, color)
    if key in _icon_cache:
        ic = _icon_cache[key]
        return ic.copy() if ic is not None else None
    names = [n for n in (ICON_ALIASES.get(name), name) if n]
    path = _load_icon(names, size)
    im = None
    try:
        if path and path.endswith(".svg"):
            im = render_svg(path, size)
        elif path:
            im = Image.open(path)
    except Exception:
        im = None
    if im is None:
        alt = ICON_FALLBACK.get(name)
        out = icon(alt, size, color, _depth + 1) if alt and _depth < 2 else None
        _icon_cache[key] = out
        return out
    im = im.convert("RGBA")
    if im.size != (size, size):
        # scale up or down to fit the box, keeping aspect ratio
        scale = size / max(im.size)
        im = im.resize((max(1, round(im.size[0] * scale)), max(1, round(im.size[1] * scale))),
                       Image.Resampling.LANCZOS)
    alpha = im.split()[3].point(lambda a: 255 if a >= 110 else 0)
    out = Image.new("RGBA", im.size, color + (255,))
    out.putalpha(alpha)
    _icon_cache[key] = out
    return out.copy()


def paste_icon(img, name, x, y, size, color=BLACK):
    ic = icon(name, size, color)
    if ic is not None:
        img.paste(ic, (int(x), int(y)), ic)
        return ic.size[0]
    return 0


# Ordered: first match wins. Covers Norwegian labels (weather_provider) and
# raw MET symbol codes (e.g. "lightrainshowers_day", "partlycloudy_night").
WEATHER_RULES = [
    (("torden", "thunder"), "cloud-lightning"),
    (("snø", "snow", "sludd", "sleet", "hagl", "hail"), "cloud-snow"),
    (("regn", "rain", "byge", "shower", "drizzle"), "cloud-rain"),
    (("tåke", "fog"), "cloud-fog"),
    (("delvis", "partly", "fair_night"), "cloud-sun"),
    (("skyet", "cloud"), "cloud"),
    (("clearsky_night",), "moon"),
    (("klart", "sol", "clear", "fair"), "sun"),
]


def weather_icon_name(symbol):
    s = str(symbol or "").lower()
    if "night" in s and ("partly" in s or "fair" in s):
        return "cloud-moon"
    for keys, name in WEATHER_RULES:
        if any(k in s for k in keys):
            return name
    return "cloud"


def person_chip(draw, x, cy, letter, color, d=20, bg=WHITE):
    """Coloured circle with an initial, vertically centred on cy. Returns width."""
    r = d // 2
    outline = WHITE if color == bg == BLACK or (color == BLACK and bg == BLACK) else None
    draw.ellipse([x, cy - r, x + d, cy + r], fill=color, outline=outline, width=2 if outline else 0)
    fg = BLACK if color in (YELLOW, GREEN, WHITE) else WHITE
    f = f_bold(13)
    tw = text_w(draw, letter, f)
    ch = cap_height(draw, f)
    draw_text_top(draw, (x + r - tw / 2, cy - ch / 2), letter, f, fg)
    return d


def is_red_day(d: date, events):
    return d.weekday() >= 5 or any(e.get("is_holiday") for e in events)


def quantize(img: Image.Image) -> Image.Image:
    flat = []
    for c in PALETTE:
        flat.extend(c)
    pal = Image.new("P", (1, 1))
    pal.putpalette(flat + [0] * (768 - len(flat)))
    return img.convert("RGB").quantize(palette=pal, dither=Image.Dither.NONE).convert("RGB")


def dotted_hline(draw, x0, x1, y, color=BLACK, gap=4):
    for x in range(int(x0), int(x1), gap):
        draw.point((x, y), fill=color)


def draw_battery(draw, x, cy, pct, color=WHITE):
    """Small battery icon + 'NN%' at (x, centre y). Fill: green > 50, yellow > 20, else red."""
    w, h = 22, 11
    top = cy - h // 2
    draw.rectangle([x, top, x + w, top + h], outline=color, width=1)
    draw.rectangle([x + w + 1, top + 3, x + w + 2, top + h - 3], fill=color)
    fill = GREEN if pct > 50 else YELLOW if pct > 20 else RED
    fw = int((w - 3) * pct / 100)
    if fw > 0:
        draw.rectangle([x + 2, top + 2, x + 1 + fw, top + h - 2], fill=fill)
    f = f_tiny(12)
    txt = f"{pct}%"
    draw_text_top(draw, (x + w + 6, cy - cap_height(draw, f) // 2), txt, f, color)
    return w + 6 + text_w(draw, txt, f)
