# Inky Frame 7.3" (Pico 2 W) - weekcalendar client
#
# Wakes at UPDATE_TIMES (and whenever a front button wakes it), downloads the
# calendar image and shows it. Works with both:
#   - AWS:  CALENDAR_URL = "https://<id>.lambda-url.eu-west-1.on.aws/image.png?token=<FRAME_TOKEN>&fresh=1"
#   - Pi:   CALENDAR_URL = "http://inkyserver.local:8000/image", PRE_TRIGGER_URL = ".../run-main?wait=1"
# PNG or JPEG is detected from the file itself.
#
# Settings and passwords live in secrets.py on the frame (see secrets_example.py).

import gc
import os
import time

import machine
import network
import ntptime
import urequests
import inky_frame
from picographics import PicoGraphics, DISPLAY_INKY_FRAME_SPECTRA_7 as D

import secrets

UPDATE_TIMES = getattr(secrets, "UPDATE_TIMES", ["04:00"])   # local Oslo time
GRACE_SECS = 120
BUTTON_A_PIN = 12
HTTP_TIMEOUT = 90          # a fresh render on AWS can take up to ~70 s
IMG_PNG = "c.png"
IMG_JPG = "c.jpg"
TMP = "dl.tmp"

# Pen numbers as used by the original code on this display
BLACK, WHITE, GREEN, RED, YELLOW = 0, 1, 2, 4, 5

g = PicoGraphics(D)


# ------------------------------------------------------------------ time
def _last_sunday(year, month):
    # weekday of the 31st (March and October both have 31 days); Monday = 0
    wd = time.gmtime(time.mktime((year, month, 31, 1, 0, 0, 0, 0)))[6]
    return 31 - ((wd + 1) % 7)


def oslo_offset(utc_ts=None):
    """Seconds to add to UTC: +2h in EU summer time, otherwise +1h."""
    if utc_ts is None:
        utc_ts = time.time()
    y = time.gmtime(utc_ts)[0]
    start = time.mktime((y, 3, _last_sunday(y, 3), 1, 0, 0, 0, 0))
    end = time.mktime((y, 10, _last_sunday(y, 10), 1, 0, 0, 0, 0))
    return 7200 if start <= utc_ts < end else 3600


def local_now():
    return time.localtime(time.time() + oslo_offset())


def get_sleep_mins():
    now = local_now()
    now_ts = time.mktime(now)
    candidates = []
    for t_str in UPDATE_TIMES:
        h, m = t_str.split(":")
        ts = time.mktime((now[0], now[1], now[2], int(h), int(m), 0, 0, 0))
        # Only times clearly in the future: if we just ran at (or slightly
        # before) an update time, don't wake again for that same slot.
        if ts - GRACE_SECS > now_ts:
            candidates.append(ts)
    if candidates:
        return max(1, int(min(candidates) - now_ts) // 60)
    h, m = UPDATE_TIMES[0].split(":")
    ts = time.mktime((now[0], now[1], now[2], int(h), int(m), 0, 0, 0)) + 86400
    return max(1, int(ts - now_ts) // 60)


# ------------------------------------------------------------------ battery
def get_batt():
    # NOTE: GPIO29 is shared with the WiFi chip. Only call this after WiFi is
    # done; WiFi stays broken until a hard reset (see end of main()).
    v = machine.ADC(29).read_u16() * (9.9 / 65535)
    p = int((v - 3.2) * 100 / (4.2 - 3.2))
    return v, min(100, max(0, p))


# ------------------------------------------------------------------ files
def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def last_image():
    """Path of the last good image on flash, or None."""
    for p in (IMG_PNG, IMG_JPG):
        if _exists(p):
            return p
    return None


# ------------------------------------------------------------------ network
WIFI_STATUS = {-3: "feil passord", -2: "fant ikke nettet", -1: "tilkobling feilet", 0: "ikke startet", 1: "kobler til"}


def wifi_connect():
    """Connect, with one full retry. Error text includes the chip's status code."""
    try:
        import rp2
        rp2.country(getattr(secrets, "WIFI_COUNTRY", "NO"))   # allow channels 12-13
    except Exception:
        pass
    w = network.WLAN(network.STA_IF)
    status = None
    for attempt in range(2):
        w.active(False)
        time.sleep(1)
        w.active(True)
        try:
            w.config(pm=0xa11140)   # disable WiFi power saving: faster, more reliable join
        except Exception:
            pass
        w.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
        for _ in range(45):
            if w.isconnected():
                return w
            status = w.status()
            if status in (-3, -2):   # wrong password / no network: retrying won't help
                break
            time.sleep(1)
        print("WiFi attempt", attempt + 1, "failed, status", status)
        if status in (-3, -2):
            break
    raise RuntimeError("WiFi feilet ({}: {})".format(status, WIFI_STATUS.get(status, "?")))


def download(url):
    """
    Stream the image to flash in small chunks (never holds the whole file in
    RAM - the old r.content approach failed on large JPEGs). Returns
    (path, status) where status is the server's X-Render-Status or "".
    """
    gc.collect()
    r = urequests.get(url, timeout=HTTP_TIMEOUT)
    try:
        if r.status_code != 200:
            raise RuntimeError("HTTP {}".format(r.status_code))
        headers = getattr(r, "headers", {}) or {}
        status = headers.get("X-Render-Status") or headers.get("x-render-status") or ""
        expected = headers.get("Content-Length") or headers.get("content-length")
        size = 0
        with open(TMP, "wb") as f:
            while True:
                chunk = r.raw.read(2048)
                if not chunk:
                    break
                f.write(chunk)
                size += len(chunk)
    finally:
        r.close()

    if expected and int(expected) != size:
        _remove(TMP)
        raise RuntimeError("Ufullstendig bilde ({}/{} B)".format(size, expected))

    with open(TMP, "rb") as f:
        magic = f.read(4)
    if magic == b"\x89PNG":
        target = IMG_PNG
    elif magic[:2] == b"\xff\xd8":
        target = IMG_JPG
    else:
        _remove(TMP)
        raise RuntimeError("Ukjent bildeformat")

    # keep exactly one last-good image
    _remove(IMG_PNG)
    _remove(IMG_JPG)
    os.rename(TMP, target)
    return target, status


# ------------------------------------------------------------------ drawing
def draw_image(path):
    gc.collect()
    if path.endswith(".png"):
        from pngdec import PNG
        p = PNG(g)
        p.open_file(path)
        mode = getattr(PNG, "PNG_POSTERISE", None)
        if mode is not None:
            p.decode(0, 0, mode=mode)
        else:
            p.decode(0, 0)
    else:
        from jpegdec import JPEG
        j = JPEG(g)
        j.open_file(path)
        j.decode(0, 0)


def draw_status(error=None, stale=False):
    """Small box bottom-left: time, battery, and an error/stale note if any."""
    v, p = get_batt()
    ts = local_now()
    time_str = "{:02d}:{:02d}".format(ts[3], ts[4])
    batt_str = "{}%".format(p)
    note = ""
    if error:
        note = "Feil: " + str(error)[:60]
    elif stale:
        note = "Gammelt bilde"

    g.set_font("bitmap8")
    scale, char_h = 1, 8
    icon_w, icon_h, pad = 24, 12, 4
    time_w = g.measure_text(time_str, scale)
    batt_w = g.measure_text(batt_str, scale)
    note_w = g.measure_text(note, scale) + pad if note else 0
    total_w = time_w + icon_w + batt_w + note_w + pad * 4
    total_h = icon_h + pad * 2
    bx, by = 2, 480 - total_h - 2
    cy = by + total_h // 2
    text_y = cy - char_h // 2
    icon_y = cy - icon_h // 2

    g.set_pen(WHITE)
    g.rectangle(bx, by, total_w, total_h)
    g.set_pen(BLACK)
    g.text(time_str, bx + pad, text_y, scale=scale)

    ix = bx + pad + time_w + pad
    g.rectangle(ix, icon_y, icon_w, icon_h)
    g.rectangle(ix + icon_w, icon_y + 3, 2, 6)
    g.set_pen(WHITE)
    g.rectangle(ix + 1, icon_y + 1, icon_w - 2, icon_h - 2)
    g.set_pen(GREEN if p > 50 else YELLOW if p > 20 else RED)
    fill = int((icon_w - 4) * (p / 100))
    if fill > 0:
        g.rectangle(ix + 2, icon_y + 2, fill, icon_h - 4)
    g.set_pen(BLACK)
    g.text(batt_str, ix + icon_w + pad, text_y, scale=scale)

    if note:
        g.set_pen(RED)
        g.text(note, ix + icon_w + pad + batt_w + pad, text_y, scale=scale)


def refresh():
    print("Refreshing screen...")
    inky_frame.led_busy.on()
    g.update()
    inky_frame.led_busy.off()


# ------------------------------------------------------------------ main flow
def do_update():
    error = None
    stale = False
    path = None
    w = None
    try:
        print("Activating WiFi...")
        w = wifi_connect()
        try:
            ntptime.settime()   # RTC in UTC; local time via oslo_offset()
        except Exception as e:
            print("NTP failed:", e)

        pre = getattr(secrets, "PRE_TRIGGER_URL", "")
        if pre:   # only for the Pi server
            print("Triggering server render...")
            urequests.post(pre, timeout=HTTP_TIMEOUT).close()
            time.sleep(5)

        print("Downloading image...")
        url = secrets.CALENDAR_URL
        try:
            path, status = download(url)
        except Exception as e:
            if "fresh=1" not in url:
                raise
            # Fresh render failed: fall back to the last image AWS has.
            print("Fresh download failed:", e, "- fetching cached image")
            cached = url.replace("&fresh=1", "").replace("fresh=1&", "").replace("?fresh=1", "")
            path, status = download(cached)
            status = "stale"
        stale = status == "stale"
        print("Got", path, status)
    except Exception as e:
        error = e
        print("Update error:", e)
    finally:
        if w is not None:
            w.active(False)

    if path is None:
        path = last_image()   # show the last good calendar with an error note
    try:
        g.set_pen(WHITE)
        g.clear()
        if path:
            draw_image(path)
        elif error is None:
            error = "Ingen bilde"
        draw_status(error=error, stale=stale)
        refresh()
        print("Done!")
    except Exception as e:
        print("Display error:", e)
        inky_frame.led_busy.off()


def main():
    print("Wakeup. 10s delay. Hold A to skip.")
    btn_a = machine.Pin(BUTTON_A_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
    for _ in range(100):
        if btn_a.value() == 0:
            print("Button A detected!")
            break
        time.sleep(0.1)

    do_update()

    m = get_sleep_mins()
    print("Next update in {} minutes.".format(m))
    gc.collect()
    inky_frame.sleep_for(m)
    # On battery the frame powers off above and never gets here. On USB power
    # sleep_for only waits, so do a full hardware reset: reading the battery
    # (ADC on GPIO29, shared with the WiFi chip) leaves WiFi unusable until a
    # hard reset, and a fresh boot runs main.py again cleanly.
    machine.reset()


if __name__ == "__main__":
    main()
