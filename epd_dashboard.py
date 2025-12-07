#!/usr/bin/env python3
"""
Simple EPD dashboard
Top half: clock + date
Bottom half: server status + last journal line for the service

No logo, no data_provider. Robust for multiple Pillow versions.
"""
import sys, os, time, subprocess, logging
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# --- Config ---
PY_WS_PATH = "/home/iamjorgensen/e-Paper/RaspberryPi_JetsonNano/python/lib"
FONT_BOLD = "/home/iamjorgensen/weekcalendar/assets/fonts/Fredoka-Bold.ttf"
FONT_REG = "/home/iamjorgensen/weekcalendar/assets/fonts/Roboto-Regular.ttf"
SERVICE_NAME = "weekcalendar-server.service"
LOGFILE = "/home/iamjorgensen/weekcalendar/epd_dashboard.log"
POLL_SECONDS = 60
FULL_REFRESH_MIN = 10
# --- end config ---

os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
                    handlers=[logging.FileHandler(LOGFILE), logging.StreamHandler()])
log = logging.getLogger("epd_dashboard")

# Ensure waveshare lib path available
if PY_WS_PATH not in sys.path:
    sys.path.insert(0, PY_WS_PATH)

# Try to import waveshare epd
epd = None
try:
    from waveshare_epd import epd1in54_V2 as epd_mod
    try:
        epd = epd_mod.EPD()
        try:
            epd.init(False)
        except TypeError:
            epd.init()
        log.info("EPD initialized")
    except Exception as e:
        log.warning("EPD init failed - running dry-run: %s", e)
        epd = None
except Exception as e:
    log.warning("waveshare_epd import failed - running dry-run: %s", e)
    epd = None

# helpers
def run_cmd(cmd, timeout=6):
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT,
                                       universal_newlines=True, timeout=timeout).strip()
    except Exception:
        return ""

def get_server_status(unit=SERVICE_NAME):
    """Return dict with ok:bool and last_run:timestamp (or None) and last_journal_line"""
    out = {"ok": False, "last_run": None, "last_line": None}
    try:
        active = run_cmd(f"systemctl is-active {unit}")
        out["ok"] = (active.strip() == "active")
        last = run_cmd(f"journalctl -u {unit} -n 1 --no-pager --output=short")
        if last:
            out["last_line"] = last
            # parse timestamp (Mon DD HH:MM:SS)
            parts = last.split()
            if len(parts) >= 3:
                mon, day, tm = parts[0], parts[1], parts[2]
                try:
                    curr_year = datetime.now().year
                    dt = datetime.strptime(f"{mon} {day} {curr_year} {tm}", "%b %d %Y %H:%M:%S")
                    out["last_run"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    out["last_run"] = None
    except Exception as e:
        log.exception("get_server_status failed: %s", e)
    return out

# robust text sizing for many PIL versions
def text_size(draw, text, font):
    try:
        # PIL/Pillow FreeTypeFont
        bbox = font.getbbox(text)
        return (bbox[2]-bbox[0], bbox[3]-bbox[1])
    except Exception:
        pass
    try:
        # newer Pillow
        bbox = draw.textbbox((0,0), text, font=font)
        return (bbox[2]-bbox[0], bbox[3]-bbox[1])
    except Exception:
        pass
    try:
        # older fallback
        return font.getsize(text)
    except Exception:
        # very last fallback (approx)
        return (len(text)*6, 12)

# safe font loader
def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.load_default()
        except Exception:
            return None

# display size detection (fall back to 200x200)
if epd:
    try:
        W, H = epd.height, epd.width
    except Exception:
        W, H = 200, 200
else:
    W, H = 200, 200
log.info("Using display %sx%s (epd present: %s)", W, H, bool(epd))

# render: 2px outer frame; top half clock/date; bottom half serverstatus
def render_dashboard_image(clock_dt, server_status, w=W, h=H):
    im = Image.new("1", (w, h), 255)
    draw = ImageDraw.Draw(im)

    # fonts
    f_clock = load_font(FONT_BOLD, 36) or ImageFont.load_default()
    f_date = load_font(FONT_REG, 24) or ImageFont.load_default()
    f_status = load_font(FONT_BOLD, 36) or ImageFont.load_default()
    f_small = load_font(FONT_REG, 16) or ImageFont.load_default()
    f_label = load_font(FONT_REG, 24) 

    # draw 2px frame (some PIL versions ignore width on '1' mode -> draw two rectangles)
    draw.rectangle((0,0,w-1,h-1), outline=0)
    draw.rectangle((1,1,w-2,h-2), outline=0)

    mid = 70
    # top half: clock + date
    timestr = clock_dt.strftime("%H:%M")
    t_w, t_h = text_size(draw, timestr, f_clock)
    tx = (w - t_w) // 2
    ty =  5
    draw.text((tx, ty), timestr, font=f_clock, fill=0)

    date_str = clock_dt.strftime("%A, %b %d")
    d_w, d_h = text_size(draw, date_str, f_date)
    dx = (w - d_w) // 2
    dy = ty + t_h + 10
    draw.text((dx, dy), date_str, font=f_date, fill=0)

    # horizontal divider line
    draw.line((4, mid, w-5, mid), fill=0)

    # bottom half: server status
    status_text = "OK" if server_status.get("ok") else "FAIL"
    s_w, s_h = text_size(draw, status_text, f_status)
    sx = (w - s_w) // 2
    bottom_top = mid + 3
    bottom_h = h - bottom_top 
    sy = bottom_top + max(0, (bottom_h//2) - (s_h//2)) -30
    draw.text((sx, sy), status_text, font=f_status, fill=0)

    # small label above status
    label = "SERVER"
    lb_w, lb_h = text_size(draw, label, f_label)
    draw.text(((w - lb_w)//2, bottom_top + 2), label, font=f_small, fill=0)

    # last journal line (truncate to fit)
    last_line = server_status.get("last_line") or ""
    # keep only the message part (after hostname) to avoid overflowing timestamp
    if last_line:
        # attempt to strip the leading date/host part
        try:
            parts = last_line.split(None, 4)
            if len(parts) >= 5:
                msg = parts[4]
            else:
                msg = last_line
        except Exception:
            msg = last_line
        # truncate to ~36 chars based on width estimate
        max_chars = max(20, (w - 24) // 6)
        if len(msg) > max_chars:
            msg = msg[:max_chars-3] + "..."
        draw.text((8, sy + s_h + 10), msg, font=f_small, fill=0)

    # also show last_run timestamp if available (small)
    last_run = server_status.get("last_run")
    if last_run:
        lr = f"Last: {last_run}"
        lr_w, lr_h = text_size(draw, lr, f_small)
        draw.text(((w - lr_w)//2, h - lr_h - 6), lr, font=f_small, fill=0)

    return im

# main loop
def main_loop():
    log.info("Starting main loop")
    last_full = 0
    try:
        while True:
            now = datetime.now()
            status = get_server_status(SERVICE_NAME)

            img = render_dashboard_image(now, status, W, H)

            if epd:
                try:
                    if time.time() - last_full > FULL_REFRESH_MIN * 60:
                        log.info("Full refresh")
                        epd.display(epd.getbuffer(img))
                        last_full = time.time()
                    else:
                        if hasattr(epd, "displayPartial"):
                            epd.displayPartial(epd.getbuffer(img))
                        else:
                            epd.display(epd.getbuffer(img))
                except Exception as e:
                    log.exception("EPD display error: %s", e)
            else:
                log.info("Dry-run: image rendered (not sent to epd)")

            sleep_for = POLL_SECONDS - (datetime.now().second % POLL_SECONDS)
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        if epd:
            try:
                epd.sleep()
            except Exception:
                pass

if __name__ == "__main__":
    main_loop()
