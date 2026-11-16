"""Design rendering from data_provider-shaped data (no network)."""
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from designs import render_design  # noqa: E402
from designs.adapter import deg_to_cardinal, people_from_tags, periods_from_hourly, sun_times, to_design_data  # noqa: E402
from designs.common import weather_icon_name  # noqa: E402

OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 11, 17, 4, 0, tzinfo=OSLO)


def _data():
    d = lambda i: (NOW.date() + timedelta(days=i)).isoformat()
    events = [
        dict(date=d(0), time="16:30", name="Fotball", display_text="Fotball", icon="soccer",
             tags=[{"text": "Peter", "color_rgb": (0, 0, 255)}, {"text": "middag"}]),
        dict(date=d(0), time="", name="Restavfall", display_text="Restavfall", icon="trash-2", tags=[]),
        dict(date=d(2), time="", name="Fridag: 1. juledag", original_name="Fridag: 1. juledag", is_holiday=True, tags=[]),
        dict(date="not-a-date", time="", name="ignored"),
    ]
    weather = [dict(date=d(i), condition="Snø", temp_max=-1, temp_min=-5, precip=2, wind_max=4, wind_dir_deg=315)
               for i in range(7)]
    hourly = [dict(time=datetime(2026, 11, 17, h, tzinfo=OSLO).isoformat(), temp=-3 + h / 10,
                   symbol="snow" if h < 12 else "cloudy") for h in range(5, 23)]
    return {"events": events, "weather": weather, "hourly_today": hourly}


def test_adapter_shapes_real_data():
    out = to_design_data(_data(), days=7, now=NOW)
    assert out["today"] == NOW.date() and len(out["days"]) == 7
    d0 = out["days"][0]
    assert [e["title"] for e in d0["events"]] == ["Restavfall", "Fotball"]  # all-day first
    assert d0["events"][1]["people"] == [("P", (0, 0, 255))]  # lowercase 'middag' tag ignored
    assert out["days"][2]["events"][0]["title"] == "1. juledag" and out["days"][2]["events"][0]["is_holiday"]
    w = d0["weather"]
    assert w["wind_dir"] == "NV" and [p[0] for p in w["periods"]] == ["Morgen", "Dag", "Kveld"]
    assert w["periods"][0][1] == "snow" and w["sunrise"] < w["sunset"]


@pytest.mark.parametrize("name", ["hero", "dense", "agenda", "band"])
def test_every_design_renders_real_and_empty_data(name):
    for data in (_data(), {}, {"events": [], "weather": [], "hourly_today": []}):
        img = render_design(name, data, 7, now=NOW)
        assert img.size == (800, 480)
        assert len(img.getcolors(1 << 24)) <= 6  # only panel colours


def test_evening_render_has_no_past_periods():
    late = datetime(2026, 11, 17, 23, 30, tzinfo=OSLO)
    data = _data()
    data["hourly_today"] = []  # MET only returns future hours
    img = render_design("hero", data, 7, now=late)
    assert img.size == (800, 480)


def test_helpers():
    assert people_from_tags([{"text": "Amalie", "color_name": "YELLOW"}, {"text": "Anne"}]) == [("A", (255, 255, 0))]
    assert deg_to_cardinal(0) == "N" and deg_to_cardinal(225) == "SV" and deg_to_cardinal(None) == ""
    rise, sset = sun_times(date(2026, 6, 21), 59.44, 10.64)
    assert rise.startswith("03:") or rise.startswith("04:")  # midsummer in Moss
    assert sun_times(date(2026, 12, 21), 78.2, 15.6) == (None, None)  # polar night, Svalbard
    assert weather_icon_name("lightrainshowers_day") == "cloud-rain" and weather_icon_name("Klart") == "sun"
    assert periods_from_hourly([], NOW.date()) == []


def test_main_uses_design_and_falls_back_to_legacy(monkeypatch):
    os.chdir(ROOT)
    import main
    img = main._try_render_calendar(_data(), {"design": "hero"}, 800, 480, 7)
    assert img.size == (800, 480)

    import designs
    def broken(*a, **k):
        raise RuntimeError("design bug")
    monkeypatch.setattr(designs, "render_design", broken)
    img = main._try_render_calendar(_data(), dict(main.opts, design="hero"), 800, 480, 7)
    assert img.size == (800, 480)  # legacy layout_renderer still produced an image
