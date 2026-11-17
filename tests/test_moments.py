"""Birthdays, holidays and other special days on the frame (designs/moments.py, splash.py)."""
import os
import sys
from datetime import date, datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "aws_lambda"))

from designs import dense, moments  # noqa: E402
from designs.common import BLACK, RED, YELLOW  # noqa: E402

PEOPLE = [{"name": "Nora", "letter": "N", "color": "YELLOW", "kind": "barn", "birthday": "2016-11-20"},
          {"name": "Lars", "letter": "L", "color": "BLACK", "kind": "voksen", "birthday": "1984-11-17"},
          {"name": "Bamse", "letter": "B", "color": "BLUE", "kind": "dyr", "birthday": "2022-11-28"},
          {"name": "Kari", "letter": "K", "color": "RED", "kind": "voksen", "birthday": "1986-11-24",
           "celebrate": False}]


def day(d, events=(), weather=None):
    return {"date": d, "events": list(events), "weather": weather}


def ev(title, icon=None, holiday=False, span="", people=(), feed="", time=""):
    return {"time": time, "sort_time": time, "title": title, "icon": icon, "people": list(people),
            "is_holiday": holiday, "span": span, "feed": feed}


def test_special_days():
    assert moments.easter(2027) == date(2027, 3, 28)
    sp = moments.special_days(2026)
    assert sp[date(2026, 11, 8)] == "farsdag" and sp[date(2026, 2, 8)] == "morsdag"
    assert sorted(d for d, k in sp.items() if k.startswith("advent")) == \
        [date(2026, 11, 29), date(2026, 12, 6), date(2026, 12, 13), date(2026, 12, 20)]
    assert sp[date(2026, 12, 13)] == "advent3"          # advent wins over Lucia on a Sunday
    assert moments.special_days(2027)[date(2027, 2, 7)] == "fastelavn"


def test_birthday_banner_age_colour_and_black_in_gold():
    b = moments.banner(day(date(2026, 11, 20)), PEOPLE)
    assert b["title"] == "Gratulerer, Nora!" and b["big"] == "10" and b["bg"] == YELLOW
    lars = moments.banner(day(date(2026, 11, 17)), PEOPLE)
    assert lars["bg"] == BLACK and lars["fg"] == YELLOW and lars["edge"] == "rainbow" and lars["big"] == "42"
    assert moments.banner(day(date(2026, 11, 28)), PEOPLE)["icon"] == "dog"
    assert moments.banner(day(date(2026, 11, 24)), PEOPLE) is None      # Kari: celebrate off


def test_holiday_themes_and_day_counter():
    hf = ev("Høstferie", "umbrella_beach", True, "2026-09-28/2026-10-02", [("N", YELLOW), ("E", YELLOW)])
    people = PEOPLE + [{"name": "Emil", "letter": "E", "color": "GREEN"}]
    b = moments.banner(day(date(2026, 9, 29), [hf]), people)
    assert b["title"] == "God høstferie!" and b["big"] == "Dag 2 av 5" and b["small"] == "Nora og Emil har fri"
    assert moments.banner(day(date(2026, 12, 24)), [])["big"] == "Julaften"
    assert moments.banner(day(date(2027, 5, 17)), [])["bg"] == RED
    adv = moments.banner(day(date(2026, 12, 6)), [])
    assert adv["candles"] == 2 and adv["small"] == "18 dager til jul"
    plan = moments.banner(day(date(2026, 11, 20), [ev("Planleggingsdag", holiday=True, people=[("N", YELLOW)])]), PEOPLE)
    assert plan["title"] == "Gratulerer, Nora!"            # a birthday beats the day off
    plan = moments.banner(day(date(2026, 11, 19), [ev("Planleggingsdag", holiday=True, people=[("N", YELLOW)])]), PEOPLE)
    assert plan["title"] == "Fri i dag!" and plan["small"] == "Nora har fri"
    match = moments.banner(day(date(2026, 11, 19), [ev("Norge – Italia", "soccer", feed="abc", time="20:45")]), [])
    assert match["title"] == "Kampdag!" and match["big"] == "20:45"
    spond = day(date(2026, 11, 19), [ev("Trening", "soccer", feed="spond-G1", time="17:00")])
    assert moments.banner(spond, []) is None                # practice is not a match day
    assert moments.banner(day(date(2026, 11, 19)), PEOPLE) is None


def test_lines_countdowns_and_evening_question():
    days = [day(date(2026, 11, 17)), day(date(2026, 11, 18))]
    now = datetime(2026, 11, 17, 6, 0)
    assert moments.lines(days, PEOPLE, now=now) == ["3 dager til Nora 10 år"]
    evening = moments.lines(days, PEOPLE, now=now.replace(hour=18), dinner_question="Hva var best i dag?",
                            evening=True)
    assert evening[0] == "Middagsspørsmål: Hva var best i dag?"
    oct_sat = datetime(2026, 10, 24, 6, 0)
    assert "Klokka stilles tilbake en time i natt" in moments.lines([day(oct_sat.date())], [], now=oct_sat)
    dec = datetime(2026, 12, 10, 6, 0)
    assert "14 dager til jul" in moments.lines([day(dec.date())], [], now=dec)


def test_birthday_events_added_once():
    days = [day(date(2026, 11, 19)), day(date(2026, 11, 20), [ev("Bursdag Ida")]),
            day(date(2026, 11, 28), [ev("Bamse 4 år", "dog")])]
    out = moments.birthday_events(days, PEOPLE)
    assert out[1]["events"][0]["title"] == "Nora 10 år" and out[1]["events"][0]["people"] == [("N", YELLOW)]
    assert [e["title"] for e in out[2]["events"]] == ["Bamse 4 år"]     # already in the calendar


@pytest.mark.parametrize("d", [date(2026, 11, 17), date(2026, 12, 24), date(2026, 12, 6), date(2027, 5, 17),
                               date(2027, 3, 26), date(2026, 12, 31), date(2026, 10, 31)])
def test_render_with_banner(d):
    data = {"today": d, "now": datetime(d.year, d.month, d.day, 6, 30), "updated": "06:30", "battery": 80,
            "people": PEOPLE, "dinner_question": "",
            "days": [day(d, [ev("Juleverksted", "gift"), ev("Tannlege", time="12:00")],
                         {"tmax": 3, "tmin": -1, "symbol": "Skyet", "precip": 0, "wind": 3, "wind_dir": "N"})]
            + [day(date.fromordinal(d.toordinal() + i)) for i in range(1, 10)]}
    img = dense.render(data, {"moments": True, "collapse": True, "month_column": True, "upcoming": True})
    assert img.size == (800, 480)
    assert img.getpixel((40, 60)) != (0, 0, 0) or d in (date(2026, 11, 17), date(2026, 10, 31))   # black banners: Lars, Halloween


def test_config_birthday_validation():
    import config_store
    cfg = {"people": [{"name": "Bamse", "kind": "dyr", "birthday": "2022-11-28"}]}
    out = config_store.validate(cfg)
    assert out["people"][0]["birthday"] == "2022-11-28" and out["people"][0]["kind"] == "dyr"
    assert out["view"]["moments"] is True
    with pytest.raises(config_store.ConfigError):
        config_store.validate({"people": [{"name": "X", "birthday": "28.11.2022"}]})
    assert config_store.people_for_design(out)[0]["celebrate"] is True


ALERTS = {"type": "FeatureCollection", "features": [
    {"properties": {"event": "gale", "eventAwarenessName": "Kuling", "awareness_level": "2; yellow; Moderate",
                    "riskMatrixColor": "Yellow", "title": "Kuling, gult nivå"},
     "when": {"interval": ["2026-11-17T06:00:00+00:00", "2026-11-17T17:00:00+00:00"]}},
    {"properties": {"event": "rainFlood", "eventAwarenessName": "Styrtregn", "awareness_level": "3; orange; Severe",
                    "riskMatrixColor": "Orange"},
     "when": {"interval": ["2026-11-18T03:00:00+00:00", "2026-11-19T12:00:00+00:00"]}}]}


def test_met_alerts_parse_and_frame():
    import met_alerts
    ws = met_alerts.parse(ALERTS)
    assert [w["name"] for w in ws] == ["Styrtregn", "Kuling"] and ws[0]["level"] == 2 and ws[1]["color"] == "yellow"
    today = date(2026, 11, 17)
    b = moments.warning_banner(ws, today)
    assert b["title"] == "Farevarsel!" and b["big"] == "Styrtregn" and b["bg"] == YELLOW
    assert b["small"] == "Oransje nivå · fra i morgen"
    assert moments.warning_lines(ws, today, skip_banner=b) == [
        "Fare for oversvømmelse", "Gult farevarsel: Kuling til kl 18 – sikre løse ting ute"]
    assert moments.warning_banner([ws[1]], today) is None                 # yellow: a line only
    assert moments.active_warnings(ws, date(2026, 11, 25)) == []          # over


def test_red_warning_beats_birthday_orange_does_not():
    import met_alerts
    ws = met_alerts.parse(ALERTS)
    d = date(2026, 11, 18)
    base = {"today": d, "now": datetime(2026, 11, 18, 6, 30), "updated": "06:30", "battery": 80,
            "people": [dict(PEOPLE[0], birthday="2016-11-18")], "dinner_question": "",
            "days": [day(d)] + [day(date(2026, 11, 18 + i)) for i in range(1, 6)]}
    img = dense.render(dict(base, warnings=ws), {"moments": True})
    assert img.getpixel((40, 60)) == YELLOW                               # Nora's birthday (yellow) wins over orange
    red = [dict(ws[0], level=3, color="red")]
    img = dense.render(dict(base, warnings=red), {"moments": True})
    assert img.getpixel((5, 60)) == RED                                   # red warning banner


def test_public_holidays_calculated():
    h = dict((n, d) for d, n in moments.public_holidays(2027))
    assert h["Kristi himmelfartsdag"] == date(2027, 5, 6) and h["2. pinsedag"] == date(2027, 5, 17)
    assert h["Langfredag"] == date(2027, 3, 26) and len(h) == 14
    assert "Julaften" not in dict((n, d) for d, n in moments.public_holidays(2027, julaften=False))
    evs = moments.holiday_events(date(2026, 12, 20), date(2027, 1, 2))
    assert [e["name"] for e in evs] == ["Julaften", "1. juledag", "2. juledag", "Nyttårsaften", "Nyttårsdag"]
    assert all(e["is_holiday"] and e["icon"] == "flag" for e in evs)
    import config_store
    assert config_store.validate({})["view"]["holidays"] == {"on": True, "julaften": True, "nyttarsaften": True}
