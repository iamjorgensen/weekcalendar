"""
Orkestrator: henter data og lager både raw output.png, en JPEG for Inky,
og en spritesheet .bin for best kvalitet på Inky Frame.
Bruk: python main_complete.py --days 10
Krev: pip install pillow requests
"""

import argparse
import os
from pathlib import Path

from data_provider import initial_fetch_all
from layout_renderer import render_calendar
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
    "tag_font": "Inter-SemiBold.ttf",   # filename in assets/fonts OR full path
    "tag_font_size": 16,  
    "weather_tag_font": "Inter-SemiBold.ttf",   # filename in assets/fonts or full path
    "weather_tag_font_size": 30,                # integer
    "weather_gap": 0,                            # pixel gap between each weather info block (default 
    "icon_gap": 2
}

opts["icon_manager"] = IconManager()
opts["event_mappings"] = EVENT_MAPPINGS
opts["tint_event_icons"] = True


def _atomic_save(img, out_path, fmt, **kwargs):
    """
    Write to a temp file and rename into place, so the web server never
    serves a half-written image while a render is in progress.
    """
    out_path = Path(out_path)
    tmp = out_path.with_name(out_path.name + ".tmp")
    img.save(tmp, fmt, **kwargs)
    os.replace(tmp, out_path)
    return out_path


def save_jpeg_fast(img, out_path="output.jpg"):
    """
    JPEG for the Inky Frame: quality=100 and no chroma subsampling to keep
    text edges sharp. Note: this is ~300+ KB, more than a Pico W's RAM.
    """
    img = img.convert("RGB")
    _atomic_save(img, out_path, "JPEG", quality=100, subsampling=0)
    size_kb = os.path.getsize(out_path) // 1024
    print(f"Saved JPEG: {out_path} ({size_kb} KB)")
    if size_kb > 200:
        print(f"[WARN] JPEG is {size_kb} KB; frames that buffer the download in RAM may fail to show it")
    return out_path


def save_png(img, out_path="output.png"):
    """
    Lossless PNG. The image is already quantized to the 6 panel colours, so
    this is typically ~15-30 KB and has no JPEG artifacts.
    """
    img = img.convert("RGB")
    _atomic_save(img, out_path, "PNG", optimize=True)
    print(f"Saved PNG: {out_path} ({os.path.getsize(out_path) // 1024} KB)")
    return out_path

# save_spritesheet and finalize_image_for_inky related functions are removed.


def _try_render_calendar(events, opts, width=800, height=480, days=8):
    """
    Render the calendar image. Uses the design named by opts["design"] or the
    DESIGN env var (default "dense"; "legacy" = the original layout_renderer).
    If a new design fails for any reason, falls back to the legacy layout so
    the frame always gets an image.
    """
    design = (opts or {}).get("design") or os.environ.get("DESIGN", "dense")
    if design and design != "legacy":
        try:
            from designs import render_design
            return render_design(design, events or {}, days, icon_manager=(opts or {}).get("icon_manager"))
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[design] '{design}' failed ({e}); falling back to legacy layout")
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
    parser.add_argument("--out-png", type=str, default="output.png", help="Output PNG path (empty to skip)")
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

    ok = True
    try:
        save_jpeg_fast(img, out_path=args.out_jpg)
    except Exception as e:
        print("save_jpeg_fast failed:", e)
        ok = False
    if args.out_png:
        try:
            save_png(img, out_path=args.out_png)
        except Exception as e:
            print("save_png failed:", e)
            ok = False
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
