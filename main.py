"""
Orkestrator: henter data og lager både raw output.png, en JPEG for Inky,
og en spritesheet .bin for best kvalitet på Inky Frame.
Bruk: python main_complete.py --days 10
Krev: pip install pillow requests
"""

import argparse
from pathlib import Path

from data_provider import initial_fetch_all
from layout_renderer import render_calendar
from inky_adapter import display_on_inky_if_available, save_png
from inky_icons_package import IconManager
from mappings import EVENT_MAPPINGS

from PIL import Image

# --- Inky palette quantize helpers (REMOVED: Only JPEG output is requested) ---
# INKY_PALETTE_INDEXED, _make_palette_image_from_indexed, finalize_image_for_inky, save_spritesheet_from_quant are removed.

# --- renderer options ---
opts = {
    "border_thickness": 2,
    "round_radius": 2,
    "underline_date": False,
    "day_fill": False,
    "invert_text_on_fill": True,
    "header_inverted": True,
    "header_fill_color": "GREEN",
    "header_text_color": "WHITE",
    "dotted_line_between_events": True,
    "event_vspacing": 14,
    "font_small_size": 16,
    "font_bold_size": 16,
    "dot_gap": 611,
    "dot_color": "WHITE",
    "heading_color": "BLACK",
    "text_color": "BLACK",
    "border_color": "BLACK",
    "min_box_height": 48,
    "show_more_text": True,
    "weather_debug": True,
    "tag_font": "Roboto-Bold.ttf",   # filename in assets/fonts OR full path
    "tag_font_size": 16,  
    "weather_tag_font": "Roboto-Regular.ttf",   # filename in assets/fonts or full path
    "weather_tag_font_size": 30,                # integer
    "weather_gap": 0,                            # pixel gap between each weather info block (default 
    "icon_gap": 2
}

opts["icon_manager"] = IconManager()
opts["event_mappings"] = EVENT_MAPPINGS
opts["tint_event_icons"] = True


def save_jpeg_fast(img, out_path="output.jpg"):
    """
    Optimized for Inky Frame Spectra 7:
    Forces 100% quality and disables Chroma Subsampling to keep 
    text edges razor-sharp and prevent color 'bleeding'.
    """
    # Ensure the image is in RGB mode (required for JPEG)
    img = img.convert("RGB")
    
    # quality=100: Prevents compression artifacts (shadings)
    # subsampling=0: The 'Secret Sauce' that stops color bleeding/blurring
    img.save(out_path, "JPEG", quality=100, subsampling=0)
    
    print(f"Saved Ultra-Crisp JPEG: {out_path}")
    return out_path

# save_spritesheet and finalize_image_for_inky related functions are removed.


def _try_render_calendar(events, opts, width=800, height=480, days=8):
    """
    Call render_calendar with the expected signature: render_calendar(data, width, height, days, renderer_opts)
    Returns a PIL Image.
    """
    try:
        img = render_calendar(events, width, height, days, opts)
        return img
    except TypeError as e:
        # try alternate ordering if code expects different arg order
        try:
            img = render_calendar(events, width, height, renderer_opts=opts)
            return img
        except Exception:
            print("render_calendar TypeError attempts failed:", e)
            raise
    except Exception as e:
        print("render_calendar failed:", e)
        raise


# _save_png_fallback is removed as png output is not desired.


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate InkyFrame calendar images")
    parser.add_argument("--days", type=int, default=7, help="How many days to fetch")
    # Removed --out-png argument
    parser.add_argument("--out-jpg", type=str, default="output.jpg", help="Output JPEG path")
    # Removed --out-bin argument
    parser.add_argument("--debug-bezel", action="store_true", help="Also create mockup with bezel")
    parser.add_argument("--no-inky", action="store_true", help="Do not attempt to display on Inky even if available")
    args = parser.parse_args(argv)

    # Fetch data
    try:
        print(f"Fetching data for {args.days} days...")
        data = initial_fetch_all(days=args.days)
    except TypeError:
        # some providers expect a different signature
        data = initial_fetch_all(args.days)
    except Exception as e:
        print("Data fetch failed:", e)
        data = {}  # fallback to empty

    # attach options
    render_opts = dict(opts)  # copy global opts
    render_opts["days"] = args.days

    # Render calendar image
    try:
        img = _try_render_calendar(data, render_opts, width=800, height=480, days=args.days)
    except Exception as e:
        print("Primary render failed, attempting fallback empty render:", e)
        try:
            img = _try_render_calendar({}, render_opts, width=800, height=480, days=args.days)
        except Exception as e2:
            print("Fallback render failed:", e2)
            raise SystemExit(1)

    # Ensure we have a PIL.Image
    from PIL import Image as _Image
    if not hasattr(img, "convert"):
        # maybe render returned (img, meta)
        if isinstance(img, (list, tuple)) and len(img) > 0:
            img_candidate = img[0]
            if hasattr(img_candidate, "convert"):
                img = img_candidate
            else:
                raise RuntimeError("render_calendar did not return an image")
        else:
            raise RuntimeError("render_calendar did not return an image")

    # Produce JPEG (fast)
    try:
        save_jpeg_fast(img, out_path=args.out_jpg)
    except Exception as e:
        print("save_jpeg_fast failed:", e)
        try:
            # Note: args.out_jpg is guaranteed to exist due to argparse default.
            img.convert("RGB").save(args.out_jpg, quality=95) 
            print("Saved JPG via PIL fallback:", args.out_jpg)
        except Exception as e2:
            print("Failed to save JPG fallback:", e2)


if __name__ == "__main__":
    main()
