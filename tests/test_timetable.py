from datetime import date

from designs.common import YELLOW, GREEN
from school import extract, timetable
from test_school import UKE47

PEOPLE = [{"name": "Amalie", "letter": "A", "color": "YELLOW"}, {"name": "Sigrid", "letter": "S", "color": "GREEN"},
          {"name": "Kari", "letter": "K", "color": "RED"}]
A, S = ("A", YELLOW), ("S", GREEN)


def store():
    return timetable.merge({}, "Amalie", "2026-W47", extract.to_timetable(UKE47))


def day(d, *events):
    return {"date": d, "events": [{"time": "", "people": [], "is_holiday": False, **e} for e in events]}


def test_to_timetable_cleans_times_and_closed_days():
    days = extract.to_timetable(UKE47)
    assert [d["weekday"] for d in days] == [0, 1, 2, 3, 4]
    assert days[0] == {"weekday": 0, "start": "09:00", "end": "14:45", "lunch": "10:50",
                       "lessons": ["KRLE", "Fysak / Norsk", "Engelsk"], "closed": False, "note": ""}
    assert days[1]["start"] == "09:00"
    assert days[3]["closed"] and days[3]["start"] == "" and days[3]["note"].startswith("Kursdag")
    assert extract.to_timetable({}) == []


def test_merge_keeps_newest_weeks_and_replaces_a_week():
    s = {}
    for w in range(30, 45):
        s = timetable.merge(s, "Amalie", f"2026-W{w}", [{"weekday": 0}])
    assert len(s["Amalie"]) == timetable.KEEP_WEEKS and "2026-W44" in s["Amalie"]
    s = timetable.merge(s, "Amalie", "2026-W44", [{"weekday": 1}])
    assert s["Amalie"]["2026-W44"] == [{"weekday": 1}]


def test_rows_for_a_normal_and_an_early_day():
    rows = timetable.day_rows(store(), PEOPLE, day(date(2026, 11, 16)))
    assert len(rows) == 1      # only Amalie has a timetable
    r = rows[0]
    assert (r["name"], r["color"], r["start"], r["lunch"], r["end"]) == ("Amalie", YELLOW, "09:00", "10:50", "14:45")
    assert not r["early"] and not r["off"]
    wed = timetable.day_rows(store(), PEOPLE, day(date(2026, 11, 18)))[0]
    assert wed["end"] == "13:20" and wed["early"]


def test_closed_day_and_weekend():
    thu = timetable.day_rows(store(), PEOPLE, day(date(2026, 11, 19)))[0]
    assert thu["off"] and thu["note"] == "Kursdag – skole og SFO stengt"
    assert timetable.day_rows(store(), PEOPLE, day(date(2026, 11, 21))) == []


def test_calendar_overrides_the_timetable():
    # a "Skoleslutt" for her in the calendar, and someone else's early finish is ignored
    rows = timetable.day_rows(store(), PEOPLE, day(date(2026, 11, 16),
                                                   {"title": "Skoleslutt 12:30", "people": [A]},
                                                   {"title": "Skoleslutt 11:00", "people": [S]}))
    assert rows[0]["end"] == "12:30" and rows[0]["early"]
    # a holiday week without a letter: the fallback timetable is not shown as a school day
    later = date(2026, 11, 23)
    assert timetable.day_rows(store(), PEOPLE, day(later))[0]["end"] == "14:45"     # last week's Monday
    off = timetable.day_rows(store(), PEOPLE, day(later, {"title": "Vinterferie", "people": [A]}))[0]
    assert off["off"] and off["note"] == "Vinterferie"
    red = timetable.day_rows(store(), PEOPLE, day(later, {"title": "1. juledag", "is_holiday": True}))[0]
    assert red["off"]


def test_fallback_skips_old_weeks_and_one_off_closures():
    # last week's Thursday was a one-off closure: no row, rather than "Fri" again
    assert timetable.day_rows(store(), PEOPLE, day(date(2026, 11, 26))) == []
    assert timetable.day_rows(store(), PEOPLE, day(date(2026, 12, 21))) == []               # > 3 weeks old
