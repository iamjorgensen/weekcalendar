"""
Render the README mockups from made-up data (a fictional family), with the real
design code. Run from the repo root:

    python docs/mockups/make_mockups.py

Writes docs/images/frame-*.png (the raw 800x480 image inside a drawn frame).
"""
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from designs import dense  # noqa: E402
from designs.adapter import to_design_data  # noqa: E402

OUT = os.path.join(ROOT, "docs", "images")
OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 11, 17, 6, 47, tzinfo=OSLO)   # a Tuesday morning

# The family (made up). Colours are the tag colours chosen on the admin page.
NORA = {"text": "Nora", "color_name": "yellow"}
EMIL = {"text": "Emil", "color_name": "green"}
OSKAR = {"text": "Oskar", "color_name": "blue"}
KARI = {"text": "Kari", "color_name": "red"}
LARS = {"text": "Lars", "color_name": "black"}


def d(i):
    return (NOW.date() + timedelta(days=i)).isoformat()


def ev(i, t, name, icon=None, tags=(), holiday=False):
    return dict(date=d(i), time=t, name=name, display_text=name, original_name=name, icon=icon,
                tags=list(tags), is_holiday=holiday)


EVENTS = [ev(i, "", "Juleverksted", "gift", [NORA]) for i in range(0, 4)] + [
    ev(0, "", "Turdag: husk sitteunderlag og varm drikke", "school", [EMIL]),
    ev(0, "09:00", "Gym – gruppe Sild", "gymnastics", [NORA]),
    ev(0, "12:00", "Tannlege", None, [KARI]),
    ev(0, "17:30", "Korpsøvelse", "music", [NORA]),
    ev(1, "", "Restavfall", "trash-2"),
    ev(1, "13:20", "Skoleslutt 13:20", None, [EMIL]),
    ev(1, "17:00", "Svømming", "droplet", [OSKAR]),
    ev(2, "", "Papir og plast", "trash-2"),
    ev(2, "18:00", "Foreldremøte 4A", None, [EMIL]),
    ev(2, "19:45", "Håndballtrening G12", "volleyball", [OSKAR]),
    ev(3, "", "Planleggingsdag", "umbrella_beach", [NORA, EMIL], holiday=True),
    ev(3, "20:45", "Norge – Italia", "soccer", [LARS]),
    ev(4, "11:00", "Håndballkamp mot Sprint", "volleyball", [OSKAR]),
    ev(4, "15:00", "Bursdag Ida (8 år)", "cake", [EMIL]),
    ev(5, "12:00", "Skøyteskole", "skate", [NORA]),
    ev(6, "08:30", "Gym", "gymnastics", [EMIL]),
    ev(6, "17:00", "Svømming", "droplet", [OSKAR]),
    ev(7, "", "Kari 40 år", "cake", [KARI]),
    ev(8, "", "Restavfall", "trash-2"),
    ev(8, "18:00", "Korpsøvelse", "music", [NORA]),
    ev(9, "19:45", "Håndballtrening G12", "volleyball", [OSKAR]),
    ev(10, "18:00", "Juleavslutning SFO", "star", [EMIL]),
    ev(12, "11:00", "Skøyteskole", "skate", [NORA]),
    ev(13, "17:00", "Svømming", "droplet", [OSKAR]),
]

COND = ["Skyet", "Lett snø", "Delvis skyet", "Klart", "Delvis skyet", "Skyet", "Regn", "Skyet", "Snø",
        "Skyet", "Regn", "Klart", "Skyet", "Delvis skyet"]
TMAX = [2, 0, 1, 3, 2, 3, 5, 0, -1, 2, 4, 1, 0, 1]
TMIN = [-1, -3, -2, -3, -2, -1, 1, -3, -4, -1, 1, -2, -3, -2]
WEATHER = [dict(date=d(i), condition=COND[i], temp_max=TMAX[i], temp_min=TMIN[i],
                precip=[0, 2, 0, 0, 0, 0, 6, 0, 3, 0, 6, 0, 0, 0][i], wind_max=5, wind_dir_deg=0)
           for i in range(14)]


def hourly():
    out = []
    for day_off, temps, sym in ((0, (-1, 1, 2, 0), "cloudy"), (1, (-3, -1, 0, -2), "lightsnow")):
        day = NOW.date() + timedelta(days=day_off)
        for h in range(6, 23):
            t = temps[0] if h <= 10 else temps[1] if h <= 13 else temps[2] if h <= 16 else temps[3]
            out.append(dict(time=datetime(day.year, day.month, day.day, h, tzinfo=OSLO).isoformat(), temp=t,
                            symbol=sym, precip_next_1h=0.4 if day_off == 1 and 7 <= h <= 9 else 0.0))
    return out


PEOPLE = [{"name": "Nora", "letter": "N", "color": "YELLOW", "kind": "barn", "birthday": "2016-11-20"},
          {"name": "Emil", "letter": "E", "color": "GREEN", "kind": "barn", "birthday": "2018-05-02"},
          {"name": "Oskar", "letter": "O", "color": "BLUE", "kind": "barn", "birthday": "2014-03-09"},
          {"name": "Kari", "letter": "K", "color": "RED", "kind": "voksen", "birthday": "1986-11-24"},
          {"name": "Lars", "letter": "L", "color": "BLACK", "kind": "voksen", "birthday": "1984-11-17"},
          {"name": "Bamse", "letter": "B", "color": "BLUE", "kind": "dyr", "birthday": "2022-12-01"}]

OPTS = {"collapse": True, "tomorrow": True, "evening": True, "advice": True, "month_column": True,
        "upcoming": True}


def render(now, opts=OPTS, people=None):
    shift = now.date() - NOW.date()      # move the sample week to `now`
    move = lambda x: dict(x, date=(NOW.date() + timedelta(days=(datetime.fromisoformat(x["date"]).date()
                                                                - NOW.date()).days) + shift).isoformat())
    data = to_design_data({"events": [move(e) for e in EVENTS], "weather": [move(w) for w in WEATHER],
                           "hourly_today": hourly() if not shift else [], "battery": 87, "people": people or []},
                          days=14, now=now)
    return dense.render(data, opts)


def moments_sheet():
    """Birthday and holiday banners side by side."""
    from PIL import ImageFont
    opts = dict(OPTS, moments=True)
    shots = [render(NOW, opts, PEOPLE),                                          # Lars: black and gold
             render(datetime(2026, 12, 1, 7, 0, tzinfo=OSLO), opts, PEOPLE),     # the dog
             render(datetime(2026, 12, 6, 7, 0, tzinfo=OSLO), opts, PEOPLE),     # 2nd Sunday of Advent
             render(datetime(2026, 12, 24, 7, 0, tzinfo=OSLO), opts, PEOPLE)]    # Christmas Eve
    panels = [im.crop((0, 0, dense.HERO_W, 480)) for im in shots]
    sheet = Image.new("RGB", (len(panels) * (dense.HERO_W + 12) + 12, 504), (255, 255, 255))
    for k, p in enumerate(panels):
        sheet.paste(p, (12 + k * (dense.HERO_W + 12), 12))
    return sheet


def in_frame(img, pad=34):
    """The 800x480 image on a white mat inside a dark frame, with a soft shadow."""
    w, h = img.size
    fw, fh = w + 2 * pad + 28, h + 2 * pad + 28
    canvas = Image.new("RGB", (fw + 60, fh + 60), (255, 255, 255))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([34, 40, 34 + fw, 40 + fh], 18, fill=(0, 0, 0, 90))
    canvas.paste(shadow.filter(ImageFilter.GaussianBlur(14)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(14)))
    dr = ImageDraw.Draw(canvas)
    dr.rounded_rectangle([30, 30, 30 + fw, 30 + fh], 18, fill=(38, 38, 40))
    dr.rectangle([44, 44, 44 + w + 2 * pad, 44 + h + 2 * pad], fill=(246, 245, 240))
    canvas.paste(img, (44 + pad, 44 + pad))
    return canvas


def main():
    os.makedirs(OUT, exist_ok=True)
    shots = {
        "frame-morning": render(NOW),
        "frame-evening": render(NOW.replace(hour=18, minute=5)),
        "frame-month-right": render(NOW, {"collapse": True, "tomorrow": True, "advice": True, "month": True}),
    }
    moments_sheet().save(os.path.join(OUT, "moments.png"))
    print("wrote moments")
    for name, img in shots.items():
        img.save(os.path.join(OUT, f"{name}-raw.png"))
        in_frame(img).save(os.path.join(OUT, f"{name}.png"))
        print("wrote", name)


if __name__ == "__main__":
    main()
