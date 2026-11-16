"""
Deterministic sample week used to compare designs.

Shape (what a design receives):
  {
    "today": date,
    "days": [ { "date": date, "events": [ev...], "weather": {...} or None }, ... ],
    "updated": "04:00",
  }
  ev = { "time": "HH:MM" or "", "title": str, "icon": str|None,
         "people": [(letter, rgb)], "is_holiday": bool }
"""
from datetime import date, timedelta

from designs.common import BLUE, GREEN, RED, YELLOW, BLACK

A = ("A", YELLOW)   # Amalie
S = ("S", GREEN)    # Sigrid
P = ("P", BLUE)     # Peter
I = ("I", RED)      # Ingun
C = ("C", BLACK)    # Christian

START = date(2026, 12, 21)  # Monday, covers Christmas: shows red days


def _d(i):
    return START + timedelta(days=i)


def sample_week(n_days=10):
    ev = {
        0: [
            dict(time="07:45", title="Levere bil på verksted", icon="truck", people=[C]),
            dict(time="", title="Restavfall", icon="trash", people=[]),
            dict(time="16:30", title="Fotballtrening", icon="soccer", people=[P]),
            dict(time="17:30", title="Istrening", icon="skate", people=[A]),
            dict(time="18:00", title="Middag: Taco", icon="food", people=[]),
        ],
        1: [
            dict(time="08:30", title="Tannlege", icon=None, people=[S, I]),
            dict(time="19:00", title="Juleavslutning korps i gymsalen på skolen", icon="music", people=[A, S]),
        ],
        2: [
            dict(time="", title="Siste skoledag før jul", icon="school", people=[A, S, P]),
            dict(time="12:00", title="Lunsj med jobben", icon="coffee", people=[C]),
            dict(time="", title="Papir og plast", icon="trash", people=[]),
        ],
        3: [
            dict(time="", title="Julaften", icon="gift", people=[]),
            dict(time="15:00", title="Gudstjeneste", icon=None, people=[]),
            dict(time="17:00", title="Middag hos mormor og morfar", icon="home", people=[]),
        ],
        4: [dict(time="", title="1. juledag", icon="star", people=[], is_holiday=True)],
        5: [
            dict(time="", title="2. juledag", icon="star", people=[], is_holiday=True),
            dict(time="13:00", title="Juleselskap", icon="users", people=[]),
        ],
        6: [dict(time="11:00", title="Aking i bakken", icon="sledding", people=[A, S, P])],
        7: [dict(time="", title="Ingun 45 år", icon="cake", people=[I])],
        8: [],
        9: [dict(time="10:00", title="Kino", icon="film", people=[A, S])],
    }
    weather = [
        ("Snø", -2, -7, 4.2, 5.1), ("Klart", -4, -11, 0.0, 2.3), ("Delvis skyet", -1, -6, 0.3, 3.0),
        ("Snø", 0, -3, 6.8, 7.4), ("Klart", -6, -12, 0.0, 1.8), ("Skyet", -3, -8, 0.0, 2.9),
        ("Klart", -5, -10, 0.0, 1.5), ("Regn", 2, -1, 3.1, 8.2), ("Skyet", 1, -2, 0.4, 4.0),
        ("Snø", -1, -4, 2.2, 3.3),
    ]
    days = []
    for i in range(n_days):
        events = [dict(is_holiday=False, **e) if "is_holiday" not in e else dict(e) for e in ev.get(i, [])]
        w = weather[i]
        days.append({
            "date": _d(i),
            "events": events,
            "weather": {"symbol": w[0], "tmax": w[1], "tmin": w[2], "precip": w[3], "wind": w[4]},
        })
    # Extra detail for today (weather_provider already has hourly data to derive this)
    days[0]["weather"].update({
        "periods": [("Morgen", "cloud-snow", -6), ("Dag", "cloud-snow", -2), ("Kveld", "cloud", -4)],
        "wind_dir": "NV",
        "sunrise": "09:17",
        "sunset": "15:13",
    })
    return {"today": START, "days": days, "updated": "04:00"}
