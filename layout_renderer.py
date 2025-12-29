"""
Pillow-based layout renderer for calendar and event data.

- Handles core text wrapping, measurement, and multi-line event display.
- Supports colored event tags (chips) and event icon display.
- Integrates weather data rendering in the date header.
- Designed to be standalone, relying only on standard PIL and OS libraries.
"""
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageColor
import os
import re
from typing import List, Tuple, Union, Dict
from datetime import datetime, timedelta
# Note: Keep the following import for event mapping, as requested.
from mappings import mapping_info_for_event, color_to_rgb 
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")
ICONS_DIR = os.path.join(ASSETS_DIR, "icons")

DEFAULT_FONT = os.path.join(FONTS_DIR, "NotoSans-Bold.ttf")
DEFAULT_BOLD_FONT = os.path.join(FONTS_DIR, "NotoSans-Bold.ttf")

ICON_NAME_MAP = {
    "clearsky_day": "sun",
    "clearsky_night": "moon",
    "fair_day": "sun",
    "fair_night": "moon",
    "partlycloudy_day": "cloud-sun",
    "partlycloudy_night": "cloud-moon",
    "cloudy": "cloud",
    "rain": "cloud-rain",
    "lightrain": "cloud-rain",
    "heavyrain": "cloud-rain",
    "rainshowers_day": "cloud-rain",
    "rainshowers_night": "cloud-rain",
    "snow": "cloud-snow",
    "heavysnow": "cloud-snow",
    "sleet": "cloud-snow",
    "lightsleet": "cloud-snow",
    "snowshowers_day": "cloud-snow",
    "snowshowers_night": "cloud-snow",
    "thunderstorm": "cloud-lightning",
    "rainandthunder": "cloud-lightning",
    "fog": "cloud",
    "wind": "wind",
}

# ---------------- Utility Functions ------------------------------------------

def _measure_text(draw, text, font):
    """Return (width, height) for text using textbbox, with sensible fallbacks."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
    except Exception:
        try:
            return font.getsize(text)
        except Exception:
            return (len(text) * (getattr(font, 'size', 10) // 2), getattr(font, 'size', 10))


def _deg_to_cardinal(deg: float) -> str:
    """
    Convert degrees (0-360) to a short cardinal (N, NE, E, SE, S, SW, W, NW).
    Returns empty string if deg is None/invalid.
    """
    if deg is None:
        return ""
    try:
        d = float(deg) % 360
    except Exception:
        return ""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    ix = int((d + 22.5) // 45) % 8
    return dirs[ix]


def _ensure_font(path: str, size: int):
    """Load a truetype font, or fall back to a reasonable default."""
    try:
        if path and os.path.isfile(path):
            return ImageFont.truetype(path, int(size))
    except Exception:
        pass
    try:
        if 'DEFAULT_FONT' in globals() and DEFAULT_FONT and os.path.isfile(DEFAULT_FONT):
            return ImageFont.truetype(DEFAULT_FONT, int(size))
    except Exception:
        pass
    # Last resort fallback: PIL's built-in bitmap font
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    """Return width of text."""
    if text is None:
        text = ""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]
    except Exception:
        pass
    try:
        w, _ = _measure_text(draw, text, font=font)
        return w
    except Exception:
        pass
    try:
        w, _ = font.getsize(text)
        return w
    except Exception:
        size = getattr(font, "size", 12)
        return int(len(text) * size * 0.6)


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int):
    """Truncate text with ellipsis if it exceeds max_width."""
    if text is None:
        text = ""
    if _text_width(draw, text, font) <= max_width:
        return text
    ell = "…"
    t = text
    while t:
        t = t[:-1]
        if _text_width(draw, t + ell, font) <= max_width:
            return t + ell
    return ell


def _load_icon_image(icon_name: str, size: int, icon_manager=None):
    """Load icon by name. Try map -> icon_manager -> assets/icons. Return RGBA or None."""
    if not icon_name:
        return None
    icon_try = ICON_NAME_MAP.get(icon_name, icon_name)
    # try icon_manager (if provided)
    if icon_manager is not None:
        try:
            if hasattr(icon_manager, "get_icon_image"):
                im = icon_manager.get_icon_image(icon_try, size)
                if isinstance(im, Image.Image):
                    return im.convert("RGBA")
            if hasattr(icon_manager, "render_icon"):
                im = icon_manager.render_icon(icon_try, size)
                if isinstance(im, Image.Image):
                    return im.convert("RGBA")
        except Exception:
            pass
    # try files
    png_path = os.path.join(ICONS_DIR, f"{icon_try}.png")
    if not os.path.isfile(png_path):
        png_path2 = os.path.join(ICONS_DIR, f"{icon_name}.png")
        if os.path.isfile(png_path2):
            png_path = png_path2
        else:
            return None
    try:
        im = Image.open(png_path).convert("RGBA")
        w, h = im.size
        if h != size:
            new_w = max(1, int(w * (size / float(h))))
            im = im.resize((new_w, size), Image.Resampling.LANCZOS)
        return im
    except Exception:
        return None


def _normalize_color_input(col: Union[int, Tuple, list, str]) -> Tuple[int, int, int]:
    """Normalize color input (int, tuple, list, hex/name string) to (r,g,b)."""
    try:
        if col is None:
            return (0, 0, 0)
        if isinstance(col, int):
            c = max(0, min(255, col))
            return (c, c, c)
        if isinstance(col, (tuple, list)):
            return (int(col[0]), int(col[1]), int(col[2]))
        if isinstance(col, str):
            return ImageColor.getrgb(col)
    except Exception:
        pass
    return (0, 0, 0) # Fallback to black


def _tint_icon_to_color(icon_im: Image.Image, color) -> Image.Image:
    """Tint icon_im to color (r,g,b). preserve alpha."""
    if icon_im is None:
        return None
    try:
        icon = icon_im.convert("RGBA")
        r, g, b = _normalize_color_input(color)
        solid = Image.new("RGBA", icon.size, (r, g, b, 255))
        alpha = icon.split()[3]
        solid.putalpha(alpha)
        return solid
    except Exception:
        return icon_im


def _resize_to_height_and_pad(icon_im: Image.Image, height: int, pad_square: bool = True) -> Image.Image:
    """Resize to given height preserving aspect; optionally pad to square (height x height)."""
    if icon_im is None:
        return None
    try:
        im = icon_im.convert("RGBA")
        w, h = im.size
        if h != height:
            new_w = max(1, int(w * (height / float(h))))
            im = im.resize((new_w, height), Image.Resampling.LANCZOS)
        if pad_square and im.size[0] != height:
            out = Image.new("RGBA", (height, height), (0, 0, 0, 0))
            ox = (height - im.size[0]) // 2
            out.paste(im, (ox, 0), im)
            return out
        return im
    except Exception:
        return icon_im


def _normalize_bg(bg: Union[int, Tuple, list, str]) -> Tuple[int, int, int, int]:
    """Normalize color input to (r,g,b,a), defaulting alpha to 255."""
    try:
        if isinstance(bg, (tuple, list)):
            if len(bg) == 3:
                return (bg[0], bg[1], bg[2], 255)
            if len(bg) == 4:
                return tuple(bg)
        if isinstance(bg, int):
            return (bg, bg, bg, 255)
        if isinstance(bg, str):
            rgb = ImageColor.getrgb(bg)
            return (rgb[0], rgb[1], rgb[2], 255)
    except Exception:
        pass
    return (255, 255, 255, 255)


def _luminance_from_color(col: Union[int, Tuple, list, str]) -> float:
    """Calculate relative luminance for a color."""
    try:
        r, g, b = _normalize_color_input(col)
        # Standard sRGB luminance calculation
        r /= 255.0; g /= 255.0; b /= 255.0
        return 0.299 * r + 0.587 * g + 0.0722 * b
    except Exception:
        return 1.0 # Default to white (max luminance)


def _group_events_by_date(events: List[dict]) -> Dict[str, List[dict]]:
    """Groups events by their 'date' key."""
    groups = {}
    for ev in events:
        d = ev.get("date", "unknown")
        groups.setdefault(d, []).append(ev)
    return groups


# ---------------- Text wrapping helper ---------------------------------------

def _wrap_text_to_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont,
                        max_width: int, max_lines: int) -> List[str]:
    """
    Greedy wrap text into at most max_lines lines to fit within max_width.
    Returns list of lines (may be shorter than max_lines). If text is empty -> [].
    """
    if not text:
        return []
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip() if cur else w
        if _text_width(draw, candidate, font) <= max_width:
            cur = candidate
        else:
            # commit current line
            if cur:
                lines.append(cur)
            else:
                # single long word: break it into pieces
                s = w
                piece = ""
                for ch in s:
                    if _text_width(draw, piece + ch, font) <= max_width:
                        piece += ch
                    else:
                        if piece:
                            lines.append(piece)
                        piece = ch
                if piece:
                    lines.append(piece)
            cur = ""
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    # if we exceeded max_lines via splitting, truncate last line with ellipsis
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if len(lines) == max_lines:
        # ensure last line fits; if not, ellipsize it
        if _text_width(draw, lines[-1], font) > max_width:
            lines[-1] = _ellipsize(draw, lines[-1], font, max_width)
    return lines


# ---------- Tag-drawing helper ----------------------------------

def _fg_for_bg(rgb):
    """
    Choose white or black for text on top of rgb background based on luminance for contrast.
    """
    try:
        bg = _normalize_color_input(rgb)
        def rl(c):
            v = c / 255.0
            return v/12.92 if v <= 0.03928 else ((v+0.055)/1.055) ** 2.4
        l_bg = 0.2126*rl(bg[0]) + 0.7152*rl(bg[1]) + 0.0722*rl(bg[2])
        # Simple threshold for contrast
        return (255, 255, 255) if l_bg < 0.45 else (0, 0, 0)
    except Exception:
        return (0, 0, 0)


def draw_event_tags(draw: ImageDraw.ImageDraw, start_x: int, top_y: int, ev: dict,
                    tag_font: ImageFont.ImageFont, padding_x: int = 8, padding_y: int = 3, gap: int = 8,
                    max_x: int = None):
    """Draw tags (chips) for an event dict `ev`."""
    x = start_x

    tags = ev.get("tags") or []
    # Legacy fallback: split comma-joined tag_text into multiple tags (trim whitespace)
    if not tags and ev.get("tag_text"):
        raw = (ev.get("tag_text") or "").strip()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if parts:
            legacy_rgb = ev.get("tag_color_rgb")
            legacy_name = ev.get("tag_color_name")
            tags = [{"text": p, "color_rgb": legacy_rgb, "color_name": legacy_name} for p in parts]

    for tag in tags:
        text = (tag.get("text") or "").strip()
        if not text:
            continue

        # determine bg color rgb (normalized)
        bg = None
        if tag.get("color_rgb") is not None:
            try:
                bg = tuple(tag["color_rgb"])
            except Exception:
                bg = None
        elif tag.get("color_name"):
            try:
                bg = _normalize_color_input(tag["color_name"])
            except Exception:
                bg = None
        if bg is None:
            # fallback: try event color fields, then grey
            ev_color = None
            if ev.get("tag_color_rgb") is not None:
                ev_color = tuple(ev.get("tag_color_rgb"))
            elif ev.get("tag_color_name"):
                try:
                    ev_color = _normalize_color_input(ev.get("tag_color_name"))
                except Exception:
                    ev_color = None
            elif ev.get("color") is not None:
                ev_color = _normalize_color_input(ev.get("color"))
            if ev_color is not None:
                bg = ev_color
            else:
                bg = (200, 200, 200)

        # precise text bbox measurement (handles baseline offsets)
        try:
            bbox = draw.textbbox((0, 0), text, font=tag_font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            baseline_top = bbox[1]
        except Exception:
            text_w, text_h = _measure_text(draw, text, font=tag_font)
            baseline_top = 0

        chip_w = text_w + padding_x * 2
        chip_h = text_h + padding_y * 2
        chip_h = max(chip_h, (tag_font.size if hasattr(tag_font, "size") else 12) + 2)

        # overflow check
        if max_x is not None and (x + chip_w) > max_x:
            break

        left = x
        top = top_y
        right = x + chip_w
        bottom = top + chip_h
        radius = 5

        try:
            draw.rounded_rectangle([(left, top), (right, bottom)], radius=radius, fill=bg)
        except Exception:
            draw.rectangle([(left, top), (right, bottom)], fill=bg)

        fg = _fg_for_bg(bg)

        # compute exact text position using baseline/top correction
        text_x = left + padding_x
        text_y = top + (chip_h - text_h) // 2 - baseline_top
        draw.text((text_x, text_y), text, font=tag_font, fill=fg)

        x = right + gap

    return x


# ---------------- Measurement helpers ---------------------------------------

def _measure_row_height(event: dict,
                        nominal_vspacing: int,
                        min_icon_padding: int,
                        draw: ImageDraw.ImageDraw,
                        font: ImageFont.ImageFont,
                        small_font: ImageFont.ImageFont,
                        inner_text_width: int,
                        event_icon_slot: int,
                        icon_gap: int,
                        max_event_lines: int) -> int:
    """
    Compute the vertical space required for one event row, aligned with render_events_section logic.
    """
    # Define tag constants used for layout estimation within this function scope
    tag_padding_x = 8
    tag_padding_y = 3
    tag_gap = 8

    requested_icon_size = event.get("icon_size") or event.get("icon_size_px") or max(12, event_icon_slot - 4)
    base_row = max(nominal_vspacing, requested_icon_size + min_icon_padding)

    time = event.get("time") or ""
    time_w = _text_width(draw, time, small_font) if time else 0

    left_reserved = event_icon_slot + icon_gap + (time_w + 6 if time_w else 0)
    text_avail = max(8, inner_text_width - left_reserved)

    name = (event.get("display_text") or event.get("name") or "") or ""

    # --- Tag parsing logic must be duplicated for accurate measurement ---
    tags_for_measure = event.get("tags") or []
    tag_text = event.get("tag_text") or event.get("tag") or None
    if not tags_for_measure and tag_text:
        rawt = (tag_text or "").strip()
        parts = [p.strip() for p in rawt.split(",") if p.strip()]
        if parts:
            tags_for_measure = [{"text": p} for p in parts] # Minimal tags for size calc

    tag_total_w = 0
    tag_count = 0
    for t in tags_for_measure:
        txt = (t.get("text") or "").strip()
        if not txt: continue
        try:
            bbox = draw.textbbox((0, 0), txt, font=small_font)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = _text_width(draw, txt, small_font)
        chip_w = tw + tag_padding_x * 2
        if tag_total_w + chip_w + (tag_gap if tag_count > 0 else 0) > text_avail // 2: break
        if tag_count > 0: tag_total_w += tag_gap
        tag_total_w += chip_w
        tag_count += 1
    if tag_total_w > text_avail // 2: tag_total_w = text_avail // 2
    reserved_for_tags = tag_total_w + (6 if tag_total_w > 0 else 0)
    # --- End Tag parsing logic ---

    name_max_width = max(8, text_avail - reserved_for_tags)
    words = (name or "").split()
    first_line = ""
    rest_text = ""
    for idx_w, w in enumerate(words):
        cand = (first_line + " " + w).strip() if first_line else w
        if _text_width(draw, cand, font) <= name_max_width:
            first_line = cand
            rest_text = " ".join(words[idx_w+1:])
        else:
            rest_text = " ".join(words[idx_w:])
            break
    if not first_line and words:
        first_line = _ellipsize(draw, words[0], font, name_max_width)
        rest_text = " ".join(words[1:]) if len(words) > 1 else ""

    remaining_lines = []
    if rest_text:
        remaining_lines = _wrap_text_to_lines(draw, rest_text, font, max(8, text_avail), max(0, max_event_lines - 1))

    lines = [first_line] + remaining_lines
    if not lines: lines = [""]

    line_heights = []
    for ln in lines:
        try:
            bbox = draw.textbbox((0, 0), ln if ln else "X", font=font)
            line_h = bbox[3] - bbox[1]
        except Exception:
            line_h = getattr(font, "size", 12)
        line_heights.append(line_h)

    spacing_px = max(2, int((line_heights[0] if line_heights else getattr(font, "size", 12)) * 0.12))
    total_text_h = sum(line_heights)
    if len(line_heights) > 1:
        total_text_h += spacing_px * (len(line_heights) - 1)

    try:
        chip_bbox = draw.textbbox((0, 0), "X", font=small_font)
        chip_text_h = chip_bbox[3] - chip_bbox[1]
    except Exception:
        chip_text_h = getattr(small_font, "size", 12)
    chip_h_est = max(10, chip_text_h + (tag_padding_y * 2))

    needed_row = max(base_row, total_text_h + min_icon_padding, chip_h_est + min_icon_padding)
    return int(needed_row)


def _measure_box_height_for_date(events: list,
                                box_header_height: int,
                                event_vspacing: int,
                                min_icon_padding: int,
                                draw: 'ImageDraw.ImageDraw',
                                font,
                                small_font,
                                inner_w: int,
                                event_icon_slot: int,
                                icon_gap: int,
                                top_padding: int = 6,
                                bottom_padding: int = 6,
                                min_box_height: int = 24,
                                max_event_lines: int = 3) -> int:
    """Compute total box height required to render a date's events."""
    total = box_header_height + top_padding + bottom_padding
    # FIX: reserve space for one line when there are no events (for 'Ingen avtaler')
    if not events:
        total += event_vspacing


    if not events:
        return max(min_box_height, total)

    for ev in events:
        try:
            h = _measure_row_height(ev, event_vspacing, min_icon_padding, draw, font, small_font,
                                    inner_w, event_icon_slot, icon_gap, max_event_lines)
        except Exception:
            # conservative fallback if measurement fails for any event
            fallback_text_h = getattr(font, "size", 12)
            h = max(event_vspacing, fallback_text_h + min_icon_padding)
        total += h

    return max(min_box_height, total)


# ---------------- Weather Helpers --------------------------------------------

def _gather_weather_values(entry: dict):
    """Return tuple (icon_name, temp_text, precip_text, wind_text)."""
    icon_keys = ("icon", "icon_name", "symbol", "weather_icon", "main", "symbol_code")
    temp_min_keys = ("temp_min", "min_temp", "tmin", "low", "temp_low", "min")
    temp_max_keys = ("temp_max", "max_temp", "tmax", "high", "temp_high", "max")
    temp_keys = ("temp", "temperature", "temp_c", "temp_celsius")
    precip_keys = ("rain_mm", "precip_mm", "precip", "rain", "rain_amount", "precipitation")
    wind_keys_ms = ("wind_m_s", "wind_ms", "wind_speed", "wind", "wind_max")

    icon = next((entry.get(k) for k in icon_keys if entry.get(k) is not None), None)

    tmin = next((entry.get(k) for k in temp_min_keys if entry.get(k) is not None), None)
    tmax = next((entry.get(k) for k in temp_max_keys if entry.get(k) is not None), None)
    temp_text = None
    if tmin is not None and tmax is not None:
        try:
            tmax = int(round(float(tmax)))
            tmin = int(round(float(tmin)))
            temp_text = f"{tmax}° / {tmin}°"
        except Exception:
            temp_text = f"{tmax}° / {tmin}°"
    elif next((entry.get(k) for k in temp_keys if entry.get(k) is not None), None) is not None:
        t = next((entry.get(k) for k in temp_keys if entry.get(k) is not None), None)
        try:
            temp_text = f"{int(round(float(t)))}°C"
        except Exception:
            temp_text = f"{t}°C"


    precip = next((entry.get(k) for k in precip_keys if entry.get(k) is not None), None)
    precip_text = None
    if precip is not None:
        try:
            precip_f = float(precip)
            # FIX: Divide by 10 to correct for tenths of mm scaling, as requested.
            precip_f /= 10.0 
            precip_text = f"{precip_f:.1f} mm"
        except Exception:
            precip_text = str(precip)
    
    wind_val = next((entry.get(k) for k in wind_keys_ms if entry.get(k) is not None), None)
    wind_dir = entry.get("wind_dir_deg") or entry.get("wind_deg") or None

    wind_text = None
    if wind_val is not None:
        try:
            wind_text = f"{float(wind_val):.1f} m/s"
        except Exception:
            wind_text = str(wind_val)
            
    # Combine wind speed and direction label (Direction is handled in render_calendar)
    return icon, temp_text, precip_text, wind_text, wind_dir


# ----------------- Rendering Section -----------------------------------------

# Defensive import for apply_event_mapping (optional)
apply_event_mapping = None
try:
    from mappings import apply_event_mapping
except Exception:
    pass

def render_events_section(image: Image.Image, x: int, y: int, width: int, events: List[dict],
                        font: ImageFont.ImageFont, small_font: ImageFont.ImageFont = None, tag_font: ImageFont.ImageFont = None,
                        icon_manager=None, event_vspacing: int = 14, icon_gap: int = 6,
                        text_color=0, dotted_line=False, dot_color=None, dot_gap=3,
                        min_icon_padding: int = 4, icon_pad_square: bool = True,
                        event_icon_slot: int = 20, tint_event_icons: bool = True,
                        max_event_lines: int = 2):
    """Draw events vertically and return new cursor_y below last drawn line."""
    draw = ImageDraw.Draw(image)
    cursor_y = y
    
    # Define tag constants used for layout
    tag_padding_x = 8
    tag_padding_y = 3
    tag_gap = 8

    # Initialize fonts defensively
    if small_font is None:
        small_font = _ensure_font(DEFAULT_FONT, max(10, getattr(font, "size", 12) - 2))
    if tag_font is None:
        tag_font = small_font

    body_rgb = _normalize_color_input(text_color)
    dot_rgb = _normalize_color_input(dot_color) if dot_color is not None else (0, 0, 0)
    
    for i, ev in enumerate(events):
        name = ev.get("display_text") or ev.get("name") or ""
        time = ev.get("time") or ""
        icon_name = ev.get("icon")
        requested_icon_size = ev.get("icon_size") or ev.get("icon_size_px") or max(12, event_icon_slot - 4)

        # Calculate line height (ensuring height calculation matches measurement function)
        line_height = _measure_row_height(ev, event_vspacing, min_icon_padding, draw, font, small_font,
                                          width - 16, event_icon_slot, icon_gap, max_event_lines)

        # Icon display sizing
        icon_display_h = max(10, int(line_height * 0.80))
        if icon_display_h > requested_icon_size:
            icon_display_h = requested_icon_size

        text_x = x + event_icon_slot + icon_gap
        text_w_avail = width - event_icon_slot - icon_gap - 8 # Safety margin

        # Draw Icon
        if icon_name:
            icon_im = _load_icon_image(icon_name, icon_display_h, icon_manager=icon_manager)
            if icon_im:
                icon_prepared = _resize_to_height_and_pad(icon_im, icon_display_h, pad_square=icon_pad_square)
                # Force event icons to be drawn in black (body_rgb)
                icon_to_draw = _tint_icon_to_color(icon_prepared, body_rgb)
                iw, ih = icon_to_draw.size
                slot_x = x + max(0, (event_icon_slot - iw) // 2)
                icon_y = cursor_y + line_height // 2 - ih // 2
                image.paste(icon_to_draw, (slot_x, icon_y), icon_to_draw)
            else:
                # Placeholder dot for missing icon
                ph_r = min(6, max(3, event_icon_slot // 4))
                ph_cx = x + event_icon_slot // 2
                ph_cy = cursor_y + line_height // 2
                draw.ellipse([ph_cx - ph_r, ph_cy - ph_r, ph_cx + ph_r, ph_cy + ph_r], fill=body_rgb, outline=None)

        # Draw Time
        name_x = text_x
        if time:
            time_w = _text_width(draw, time, small_font)
            draw.text((x + event_icon_slot + icon_gap, cursor_y), time, font=small_font, fill=body_rgb)
            name_x = x + event_icon_slot + icon_gap + time_w + 6

        # --- Wrapping and Drawing Name + Tags ---
        max_text_width = width - (name_x - x) - 8

        # Recalculate wrapping dimensions from _measure_row_height logic
        # 1. Determine reserved space for tags on the first line (simplified minimal tags for size calc)
        tags_for_measure = ev.get("tags") or []
        tag_text_raw = ev.get("tag_text") or ev.get("tag") or None
        if not tags_for_measure and tag_text_raw:
            parts = [p.strip() for p in tag_text_raw.split(",") if p.strip()]
            if parts: tags_for_measure = [{"text": p} for p in parts]

        tag_total_w = 0
        tag_count = 0
        for t in tags_for_measure:
            txt = (t.get("text") or "").strip()
            if not txt: continue
            tw = _text_width(draw, txt, small_font)
            chip_w = tw + tag_padding_x * 2
            if tag_total_w + chip_w + (tag_gap if tag_count > 0 else 0) > max_text_width // 2: break
            if tag_count > 0: tag_total_w += tag_gap
            tag_total_w += chip_w
            tag_count += 1
        
        reserved_for_tags = tag_total_w + (6 if tag_total_w > 0 else 0)
        name_max_width = max(8, text_w_avail - reserved_for_tags) 

        # 2. Simulate full wrapping to get lines
        words = (name or "").split()
        first_line = ""
        rest_text = ""
        for idx_w, w in enumerate(words):
            cand = (first_line + " " + w).strip() if first_line else w
            if _text_width(draw, cand, font) <= name_max_width:
                first_line = cand
            else:
                rest_text = " ".join(words[idx_w:])
                break
        if not first_line and words:
            first_line = _ellipsize(draw, words[0], font, name_max_width)
            rest_text = " ".join(words[1:]) if len(words) > 1 else ""

        remaining_lines = []
        if rest_text:
            remaining_lines = _wrap_text_to_lines(draw, rest_text, font, max_text_width, max(0, max_event_lines - 1))

        lines = [first_line] + remaining_lines
        if not lines: lines = [""]
        
        # 3. Draw first line text
        draw.text((name_x, cursor_y), lines[0], font=font, fill=body_rgb)

        # Get actual height of first line for tag placement
        try:
            bbox_1st = draw.textbbox((0, 0), lines[0] if lines[0] else "X", font=font)
            line_h_1st = bbox_1st[3] - bbox_1st[1]
        except Exception:
            line_h_1st = getattr(font, "size", 12)

        # Vertical position for chips on the first line (centered in the total row height)
        tag_top = cursor_y + (line_height // 2) - (tag_font.size // 2) # simplified vertical centering
        tag_top = max(cursor_y, tag_top) # don't draw above the current cursor
        
        # Draw tags on the first line
        displayed_name_w = _text_width(draw, lines[0], font)
        tag_start_x = name_x + displayed_name_w + 6
        max_right = x + width - 4
        
        after_tags_x = draw_event_tags(draw, tag_start_x, tag_top, ev, tag_font,
                                    padding_x=tag_padding_x, padding_y=tag_padding_y, gap=tag_gap, max_x=max_right)
        drew_on_first_line = (after_tags_x != tag_start_x)


        # 4. Draw subsequent wrapped lines
        if len(lines) > 1:
            spacing_px = max(2, int(line_h_1st * 0.12))
            second_y = cursor_y + line_h_1st + spacing_px
            ln_y = second_y
            
            # Recalculate line heights array for drawing if needed (already done in _measure_row_height but safe here)
            line_heights = []
            for ln in lines:
                try:
                    bbox = draw.textbbox((0, 0), ln if ln else "X", font=font)
                    line_heights.append(bbox[3] - bbox[1])
                except Exception:
                    line_heights.append(getattr(font, "size", 12))

            for idx_ln, ln in enumerate(lines[1:]):
                draw.text((name_x, ln_y), ln, font=font, fill=body_rgb)
                ln_y += line_heights[1 + idx_ln] + spacing_px
        
        # Advance cursor and draw dotted separator
        prev_cursor = cursor_y
        cursor_y += line_height # Use the calculated total line_height

        if dotted_line and i != len(events) - 1:
            y_line = prev_cursor + line_height - max(2, int(line_height * 0.18))
            pos = x
            end = x + width
            while pos < end:
                draw.rectangle([pos, y_line, pos + 1, y_line + 1], fill=dot_rgb)
                pos += dot_gap

    return cursor_y


def render_calendar(data: dict, width: int, height: int, days: int = 8, renderer_opts: dict = None):
    opts = renderer_opts or {}

    # options
    border_thickness = int(opts.get("border_thickness", 2))
    round_radius = int(opts.get("round_radius", 6))
    underline_date = bool(opts.get("underline_date", False))
    dotted_line_between_events = bool(opts.get("dotted_line_between_events", True))
    event_vspacing = int(opts.get("event_vspacing", 14))
    font_small_size = int(opts.get("font_small_size", 12))
    font_bold_size = int(opts.get("font_bold_size", 14))
    dot_gap = int(opts.get("dot_gap", 3))
    dot_color = opts.get("dot_color", "black")
    min_box_height = int(opts.get("min_box_height", 48))
    show_more_text = bool(opts.get("show_more_text", True))
    columns = int(opts.get("columns", 2))
    grid_gap = int(opts.get("grid_gap", 12))
    box_header_height = int(opts.get("box_header_height", 26))
    box_radius = int(opts.get("box_radius", round_radius))
    box_header_padding = int(opts.get("box_header_padding", 6))
    min_icon_padding = int(opts.get("min_icon_padding", 4))
    top_padding = int(opts.get("box_top_padding", 8))
    bottom_padding = int(opts.get("box_bottom_padding", 8))

    # event icon slot width (pixels)
    event_icon_slot = int(opts.get("event_icon_slot", 20))
    icon_pad_square = bool(opts.get("icon_pad_square", True))
    tint_event_icons = bool(opts.get("tint_event_icons", True))

    icon_gap = int(opts.get("icon_gap", 6))
    max_event_lines = int(opts.get("max_event_lines", 2))

    background_raw = opts.get("background", 255)
    bg_rgba = _normalize_bg(background_raw)
    lum = _luminance_from_color(background_raw)
    text_color_opt = opts.get("text_color", None)
    default_text_color_raw = text_color_opt if text_color_opt is not None else (0 if lum > 0.5 else 255)

    # normalize colors
    header_fill_raw = opts.get("header_fill_color", (255, 153, 0))
    header_text_raw = opts.get("header_text_color", None)
    if header_text_raw is None:
        header_text_raw = ("white" if opts.get("invert_text_on_fill", True) else "black")
    box_outline_raw = opts.get("border_color", "black")
    body_text_raw = default_text_color_raw

    hf = _normalize_bg(header_fill_raw)
    header_fill_rgba = (hf[0], hf[1], hf[2], 255)
    header_text_rgb = _normalize_color_input(header_text_raw)
    box_outline_rgb = _normalize_color_input(box_outline_raw)
    body_text_rgb = _normalize_color_input(body_text_raw)
    dot_rgb = _normalize_color_input(dot_color)

    # expose for fallback glyph
    globals()["box_outline_rgb"] = box_outline_rgb

    base = Image.new("RGBA", (width, height), color=bg_rgba)
    draw = ImageDraw.Draw(base)
    
    font_path = opts.get("font_path", DEFAULT_FONT)
    bold_font_path = opts.get("bold_font_path", DEFAULT_BOLD_FONT)
    font = _ensure_font(font_path, max(10, font_small_size))
    bold_font = _ensure_font(bold_font_path, font_bold_size)
    small_font = _ensure_font(font_path, font_small_size)

    # Initialize weather_tag_font (used for tags/weather text)
    weather_tag_font = small_font
    
    events = data.get("events", []) or []

    # Apply mapping if available (Kept as requested)
    if callable(apply_event_mapping):
        mapped_events = []
        for ev in events:
            ev_copy = dict(ev)
            if not ev_copy.get("tags"):
                try:
                    # Defensive check for name existence before calling mapping
                    event_name = ev_copy.get("name", "") if ev_copy.get("name") is not None else ""
                    mapped = apply_event_mapping(event_name)
                except Exception:
                    mapped = {}
                for k in ("display_text", "tags", "tag_text", "tag_color_name", "tag_color_rgb",
                        "icon", "icon_size", "icon_color_name", "icon_color_rgb", "mode", "original_name"):
                    if k in mapped and mapped[k] is not None:
                        ev_copy[k] = mapped[k]
            mapped_events.append(ev_copy)
        events = mapped_events
        data["events"] = events

    groups = _group_events_by_date(events)
    # FIX: always render a continuous date range (including empty days / weekends)
    if events:
        try:
            start_date = min(
                datetime.fromisoformat(ev["date"]).date()
                for ev in events
                if ev.get("date")
            )
        except Exception:
            start_date = datetime.today().date()
    else:
        start_date = datetime.today().date()

    ordered_dates = [
        (start_date + timedelta(days=i)).isoformat()
        for i in range(days)
    ]

    margin_x = 3
    margin_y = 3
    gap = grid_gap
    box_w = (width - margin_x * 2 - (columns - 1) * gap) // columns
    inner_w = box_w - 16 # Available width for text content

    date_heights = {}
    for d in ordered_dates:
        evs = groups.get(d, [])
        h = _measure_box_height_for_date(evs, box_header_height, event_vspacing, min_icon_padding,
                                        draw, font, small_font, inner_w, event_icon_slot, icon_gap,
                                        top_padding=top_padding, bottom_padding=bottom_padding,
                                        min_box_height=min_box_height, max_event_lines=max_event_lines)
        date_heights[d] = h

    placements = {}
    col_width = box_w
    col_x_positions = [margin_x + c * (col_width + gap) for c in range(columns)]
    bottom_limit = height - 3
    col_tops = [margin_y for _ in range(columns)]
    current_col = 0

    for d in ordered_dates:
        h = date_heights[d]
        placed = False
        for col_try in range(current_col, columns):
            if col_tops[col_try] + h <= bottom_limit:
                current_col = col_try
                x = col_x_positions[current_col]
                y = col_tops[current_col]
                placements[d] = (x, y, h)
                col_tops[current_col] = y + h + gap
                placed = True
                break

        if not placed:
            continue # skip if no room left

    for date_key, (x, y, box_h) in placements.items():
        hx0 = x + border_thickness
        hy0 = y + border_thickness
        hx1 = x + box_w - border_thickness
        hy1 = y + box_header_height

        header_fill_rect = [hx0, hy0, hx1, hy1]
        
        draw_header_fill = header_fill_rgba
        try:
            dt = datetime.fromisoformat(date_key)
            if dt.weekday() >= 5: # Saturday (5) or Sunday (6)
                weekend_col = opts.get('weekend_header_fill_color', (255, 0, 0))
                wf = _normalize_bg(weekend_col)
                draw_header_fill = (wf[0], wf[1], wf[2], 255)
        except Exception:
            pass
            
        try:
            draw.rounded_rectangle(header_fill_rect, radius=box_radius, fill=draw_header_fill)
        except Exception:
            draw.rectangle(header_fill_rect, fill=draw_header_fill)

        try:
            # Draw header outline (slightly larger to cover main box border)
            draw.rounded_rectangle([x + 1, y + 1, x + box_w - 1, y + box_header_height + 1], radius=box_radius, outline=box_outline_rgb, width=border_thickness, fill=None)
        except Exception:
            draw.rectangle([x, y, x + box_w, y + box_header_height], outline=box_outline_rgb, width=border_thickness)

        # Draw full box outline
        try:
            draw.rounded_rectangle([x, y, x + box_w, y + box_h], radius=box_radius,
                                outline=box_outline_rgb, width=border_thickness, fill=None)
        except Exception:
            draw.rectangle([x, y, x + box_w, y + box_h], outline=box_outline_rgb, width=border_thickness)

        # Format date
        pretty = date_key
        try:
            dt = datetime.fromisoformat(date_key)
            wk = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]
            months = ["Jan", "Feb", "Mar", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Des"]
            pretty = f"{wk[dt.weekday()]} {dt.day} {months[dt.month - 1]}"
        except Exception:
            pass
        draw.text((x + box_header_padding, y + 3), pretty, font=bold_font, fill=header_text_rgb)

        # Weather Info
        weather_entry = next((w for w in data.get("weather", []) if w.get("date") == date_key), None)

        if weather_entry:
            icon, temp_text, precip_text, wind_text, wind_dir = _gather_weather_values(weather_entry)

            small_icon_size = 16
            gap_between_parts = 10
            right_x = x + box_w - box_header_padding

            # Helper to draw icon+text right-aligned, returns new right_x
            def _draw_icon_and_text_right(icon_key, text, r_x, y_top, icon_h, font_for_text):
                if not text:
                    return r_x
                p_w = _text_width(draw, text, font_for_text)
                icon_im = _load_icon_image(icon_key, icon_h, icon_manager=opts.get("icon_manager"))
                text_x = r_x - p_w

                min_x_for_text = x + box_header_padding + _text_width(draw, pretty, bold_font) + 8
                if text_x < min_x_for_text:
                    return r_x # No space

                if icon_im:
                    icon_prepared = _resize_to_height_and_pad(icon_im, icon_h, pad_square=True)
                    icon_tinted = _tint_icon_to_color(icon_prepared, header_text_rgb)
                    iw, ih = icon_tinted.size
                    icon_x = text_x - iw - 6
                    
                    if icon_x < min_x_for_text:
                        draw.text((text_x, y + 6), text, font=font_for_text, fill=header_text_rgb)
                        return text_x - gap_between_parts
                    
                    icon_y = y + ((box_header_height - ih) // 2)
                    base.paste(icon_tinted, (icon_x, icon_y), icon_tinted)
                    draw.text((text_x, y + 6), text, font=font_for_text, fill=header_text_rgb)
                    return icon_x - gap_between_parts
                else:
                    draw.text((text_x, y + 6), text, font=font_for_text, fill=header_text_rgb)
                    return text_x - gap_between_parts

            # Draw in order: Temp -> Wind -> Precip
            if temp_text:
                right_x = _draw_icon_and_text_right("thermometer", temp_text, right_x, y, small_icon_size, weather_tag_font)

            if wind_text:
                # Combine wind speed and direction label (FIX: Restore wind direction)
                wind_label = wind_text
                try:
                    if wind_dir is not None:
                        dir_short = _deg_to_cardinal(float(wind_dir))
                        if dir_short:
                            wind_label = f"{wind_label} {dir_short}"
                except Exception:
                    pass
                right_x = _draw_icon_and_text_right("wind", wind_label, right_x, y, small_icon_size, weather_tag_font)

            if precip_text:
                right_x = _draw_icon_and_text_right("cloud-rain", precip_text, right_x, y, small_icon_size, weather_tag_font)


        if underline_date:
            date_w = _text_width(draw, pretty, bold_font)
            date_x = x + box_header_padding
            underline_y = hy1 - 4
            draw.line((date_x, underline_y, date_x + date_w, underline_y), fill=box_outline_rgb, width=1)

        inner_x = x + 10
        inner_y = y + box_header_height + top_padding
        inner_w = box_w - 16
        max_bottom = y + box_h - bottom_padding

        evs = groups.get(date_key, [])
        try:
            evs = sorted(evs, key=lambda e: e.get("time") or "")
        except Exception:
            pass

        cur_y = inner_y
        if evs:
            cur_y = render_events_section(base, inner_x, cur_y, inner_w, evs, font,
                                        small_font=small_font, tag_font=weather_tag_font, icon_manager=opts.get("icon_manager"),
                                        event_vspacing=event_vspacing, icon_gap=icon_gap,
                                        text_color=body_text_rgb, dotted_line=dotted_line_between_events,
                                        dot_color=dot_rgb, dot_gap=dot_gap, min_icon_padding=min_icon_padding,
                                        icon_pad_square=icon_pad_square, event_icon_slot=event_icon_slot,
                                        tint_event_icons=tint_event_icons, max_event_lines=max_event_lines)
        else:
            placeholder = opts.get("no_events_text", "")
            if placeholder:
                draw.text((inner_x, cur_y), placeholder, font=font, fill=body_text_rgb)

        if cur_y > max_bottom and show_more_text:
            more_y = max_bottom - getattr(font, "size", 12)
            draw.text((inner_x, more_y), "…", font=font, fill=body_text_rgb)

    return base

# Removed helper function make_mockup_with_bezel as it was outside core calendar rendering.