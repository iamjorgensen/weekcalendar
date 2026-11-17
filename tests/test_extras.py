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
    s2 = tibber.summary(short, today)                             # no data a year back: previous 30 days
    assert s2["against"] == "forrige 30 dager" and s2["pct"] == -20


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
    monkeypatch.setattr(tibber, "fetch_history", lambda token: _tibber_data(today))
    monkeypatch.setattr(tibber, "query", lambda token, q, timeout=10: _tibber_data(today) if "consumption" in q
                        else {"__schema": {"types": [{"name": "Home"}, {"name": "ElectricVehicle"}]}})
    r = _api("/api/tibber/test", method="POST")
    body = json.loads(r["body"])
    assert r["statusCode"] == 200 and body["homes"] == ["Hjemme"] and body["vehicle_types"] == ["ElectricVehicle"]
    assert body["summary"]["kwh"] == 1200


def test_tibber_pages_backwards(monkeypatch):
    import tibber
    from datetime import timedelta
    today = date(2026, 11, 17)
    full = _tibber_data(today)["viewer"]["homes"][0]["consumption"]["nodes"]
    full = sorted(full, key=lambda n: n["from"])
    calls = []

    def fake(token, q, timeout=10):
        calls.append(q)
        # 100 newest days per page; the cursor is the index of the first node returned
        end = int(q.split('before: "')[1].split('"')[0]) if "before:" in q else len(full)
        start = max(0, end - 100)
        return {"viewer": {"homes": [{"id": "h1", "appNickname": "Hjem", "consumption": {
            "pageInfo": {"startCursor": str(start), "hasPreviousPage": start > 0}, "nodes": full[start:end]}}]}}
    monkeypatch.setattr(tibber, "query", fake)
    s = tibber.summary(tibber.daily(tibber.fetch_history("t")), today)
    assert len(calls) == 4 and s["pct"] == -20      # 399 days in 4 pages: reached a year back


def test_tibber_falls_back_to_previous_30_days():
    import tibber
    from datetime import timedelta
    today = date(2026, 11, 17)
    per_day = {today - timedelta(days=i): (40.0 if i <= 30 else 50.0) for i in range(1, 61)}
    s = tibber.summary(per_day, today)
    assert s["pct"] == -20 and s["against"] == "forrige 30 dager" and s["kwh_last_year"] is None
    assert tibber.summary({k: v for k, v in per_day.items() if (today - k).days <= 31}, today)["pct"] is None


def test_tibber_history_cached_in_s3(monkeypatch):
    import tibber
    from datetime import timedelta
    today = date(2026, 11, 17)
    full = sorted(_tibber_data(today)["viewer"]["homes"][0]["consumption"]["nodes"], key=lambda n: n["from"])
    calls = []

    def fake(token, q, timeout=10):
        if "HOURLY" in q:          # hourly data for nettleie: covered by its own tests
            return {"viewer": {"homes": []}}
        calls.append(q)
        end = int(q.split('before: "')[1].split('"')[0]) if "before:" in q else len(full)
        start = max(0, end - 31)
        return {"viewer": {"homes": [{"id": "h1", "consumption": {
            "pageInfo": {"startCursor": str(start), "hasPreviousPage": start > 0}, "nodes": full[start:end]}}]}}
    monkeypatch.setattr(tibber, "query", fake)
    s3 = S3()
    first = tibber.energy("t", today, s3, "b")
    assert first["pct"] == -20 and first["against"] == "i fjor" and len(calls) == 13     # backfill once
    calls.clear()
    again = tibber.energy("t", today + timedelta(days=1), s3, "b")
    assert len(calls) == 1 and again["kwh"] > 0                                            # newest page only


def _with_cost(data, price=1.1):
    for n in data["viewer"]["homes"][0]["consumption"]["nodes"]:
        n["cost"] = n["consumption"] * price
    return data


def test_tibber_year_cost_and_estimate_with_norgespris():
    import tibber
    today = date(2026, 11, 17)
    data = _with_cost(_tibber_data(today))
    s = tibber.summary(tibber.daily(data), today, per_day_cost=tibber.daily_cost(data))
    # 1 Jan - 16 Nov: 290 days at 50 kWh + 30 at 40 kWh, Norgespris 0.50 kr/kWh (spot cost is ignored)
    assert s["year_cost"]["cost"] == round((290 * 50 + 30 * 40) * 0.5)
    # rest of the year (17 Nov - 31 Dec, 45 days): last year's 50 kWh/day
    assert s["year_cost"]["estimate"] == round(s["year_cost"]["cost"] + 45 * 50 * 0.5)
    assert tibber.summary(tibber.daily(data), today)["year_cost"]["cost"] == s["year_cost"]["cost"]
    short = {d: v for d, v in tibber.daily(data).items() if d > date(2026, 6, 1)}
    assert tibber.year_cost(short, {}, today) is None                     # history doesn't reach 1 Jan


def test_norgespris_cap_uses_spot_above_5000_kwh():
    import tibber
    assert tibber._month_cost(6000, 2026, 1.2) == 5000 * 0.5 + 1000 * 1.2
    assert tibber._month_cost(400, 2027, None) == 400 * 0.5               # unknown year: latest known price


def test_tibber_old_cache_without_cost_is_refetched(monkeypatch):
    import tibber
    today = date(2026, 11, 17)
    s3 = S3()
    s3.put_object(Bucket="b", Key=tibber.CACHE_KEY, Body=json.dumps(
        {"complete": True, "days": {"2026-11-16": 40.0}}).encode())
    fetched = []
    monkeypatch.setattr(tibber, "fetch_history",
                        lambda token, max_pages=tibber.MAX_PAGES: (fetched.append(max_pages), _with_cost(_tibber_data(today)))[1])
    out = tibber.energy("t", today, s3, "b")
    assert fetched == [tibber.MAX_PAGES] and out["year_cost"]["estimate"]
    assert json.loads(s3.get_object(Bucket="b", Key=tibber.CACHE_KEY)["Body"].read())["cost"]


def test_energy_block_shows_year_cost_when_there_is_room():
    import tibber
    today = date(2026, 11, 17)
    data = _with_cost(_tibber_data(today))
    energy = tibber.summary(tibber.daily(data), today, per_day_cost=tibber.daily_cost(data))
    base = {"today": today, "updated": "18:05", "battery": 80, "now": datetime(2026, 11, 17, 18, 5),
            "days": [day(date(2026, 11, 17 + i)) for i in range(0, 6)]}
    opts = {"month_column": True, "upcoming": True, "evening": True}
    dark = lambda im: sum(1 for x in range(551, 795) for y in range(370, 410) if im.getpixel((x, y)) == (0, 0, 0))
    with_cost = dense.render(dict(base, energy=energy), opts)
    without = dense.render(dict(base, energy=dict(energy, year_cost=None)), opts)
    assert dark(with_cost) > dark(without) + 200


# ------------------------------------------------------------------ nettleie (Elvia)
def _hour_nodes(first_day, days, kwh=lambda d, h: 1.0):
    from datetime import timedelta
    out = []
    for i in range(days):
        d = first_day + timedelta(days=i)
        for h in range(24):
            out.append({"from": f"{d.isoformat()}T{h:02d}:00:00.000+01:00", "consumption": kwh(d, h)})
    return out


def test_elvia_tariff_periods_and_steps():
    import nettleie
    assert nettleie.tariff(date(2026, 3, 1))[1:3] == (0.364, 0.264)
    assert nettleie.tariff(date(2026, 7, 1))[1:3] == (0.464, 0.314)
    assert nettleie.capacity_fee(4.0, date(2026, 2, 1)) == 190 and nettleie.capacity_fee(5.0, date(2026, 2, 1)) == 190
    assert nettleie.capacity_fee(7.5, date(2026, 8, 1)) == 420 and nettleie.capacity_fee(150, date(2026, 8, 1)) == 6800
    assert nettleie.is_day_hour(date(2026, 11, 17), 6) and not nettleie.is_day_hour(date(2026, 11, 17), 22)
    assert not nettleie.is_day_hour(date(2026, 11, 21), 12)                  # Saturday
    assert not nettleie.is_day_hour(date(2026, 4, 2), 12)                    # Skjærtorsdag 2026
    assert not nettleie.is_day_hour(date(2026, 5, 14), 12)                   # Kristi himmelfart 2026


def test_tibber_grid_days_splits_day_night_and_peak():
    import tibber
    nodes = _hour_nodes(date(2026, 11, 16), 2, lambda d, h: 3.0 if h == 18 else 1.0)    # Mon, Tue
    nodes += _hour_nodes(date(2026, 11, 16), 1, lambda d, h: 0.5)                       # a second home
    g = tibber.grid_days(nodes)
    assert g[date(2026, 11, 16)] == [16 * 1.5 + 2.0, 8 * 1.5, 3.5]       # 06-22 day, rest night, peak 18:00
    assert date(2026, 11, 16) not in tibber.grid_days(nodes, partial_first=True)


def test_year_cost_includes_nettleie_from_hourly_data():
    import nettleie
    import tibber
    today = date(2026, 11, 17)
    data = _tibber_data(today)
    per_day = tibber.daily(data)
    grid = tibber.grid_days(_hour_nodes(date(2025, 12, 17), 335, lambda d, h: 2.0))     # 48 kWh/day, peak 2 kW
    plain = tibber.year_cost(per_day, {}, today)
    with_grid = tibber.year_cost(per_day, {}, today, grid)
    assert with_grid["nettleie"] and not plain["nettleie"]
    so_far = [d for d in grid if date(2026, 1, 1) <= d < today]
    energy = sum(nettleie.energy_cost(d, grid[d][0], grid[d][1]) for d in so_far)
    fees = 6 * 125 + 4 * 150 + 150 * 16 / 30          # 0-2 kW step: Jan-Jun, Jul-Oct new price, Nov pro rata
    assert with_grid["cost"] == round(plain["cost"] + energy + fees)
    assert with_grid["estimate"] > plain["estimate"] + energy + 6 * 125 + 6 * 150
    short = {d: v for d, v in grid.items() if d > date(2026, 6, 1)}
    assert tibber.year_cost(per_day, {}, today, short)["nettleie"] is False   # hourly data doesn't cover the year


def test_tibber_hourly_backfill_once_then_last_days(monkeypatch):
    import tibber
    from datetime import timedelta
    today = date(2026, 11, 17)
    daily_data = _tibber_data(today)
    hours = _hour_nodes(date(2025, 12, 1), (today - date(2025, 12, 1)).days + 1)
    hourly_calls = []

    def fake(token, q, timeout=10):
        if "HOURLY" not in q:
            return daily_data
        hourly_calls.append(q)
        last = int(q.split("last: ")[1].split(",")[0].split(")")[0])
        end = int(q.split('before: "')[1].split('"')[0]) if "before:" in q else len(hours)
        start = max(0, end - last)
        return {"viewer": {"homes": [{"id": "h1", "consumption": {
            "pageInfo": {"startCursor": str(start), "hasPreviousPage": start > 0}, "nodes": hours[start:end]}}]}}
    monkeypatch.setattr(tibber, "query", fake)
    s3 = S3()
    first = tibber.energy("t", today, s3, "b")
    assert first["year_cost"]["nettleie"] and len(hourly_calls) == 11          # back to 1 Jan, 744 hours a page
    hourly_calls.clear()
    tibber.energy("t", today + timedelta(days=1), s3, "b")
    assert len(hourly_calls) == 1 and "last: 72" in hourly_calls[0]
    cached = json.loads(s3.get_object(Bucket="b", Key=tibber.CACHE_KEY)["Body"].read())
    assert min(cached["grid"]) <= "2026-01-01"


def test_energy_box_labels_nettleie():
    import tibber
    today = date(2026, 11, 17)
    energy = tibber.summary(tibber.daily(_tibber_data(today)), today)
    base = {"today": today, "updated": "18:05", "battery": 80, "now": datetime(2026, 11, 17, 18, 5),
            "days": [day(date(2026, 11, 17 + i)) for i in range(0, 6)]}
    opts = {"month_column": True, "upcoming": True, "evening": True}
    a = dense.render(dict(base, energy=dict(energy, year_cost=dict(energy["year_cost"], nettleie=True))), opts)
    b = dense.render(dict(base, energy=energy), opts)
    assert a.crop((551, 380, 700, 400)).tobytes() != b.crop((551, 380, 700, 400)).tobytes()
