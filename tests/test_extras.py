"""Spond answers, rota, ⏳ countdowns, yearly dates, name days, first snow, moon/aurora, watchdog, preview."""
import json
import os
import sys
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "aws_lambda"))

import config_store  # noqa: E402
import extras  # noqa: E402
import spond_client  # noqa: E402
import watchdog_handler  # noqa: E402
from designs import dense, moments  # noqa: E402
from designs.common import RED, YELLOW  # noqa: E402
from test_moments import day  # noqa: E402
from test_aws_handlers import aws  # noqa: E402,F401  (fixture)

PEOPLE = [{"name": "Nora", "letter": "N", "color": "YELLOW", "birthday": "", "nameday": "11-19"},
          {"name": "Emil", "letter": "E", "color": "GREEN", "birthday": "", "nameday": "03-14"}]


def test_spond_unanswered():
    now = datetime(2026, 11, 17, 6, tzinfo=timezone.utc)
    evs = [{"heading": "Kamp mot Sprint", "startTimestamp": "2026-11-21T10:00:00Z",
            "responses": {"unansweredIds": ["M1"], "acceptedIds": []}},
           {"heading": "Trening", "startTimestamp": "2026-11-19T16:00:00Z", "responses": {"acceptedIds": ["M1"]}},
           {"heading": "Avlyst", "cancelled": True, "startTimestamp": "2026-11-20T16:00:00Z",
            "responses": {"unansweredIds": ["M1"]}},
           {"heading": "Langt fram", "startTimestamp": "2027-01-20T16:00:00Z", "responses": {"unansweredIds": ["M1"]}}]
    out = spond_client.unanswered(evs, {"M1": "Oskar", "M9": "Lars"}, now=now)
    assert out == [{"start": "2026-11-21T10:00:00+00:00", "title": "Kamp mot Sprint", "who": ["Oskar"]}]
    line = moments.lines([day(date(2026, 11, 17))], [], now=datetime(2026, 11, 17, 6), spond_pending=out)
    assert line[0] == "Svar på Spond: Kamp mot Sprint lør 11:00 (Oskar)"


def test_rota_rotates_weekly_and_validates():
    cfg = config_store.validate({"people": [{"name": "Nora", "color": "YELLOW"}, {"name": "Emil"}],
                                 "chores": [{"task": "Oppvask", "people": ["Nora", "Emil"]}]})
    w47 = config_store.chores_for_week(cfg, date(2026, 11, 17))     # ISO week 47
    w48 = config_store.chores_for_week(cfg, date(2026, 11, 24))
    assert w47[0]["name"] != w48[0]["name"] and {w47[0]["name"], w48[0]["name"]} == {"Nora", "Emil"}
    import pytest
    with pytest.raises(config_store.ConfigError):
        config_store.validate({"people": [{"name": "Nora"}], "chores": [{"task": "X", "people": ["Ola"]}]})


def test_yearly_dates_and_namedays():
    dates = [{"name": "Bryllupsdag", "date": "2012-06-16", "color": "RED", "icon": "heart"}]
    b = moments.banner(day(date(2026, 6, 16)), PEOPLE, dates=dates)
    assert b["title"] == "Bryllupsdag!" and b["big"] == "14" and b["bg"] == RED
    assert moments.lines([day(date(2026, 6, 13))], [], now=datetime(2026, 6, 13, 7), dates=dates) == \
        ["3 dager til bryllupsdag"]
    nd = moments.banner(day(date(2026, 11, 19)), PEOPLE)
    assert nd["title"] == "Gratulerer, Nora!" and nd["big"] == "Navnedag" and nd["bg"] == YELLOW
    assert "Navnedag i morgen: Nora" in moments.lines([day(date(2026, 11, 18))], PEOPLE, now=datetime(2026, 11, 18, 7))
    cfg = config_store.validate({"people": [{"name": "Nora", "nameday": "11-19"}],
                                 "dates": [{"name": "Bamse kom", "date": "2022-08-01", "icon": "dog"}]})
    assert cfg["people"][0]["nameday"] == "11-19" and cfg["dates"][0]["color"] == "RED"


def test_countdowns_from_calendar(monkeypatch):
    items = {"items": [{"summary": "⏳ Syden", "start": {"date": "2027-01-20"}},
                       {"summary": "Uten markør", "start": {"date": "2027-01-21"}}]}
    seen = {}
    monkeypatch.setattr(extras, "_get_json", lambda url, timeout=8: (seen.setdefault("url", url), items)[1])
    out = extras.countdowns("key", "cal@group", date(2026, 11, 17))
    assert out == [{"date": "2027-01-20", "title": "Syden"}] and "q=%E2%8F%B3" in seen["url"]
    assert moments.lines([day(date(2026, 11, 17))], [], now=datetime(2026, 11, 17, 7), countdowns=out) == \
        ["64 dager til Syden"]


class S3:
    def __init__(self):
        self.d = {}

    def get_object(self, Bucket, Key):
        import io
        if Key not in self.d:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.d[Key])}

    def put_object(self, Bucket, Key, Body, **kw):
        self.d[Key] = Body


def test_first_snow_once_per_season():
    s3 = S3()
    assert not extras.first_snow(s3, "b", date(2026, 11, 10), "Skyet")
    assert extras.first_snow(s3, "b", date(2026, 11, 17), "Lett snø")
    assert extras.first_snow(s3, "b", date(2026, 11, 17), "Lett snø")      # the whole day
    assert not extras.first_snow(s3, "b", date(2026, 11, 20), "Snø")      # not again this season
    assert extras.first_snow(s3, "b", date(2027, 10, 30), "Snø")          # next season
    b = moments.banner(day(date(2026, 11, 17)), [], first_snow=True)
    assert b["title"] == "Første snø!"


def test_moon_and_aurora():
    assert moments.full_moon_tonight(date(2026, 11, 24))       # full moon 24 Nov 2026
    assert not moments.full_moon_tonight(date(2026, 11, 17))
    rows = [["time_tag", "kp", "observed", "noaa_scale"], ["2026-11-17 18:00:00", "5.33", "predicted", "G1"],
            ["2026-11-18 12:00:00", "7.00", "predicted", "G3"]]
    start = datetime(2026, 11, 17, 17, tzinfo=timezone.utc)
    from datetime import timedelta
    assert extras.parse_kp(rows, start, start + timedelta(hours=9)) == 5.33
    assert extras.parse_kp([{"time_tag": "2026-11-17T21:00:00", "kp": 3}], start, start + timedelta(hours=9)) == 3
    assert any("Nordlys" in x for x in moments.lines([day(date(2026, 11, 17))], [], now=datetime(2026, 11, 17, 7),
                                                     aurora_kp=5.3))


def test_watchdog_alerts_once():
    now = 2_000_000_000
    alerts, state = watchdog_handler.check({"at": now - 30 * 3600, "battery": 12}, {}, now)
    assert len(alerts) == 2 and "batteri" in alerts[1][0].lower()
    again, state2 = watchdog_handler.check({"at": now - 30 * 3600, "battery": 12}, state, now + 3600)
    assert again == []
    fine, _ = watchdog_handler.check({"at": now - 3600, "battery": 80}, {}, now)
    assert fine == []


def test_low_battery_text_on_frame():
    d = date(2026, 11, 17)
    data = {"today": d, "now": datetime(2026, 11, 17, 7), "updated": "07:00", "battery": 9,
            "days": [day(d)] + [day(date(2026, 11, 17 + i)) for i in range(1, 5)]}
    img = dense.render(data, {})
    assert YELLOW in [img.getpixel((x, 470)) for x in range(84, 160)]    # "Bytt batteri!"


def test_render_handler_preview_returns_png(monkeypatch):
    import render_handler
    monkeypatch.setattr(render_handler, "_oslo_today", lambda: date(2026, 11, 17))
    assert "error" in render_handler.handler({"action": "preview", "date": "2020-01-01"}, None)
    assert "error" in render_handler.handler({"action": "preview", "date": "nope"}, None)


def test_countdown_tags_people():
    people = [{"name": "Christian", "letter": "C", "color": "BLACK", "words": ["christian", "c:"]},
              {"name": "Nora", "letter": "N", "color": "YELLOW", "words": ["nora"]}]
    title, chips = moments.tag_people("Syden Christian", people)
    assert title == "Syden" and chips == [("C", (0, 0, 0))]
    out = moments.lines([day(date(2026, 11, 17))], people, now=datetime(2026, 11, 17, 7),
                        countdowns=[{"date": "2026-11-29", "title": "Syden Christian"},
                                    {"date": "2027-01-01", "title": "Senere"}])
    assert out == ["12 dager til Syden"] and out[0].chips == [("C", (0, 0, 0))]
    assert moments.tag_people("Christiania-turen", people) == ("Christiania-turen", [])   # whole words only
    d = date(2026, 11, 17)
    img = dense.render({"today": d, "now": datetime(2026, 11, 17, 7), "updated": "07:00", "battery": 80,
                        "people": people, "countdowns": [{"date": "2026-11-29", "title": "Syden Christian"}],
                        "days": [day(d)] + [day(date(2026, 11, 17 + i)) for i in range(1, 5)]}, {"moments": True})
    assert img.size == (800, 480)


def _tibber_data(today):
    from datetime import timedelta
    nodes = []
    for i in range(1, 400):
        d = today - timedelta(days=i)
        nodes.append({"from": f"{d.isoformat()}T00:00:00.000+01:00", "consumption": 40.0 if i <= 30 else 50.0})
    return {"viewer": {"homes": [{"id": "h1", "appNickname": "Hjemme", "consumption": {"nodes": nodes}}]}}


def test_tibber_summary_this_year_vs_last():
    import tibber
    today = date(2026, 11, 17)
    s = tibber.summary(tibber.daily(_tibber_data(today)), today)
    assert s["kwh"] == 1200 and s["kwh_last_year"] == 1500 and s["pct"] == -20
    assert len(s["days"]) == 30 and s["days"][-1] == 40.0
    short = {d: v for d, v in tibber.daily(_tibber_data(today)).items() if d > date(2026, 1, 1)}
    assert tibber.summary(short, today)["pct"] is None          # no data a year back


def test_energy_block_in_evening_and_car_in_corner():
    import tibber
    from designs.common import BLUE, WHITE
    today = date(2026, 11, 17)
    energy = tibber.summary(tibber.daily(_tibber_data(today)), today)
    base = {"today": today, "updated": "18:05", "battery": 80, "energy": energy,
            "car": {"pct": 64, "note": "Lader nå"},
            "days": [day(date(2026, 11, 17 + i)) for i in range(0, 6)]}
    opts = {"month_column": True, "upcoming": True, "evening": True}
    eve = dense.render(dict(base, now=datetime(2026, 11, 17, 18, 5)), opts)
    morning = dense.render(dict(base, now=datetime(2026, 11, 17, 7, 0)), opts)
    count = lambda im: sum(1 for x in range(551, 795) for y in range(300, 476) if im.getpixel((x, y)) == BLUE)
    assert count(eve) > 200 and count(morning) == 0          # bars only in the evening view
    assert YELLOW in [eve.getpixel((x, 466)) for x in range(86, 104)]   # ⚡ next to the frame battery


def test_tibber_admin_test_endpoint(aws, monkeypatch):
    import tibber
    from test_admin import ADMIN, _api
    from test_aws_handlers import _put_params
    _s3, ssm = aws
    _put_params(ssm, {"ADMIN_TOKEN": ADMIN})
    assert _api("/api/tibber/test", method="POST")["statusCode"] == 400
    _put_params(ssm, {"TIBBER_TOKEN": "t"})
    today = date.today()
    monkeypatch.setattr(tibber, "query", lambda token, q, timeout=10: _tibber_data(today) if "consumption" in q
                        else {"__schema": {"types": [{"name": "Home"}, {"name": "ElectricVehicle"}]}})
    r = _api("/api/tibber/test", method="POST")
    body = json.loads(r["body"])
    assert r["statusCode"] == 200 and body["homes"] == ["Hjemme"] and body["vehicle_types"] == ["ElectricVehicle"]
    assert body["summary"]["kwh"] == 1200
