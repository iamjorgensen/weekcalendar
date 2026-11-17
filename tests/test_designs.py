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


def test_titles_are_tidied_after_tag_mapping():
    from designs.adapter import _clean_title
    assert _clean_title({"display_text": ": Slutt 13:20"}) == "Slutt 13:20"
    assert _clean_title({"display_text": "Turdag –"}) == "Turdag"
    assert _clean_title({"display_text": "Fridag: 1. juledag"}) == "1. juledag"
    assert _clean_title({"display_text": "Kl. 18:00"}) == "Kl. 18:00"


def test_time_not_repeated_when_in_title():
    d = NOW.date().isoformat()
    data = {"events": [dict(date=d, time="13:40", name="Slutt 13:40", display_text="Slutt 13:40"),
                       dict(date=d, time="09:00", name="Gym", display_text="Gym"),
                       dict(date=d, time="", name="Juleboden", display_text="Juleboden")]}
    evs = to_design_data(data, days=1, now=NOW)["days"][0]["events"]
    assert [(e["time"], e["title"]) for e in evs] == [("", "Juleboden"), ("09:00", "Gym"), ("", "Slutt 13:40")]


def test_dense_options_render_and_collapse_label(monkeypatch):
    from designs import dense
    data = _data()
    d0 = NOW.date()
    for i in range(4):   # same all-day event four days in a row
        data["events"].append(dict(date=(d0 + timedelta(days=i)).isoformat(), time="", name="Juleboden",
                                   display_text="Juleboden"))
    dd = to_design_data(data, days=7, now=NOW)
    collapsed = dense.collapse_repeats(dd["days"])
    titles0 = [e["title"] for e in collapsed[0]["events"]]
    assert "Juleboden (tir–fre)" in titles0
    assert all(e["title"] != "Juleboden" for day in collapsed[1:4] for e in day["events"])
    monkeypatch.setenv("DESIGN_OPTIONS", "collapse+month+tomorrow")
    img = dense.render(dd)
    assert img.size == (800, 480)


def test_clothing_advice_rules():
    from designs.adapter import clothing_advice
    assert clothing_advice(None, 0, []) == ""
    assert clothing_advice(-10, 0, ["clearsky_day"]) == "Klær: Vinterdress, ull, lue og votter"
    assert clothing_advice(-3, 0, ["cloudy"]) == "Klær: Vinterdress, lue og votter"
    assert clothing_advice(-1, 1.0, ["snow"]).startswith("Klær: Vinterdress + vintersko")
    assert "Glatt?" in clothing_advice(1, 0.8, ["lightrain"])            # rain around zero
    assert clothing_advice(3, 0, ["cloudy"]) == "Klær: Boblejakke, lue og votter"
    assert clothing_advice(8, 1.2, ["rain"]) == "Klær: Regntøy og støvler"
    assert clothing_advice(18, 0, ["clearsky_day"]) == "Klær: T-skjorte og shorts?"


def test_adapter_today_and_tomorrow_get_periods_and_advice():
    data = _data()
    tomorrow = NOW.date() + timedelta(days=1)
    data["hourly_today"] += [dict(time=datetime(tomorrow.year, tomorrow.month, tomorrow.day, h, tzinfo=OSLO).isoformat(),
                                  temp=-6.0, symbol="clearsky_day") for h in range(6, 23)]
    dd = to_design_data(data, days=7, now=NOW)
    w0, w1 = dd["days"][0]["weather"], dd["days"][1]["weather"]
    assert w0["periods"] and w1["periods"] and w1["periods"][0][2] == -6
    assert w1["morning"] == -6 and w1["advice"] == "Klær: Vinterdress + vintersko"   # daily symbol is "Snø"
    assert w0["advice"].startswith("Klær: ")


def test_evening_mode_shows_tomorrow(monkeypatch):
    from designs import dense
    import designs.common as common
    evening = datetime(2026, 11, 17, 18, 5, tzinfo=OSLO)
    dd = to_design_data(_data(), days=7, now=evening)
    seen = []
    real = dense._today
    monkeypatch.setattr(dense, "_today", lambda img, draw, day, *a, **k: (seen.append(day), real(img, draw, day, *a, **k))[1])
    dense.render(dd, {"evening": True, "advice": True})
    assert seen[-1]["date"] == evening.date() + timedelta(days=1) and seen[-1]["heading"] == "I morgen"
    seen.clear()
    dense.render(dd, {"evening": False})
    assert seen[-1]["date"] == evening.date() and "advice" not in (seen[-1]["weather"] or {})


def test_tomorrow_block_only_when_all_events_fit(monkeypatch):
    from designs import dense
    dd = to_design_data(_data(), days=7, now=NOW)
    dd["days"][1]["events"] = [{"time": f"{8 + i:02d}:00", "sort_time": f"{8 + i:02d}:00", "title": f"Ting {i}",
                                "icon": None, "people": [], "is_holiday": False} for i in range(12)]
    shown = []
    monkeypatch.setattr(dense, "_day_section",
                        lambda img, draw, x, y, w, day, measure=False, morning=False: (shown.append(day["date"]), 40)[1])
    dense.render(dd, {"tomorrow": True})
    assert dd["days"][1]["date"] in shown   # too many to fit -> tomorrow stays in the day list


def test_evening_mode_keeps_tonight(monkeypatch):
    from designs import dense
    evening = datetime(2026, 11, 17, 18, 5, tzinfo=OSLO)
    data = _data()
    data["events"].append(dict(date=evening.date().isoformat(), time="20:45", name="Danmark – Norge Christian",
                               display_text="Danmark – Norge", tags=[{"text": "Christian", "color_rgb": (0, 0, 0)}]))
    dd = to_design_data(data, days=7, now=evening)
    sections = []
    monkeypatch.setattr(dense, "_day_section",
                        lambda img, draw, x, y, w, day, measure=False, morning=False: (sections.append(day), 40)[1])
    dense.render(dd, {"evening": True})
    first = sections[0]
    assert first.get("label") == "I kveld" and [e["title"] for e in first["events"]] == ["Danmark – Norge"]


def test_private_icon_from_calendar_event():
    import data_provider
    assert data_provider._private_icon({"extendedProperties": {"private": {"icon": "soccer"}}}) == "soccer"
    assert data_provider._private_icon({}) is None


@pytest.mark.parametrize("opt", ["month_right", "month_column"])
def test_month_on_white_side(opt):
    from designs import dense
    dd = to_design_data(_data(), days=14, now=NOW)
    img = dense.render(dd, {opt: True, "month": True, "collapse": True})
    assert img.size == (800, 480) and len(img.getcolors(1 << 24)) <= 6


def test_month_column_with_husk_upcoming_weather():
    from designs import dense
    data = _data()
    d0 = NOW.date().isoformat()
    data["events"] += [dict(date=d0, time="", name="Husk denne uka: skiftetøy og innesko", display_text="Husk denne uka: skiftetøy og innesko",
                            tags=[{"text": "Amalie", "color_rgb": (255, 255, 0)}])]
    dd = to_design_data(data, days=14, now=NOW)
    for opts in ({"husk": True}, {"upcoming": True}, {"weather5": True}, {"husk": True, "upcoming": True, "weather5": True}):
        img = dense.render(dd, dict(opts, month_column=True, collapse=True))
        assert img.size == (800, 480) and len(img.getcolors(1 << 24)) <= 6
    assert dense.HUSK_RE.search("Turdag – husk vedkubbe") and dense.HUSK_RE.search("Ta med gamle klær")
    assert not dense.HUSK_RE.search("Huskestue")
