"""School-letter extraction and Google Calendar sync (no network)."""
import json
import os
import sys
from datetime import date

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from school import calendar_sync, extract  # noqa: E402

TODAY = date(2026, 11, 16)

# What the model returns for the real "Uke 47, 6. trinn" letter
UKE47 = {
    "doc_type": "ukebrev", "week": 47, "year": 0, "grade": 6,
    "items": [
        {"weekday": "Mandag", "date": "", "start": "", "end": "", "kind": "gym", "title": "Fysak",
         "bring": ["gymtøy"], "details": "", "for": [], "already_in_calendar": False},
        {"weekday": "Tirsdag", "date": "", "start": "", "end": "", "kind": "trip",
         "title": "Turdag – mat og helse på uteskolen",
         "bring": ["vedkubbe", "vannflaske", "sitteunderlag"], "details": "iPad kan være hjemme.",
         "for": [], "already_in_calendar": False},
        {"weekday": "Onsdag", "date": "", "start": "13:20", "end": "", "kind": "early_finish",
         "title": "Slutt 13:20", "bring": [], "details": "", "for": [], "already_in_calendar": False},
        {"weekday": "Torsdag", "date": "", "start": "", "end": "", "kind": "closed",
         "title": "Skole og SFO stengt – kursdag", "bring": [], "details": "", "for": [], "already_in_calendar": False},
        {"weekday": "Fredag", "date": "", "start": "13:40", "end": "", "kind": "early_finish",
         "title": "Slutt 13:40", "bring": [], "details": "", "for": [], "already_in_calendar": False},
        {"weekday": "Torsdag", "date": "2026-12-03", "start": "18:00", "end": "19:30", "kind": "meeting",
         "title": "Foreldremøte", "bring": [], "details": "", "for": [], "already_in_calendar": True},
    ],
    "week_reminders": ["skiftetøy og innesko", "gamle bukser/t-skjorter til poser"],
    "dinner_question": "Hvordan finner man arealet av en firkant og trekant?",
}


def test_week_dates_and_items():
    week_id, items = extract.to_calendar_items(UKE47, TODAY, default_for=["Amalie"])
    assert week_id == "2026-W47"
    assert all(i["for"] == ["Amalie"] for i in items)
    by_title = {i["title"]: i for i in items}
    tur = by_title["Turdag – mat og helse på uteskolen – husk vedkubbe, vannflaske, sitteunderlag"]
    assert tur["date"] == date(2026, 11, 17) and tur["kind"] == "trip"
    assert by_title["Slutt 13:20"]["date"] == date(2026, 11, 18)
    assert by_title["Skole og SFO stengt – kursdag"]["date"] == date(2026, 11, 19)
    assert by_title["Foreldremøte"]["date"] == date(2026, 12, 3)            # explicit date wins
    assert by_title["Foreldremøte"]["already_in_calendar"] is True
    remind = [i for i in items if i["title"].startswith("Husk denne uka")][0]
    assert remind["date"] == date(2026, 11, 16) and "innesko" in remind["title"]


def test_week_without_year_picks_nearest():
    assert extract.week_dates(1, 0, date(2026, 12, 20)) == date(2027, 1, 4)   # next January
    assert extract.week_dates(52, 0, date(2027, 1, 3)) == date(2026, 12, 21)  # last December


def test_document_without_anything_is_an_error():
    with pytest.raises(extract.ExtractError):
        extract.to_calendar_items({"doc_type": "other", "week": 0, "items": []}, TODAY)


# What the model returns for the "Barnas frimarked" flyer (no week, no grade)
FLYER = {
    "doc_type": "other", "week": 0, "year": 0, "grade": 0,
    "items": [
        {"weekday": "", "date": "2027-09-10", "start": "", "end": "", "kind": "deadline",
         "title": "Frist: påmelding Barnas frimarked", "bring": [],
         "details": "Meld på via e-post til post@mossisentrum.no", "for": [], "already_in_calendar": False},
        {"weekday": "", "date": "2027-09-19", "start": "10:00", "end": "16:00", "kind": "special",
         "title": "Barnas frimarked, Moss sentrum", "bring": ["bord", "stoler"],
         "details": "Selge brukte leker, bøker, håndarbeid og smykker. Gratis.", "for": [],
         "already_in_calendar": False},
        {"weekday": "", "date": "2026-09-19", "start": "10:00", "end": "16:00", "kind": "special",
         "title": "Gammel versjon", "bring": [], "details": "", "for": ["Sigrid"], "already_in_calendar": False},
    ],
    "week_reminders": ["ignored for non-weekly docs"], "dinner_question": "",
}


def test_flyer_items_use_dates_and_no_week_key():
    key, items = extract.to_calendar_items(FLYER, TODAY)
    assert key is None
    assert [i["date"] for i in items] == [date(2027, 9, 10), date(2027, 9, 19), date(2026, 9, 19)]
    assert items[1]["title"] == "Barnas frimarked, Moss sentrum – husk bord, stoler"
    assert items[0]["for"] == [] and items[2]["for"] == ["Sigrid"]
    assert not any(i["title"].startswith("Husk denne uka") for i in items)


def test_title_prefix():
    assert extract.title_prefix([]) == ""
    assert extract.title_prefix(["Amalie"]) == "Amalie: "
    assert extract.title_prefix(["Amalie", "Sigrid"]) == "Amalie og Sigrid: "


def test_children_and_grades_advance_in_august():
    kids = extract.parse_children("Amalie:6, Sigrid:3")
    assert kids == [("Amalie", 6), ("Sigrid", 3)]
    assert extract.child_for_grade(6, kids, 2026, TODAY) == "Amalie"
    assert extract.child_for_grade(3, kids, 2026, TODAY) == "Sigrid"
    assert extract.child_for_grade(6, kids, 2026, date(2027, 6, 1)) == "Amalie"   # same school year
    assert extract.child_for_grade(7, kids, 2026, date(2027, 9, 1)) == "Amalie"   # next school year
    assert extract.child_for_grade(5, kids, 2026, TODAY) is None


def test_content_blocks():
    assert extract.content_block(b"%PDF-1.7 ...", "application/octet-stream")["type"] == "document"
    assert extract.content_block(b"\x89PNG...", "image/png")["source"]["media_type"] == "image/png"
    assert extract.content_block("Uke 47".encode(), "text/plain") == {"type": "text", "text": "Uke 47"}
    with pytest.raises(extract.ExtractError):
        extract.content_block(b"....ftypheic", "image/heic")


class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class FakeAnthropic:
    def __init__(self, result, stop_reason="end_turn"):
        self.result, self.stop_reason, self.requests = result, stop_reason, []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        r = type("R", (), {})()
        r.stop_reason = self.stop_reason
        r.content = [_Block(json.dumps(self.result))]
        return r


def test_call_model_request_shape():
    fake = FakeAnthropic(UKE47)
    existing = [(date(2026, 12, 3), "18:00", "Foreldremøte 6B")]
    out = extract.call_model(fake, b"%PDF-1.7", "application/pdf", TODAY, existing=existing,
                             children_now=[("Amalie", 6), ("Sigrid", 3)])
    assert out["week"] == 47
    req = fake.requests[0]
    assert req["model"] == "anthropic.claude-opus-5-5"
    assert req["output_config"]["format"]["type"] == "json_schema"
    content = req["messages"][0]["content"]
    assert content[0]["type"] == "document"
    assert content[1]["text"] == "Familiens barn: Amalie (6. trinn), Sigrid (3. trinn)."
    assert "2026-12-03 18:00 Foreldremøte 6B" in content[2]["text"]
    assert "2026-11-16" in content[3]["text"]
    assert "Husk" in req["system"]


def test_call_model_refusal():
    with pytest.raises(extract.ExtractError):
        extract.call_model(FakeAnthropic({}, stop_reason="refusal"), b"x", "text/plain", TODAY)


# ------------------------------------------------------------------ calendar
class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data, self.text = status, data or {}, json.dumps(data or {})

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, listing):
        self.listing, self.posted, self.deleted, self.gets = listing, [], [], []

    def get(self, url, params=None):
        self.gets.append(params)
        if params and "privateExtendedProperty" in params:
            return FakeResp(200, {"items": [e for e in self.listing
                                            if (e.get("extendedProperties") or {}).get("private", {}).get("source")]})
        return FakeResp(200, {"items": self.listing})

    def delete(self, url):
        self.deleted.append(url)
        return FakeResp(204)

    def post(self, url, json=None):
        self.posted.append(json)
        return FakeResp(200, json)


def test_family_events_excludes_our_weekly_letter_events():
    session = FakeSession([
        {"summary": "Foreldremøte 6B", "start": {"dateTime": "2026-12-03T17:00:00Z"}},
        {"summary": "Bursdag", "start": {"date": "2026-11-20"}},
        {"id": "x", "summary": "Amalie: Slutt 13:20", "start": {"date": "2026-11-18"},
         "extendedProperties": {"private": {"source": calendar_sync.SOURCE, "doc": "week"}}},
        {"id": "y", "summary": "Barnas frimarked", "start": {"date": "2027-09-19"},
         "extendedProperties": {"private": {"source": calendar_sync.SOURCE, "doc": "other"}}},
    ])
    ev = calendar_sync.family_events(session, "cal@group", TODAY, date(2027, 2, 1))
    assert (date(2026, 12, 3), "18:00", "Foreldremøte 6B") in ev     # converted to Oslo time
    assert (date(2026, 11, 20), "", "Bursdag") in ev
    assert all("Slutt" not in t for _, _, t in ev)                     # replaced on re-upload
    assert (date(2027, 9, 19), "", "Barnas frimarked") in ev           # flyer events stay visible


def test_sync_weekly_letter_replaces_old_and_formats_events():
    old = {"id": "old1", "summary": "Amalie: gammel", "start": {"date": "2026-11-17"},
           "extendedProperties": {"private": {"source": calendar_sync.SOURCE, "doc": "week"}}}
    session = FakeSession([old])
    _, items = extract.to_calendar_items(UKE47, TODAY, default_for=["Amalie"])
    items = [i for i in items if not i["already_in_calendar"]]
    scope = {"week": "2026-W47", "letter_child": "Amalie"}
    deleted, created = calendar_sync.sync_items(session, "cal@group", items, scope)
    assert deleted == 1 and created == len(items) == 6
    q = session.gets[0]["privateExtendedProperty"]
    assert "letter_child=Amalie" in q and "week=2026-W47" in q and "doc=week" in q
    bodies = {b["summary"]: b for b in session.posted}
    slutt = bodies["Amalie: Slutt 13:20"]
    assert slutt["start"] == {"dateTime": "2026-11-18T13:20:00", "timeZone": "Europe/Oslo"}
    assert slutt["end"]["dateTime"] == "2026-11-18T13:50:00"
    closed = bodies["Amalie: Skole og SFO stengt – kursdag"]
    assert closed["start"] == {"date": "2026-11-19"} and closed["end"] == {"date": "2026-11-20"}
    assert closed["extendedProperties"]["private"]["week"] == "2026-W47"
    assert closed["transparency"] == "transparent"


def test_flyer_sync_creates_without_deleting_and_without_name_prefix():
    session = FakeSession([])
    _, items = extract.to_calendar_items(FLYER, TODAY)
    deleted, created = calendar_sync.sync_items(session, "cal@group", items[:2], scope=None)
    assert (deleted, created) == (0, 2) and session.gets == []
    b = session.posted[1]
    assert b["summary"] == "Barnas frimarked, Moss sentrum – husk bord, stoler"
    assert b["start"] == {"dateTime": "2027-09-19T10:00:00", "timeZone": "Europe/Oslo"}
    assert b["end"]["dateTime"] == "2027-09-19T16:00:00"
    assert b["extendedProperties"]["private"]["doc"] == "other"
    assert "post@mossisentrum.no" in session.posted[0]["description"]


def test_rich_text_becomes_text_block():
    blk = extract.content_block(b"{\\rtf1\\ansi Uke 47}", "text/rtf")
    assert blk["type"] == "text" and "Uke 47" in blk["text"]
    assert extract.content_block(b"<p>Uke 47</p>", "text/html")["type"] == "text"
