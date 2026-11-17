"""Calendar-feed sync (ICS -> family Google Calendar), no network."""
import json
import os
import sys
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from school import feeds  # noqa: E402

TODAY = date(2026, 11, 17)

ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:match-1@fotmob\r
SUMMARY:Norge - Danmark\r
DTSTART:20261117T194500Z\r
DTEND:20261117T214500Z\r
LOCATION:Ullevaal Stadion\\, Oslo\r
DESCRIPTION:VM-kvalifisering\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:match-2@fotmob\r
SUMMARY:Italia - Norge\r
DTSTART;TZID=Europe/Rome:20270325T204500\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:old@fotmob\r
SUMMARY:Norge - Sverige\r
DTSTART:20260901T180000Z\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:camp@fotmob\r
SUMMARY:Landslagssamling med en veldig lang tittel som er brettet over\r
  flere linjer\r
DTSTART;VALUE=DATE:20261120\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_parse_feeds_config():
    spec = "webcal://ics.example.com/norway.ics | Christian\n# comment\nhttps://x/y.ics\n"
    assert feeds.parse_feeds(spec) == [("https://ics.example.com/norway.ics", ["Christian"], ""),
                                       ("https://x/y.ics", [], "")]
    fm = feeds.parse_feeds("https://pub.fotmob.com/x/8492.ics | Christian\nhttps://a/b.ics | Peter | tree")
    assert fm == [("https://pub.fotmob.com/x/8492.ics", ["Christian"], "soccer"), ("https://a/b.ics", ["Peter"], "tree")]


def test_parse_ics_formats():
    evs = {e["uid"]: e for e in feeds.parse_ics(ICS)}
    m1 = evs["match-1@fotmob"]
    assert m1["start"] == datetime(2026, 11, 17, 19, 45, tzinfo=timezone.utc)
    assert m1["location"] == "Ullevaal Stadion, Oslo" and not m1["all_day"]
    assert evs["match-2@fotmob"]["start"].utcoffset().total_seconds() == 3600   # Rome, winter time
    camp = evs["camp@fotmob"]
    assert camp["all_day"] and camp["start"] == date(2026, 11, 20)
    assert camp["summary"].endswith("brettet over flere linjer")


class Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self._d, self.text = status, data or {}, json.dumps(data or {})

    def json(self):
        return self._d


class Session:
    """Fake Google Calendar: `ours` are events this sync wrote, `manual` the family's own."""

    def __init__(self, ours=(), manual=()):
        self.ours, self.manual = list(ours), list(manual)
        self.posted, self.patched, self.deleted = [], [], []

    def get(self, url, params=None):
        if params and "privateExtendedProperty" in params:
            return Resp(200, {"items": self.ours})
        return Resp(200, {"items": self.manual + self.ours})

    def post(self, url, json=None):
        self.posted.append(json)
        return Resp(200, json)

    def patch(self, url, json=None):
        self.patched.append((url.rsplit("/", 1)[-1], json))
        return Resp(200, json)

    def delete(self, url):
        self.deleted.append(url.rsplit("/", 1)[-1])
        return Resp(204)


def _ours(uid, start_iso, summary):
    return {"id": "ev-" + uid, "summary": summary, "start": {"dateTime": start_iso},
            "end": {"dateTime": start_iso},
            "extendedProperties": {"private": {"source": feeds.SOURCE, "feed": "f", "uid": uid}}}


def test_sync_creates_with_names_last_and_skips_past():
    s = Session()
    stats = feeds.sync_feed(s, "cal", ICS, ["Christian"], "f", TODAY)
    assert stats == {"created": 3, "updated": 0, "deleted": 0, "skipped": 0}
    titles = [b["summary"] for b in s.posted]
    assert "Norge – Danmark Christian" in titles and "Italia – Norge Christian" in titles
    assert all("Sverige" not in t for t in titles)       # September match is in the past
    m1 = next(b for b in s.posted if b["summary"].startswith("Norge – Danmark"))
    assert m1["start"]["dateTime"].startswith("2026-11-17T19:45") and m1["location"] == "Ullevaal Stadion, Oslo"
    assert m1["extendedProperties"]["private"] == {"source": feeds.SOURCE, "feed": "f", "uid": "match-1@fotmob"}
    camp = next(b for b in s.posted if b["summary"].startswith("Landslagssamling"))
    assert camp["start"] == {"date": "2026-11-20"} and camp["end"] == {"date": "2026-11-21"}


def test_sync_updates_changed_time_and_deletes_cancelled():
    ours = [
        _ours("match-1@fotmob", "2026-11-17T18:00:00+00:00", "Norge – Danmark Christian"),   # time changed
        _ours("match-2@fotmob", "2027-03-25T20:45:00+01:00", "Italia – Norge Christian"),
        _ours("gone@fotmob", "2027-01-10T18:00:00+00:00", "Norge - Island Christian"),        # no longer in feed
    ]
    ours[1]["end"] = {"dateTime": "2027-03-25T22:45:00+01:00"}
    s = Session(ours=ours)
    stats = feeds.sync_feed(s, "cal", ICS, ["Christian"], "f", TODAY)
    assert stats["updated"] == 1 and s.patched[0][0] == "ev-match-1@fotmob"
    assert stats["deleted"] == 1 and s.deleted == ["ev-gone@fotmob"]
    assert stats["created"] == 1                          # only the all-day camp is new


def test_sync_skips_what_the_family_already_added():
    manual = [{"summary": "Fotball: Norge - Danmark!", "start": {"dateTime": "2026-11-17T20:45:00+01:00"}}]
    s = Session(manual=manual)
    stats = feeds.sync_feed(s, "cal", ICS, ["Christian"], "f", TODAY)
    assert stats["skipped"] == 1 and stats["created"] == 2


FOTMOB = """BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
DESCRIPTION:https://www.fotmob.com/match/1\\nWorld Cup Qualification \r
 UEFA\r
DTSTART:20261117T194500Z\r
DTEND:20261117T214500Z\r
LOCATION:Parken\\, København\\, DEN\r
SUMMARY:\U0001F1E9\U0001F1F0 Denmark - \U0001F1F3\U0001F1F4 Norway\r
UID:1-8492@fotmob.com\r
BEGIN:VALARM\r
ACTION:DISPLAY\r
DESCRIPTION:Denmark - Norway starting in 15 minutes\r
SUMMARY:\U0001F1E9\U0001F1F0 Denmark - \U0001F1F3\U0001F1F4 Norway starting in 15 minutes\r
TRIGGER:-PT15M\r
END:VALARM\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_fotmob_feed_alarm_ignored_and_title_cleaned():
    ev = feeds.parse_ics(FOTMOB)[0]
    assert ev["summary"].endswith("Norway") and "starting" not in ev["summary"]
    assert ev["description"].startswith("https://www.fotmob.com/match/1")
    assert feeds.clean_title(ev["summary"]) == "Danmark – Norge"
    s = Session()
    feeds.sync_feed(s, "cal", FOTMOB, ["Christian"], "f", TODAY)
    assert s.posted[0]["summary"] == "Danmark – Norge Christian"
    assert s.posted[0]["start"]["dateTime"].startswith("2026-11-17T19:45")


def test_clean_title_keeps_ordinary_text():
    assert feeds.clean_title("Bosnia and Herzegovina - Norway (1-4)") == "Bosnia-Hercegovina – Norge (1-4)"
    assert feeds.clean_title("Juleavslutning") == "Juleavslutning"


def test_resync_corrects_title_written_by_old_version():
    old_title = "\U0001F1E9\U0001F1F0 Denmark - \U0001F1F3\U0001F1F4 Norway starting in 15 minutes Christian"
    ours = [{"id": "ev-1", "summary": old_title,
             "start": {"dateTime": "2026-11-17T19:45:00+00:00"}, "end": {"dateTime": "2026-11-17T21:45:00+00:00"},
             "extendedProperties": {"private": {"source": feeds.SOURCE, "feed": "f", "uid": "1-8492@fotmob.com"}}}]
    s = Session(ours=ours)
    stats = feeds.sync_feed(s, "cal", FOTMOB, ["Christian"], "f", TODAY)
    assert stats["updated"] == 1 and stats["created"] == 0
    assert s.patched[0][1]["summary"] == "Danmark – Norge Christian"


def test_feed_icon_stored_and_old_events_patched():
    s = Session()
    feeds.sync_feed(s, "cal", FOTMOB, ["Christian"], "f", TODAY, icon="soccer")
    assert s.posted[0]["extendedProperties"]["private"]["icon"] == "soccer"
    ours = [dict(s.posted[0], id="ev-1")]
    ours[0]["extendedProperties"] = {"private": {k: v for k, v in s.posted[0]["extendedProperties"]["private"].items()
                                                 if k != "icon"}}
    s2 = Session(ours=ours)
    stats = feeds.sync_feed(s2, "cal", FOTMOB, ["Christian"], "f", TODAY, icon="soccer")
    assert stats["updated"] == 1 and s2.patched[0][1]["extendedProperties"]["private"]["icon"] == "soccer"


def test_cancelled_events_are_removed():
    cancelled = ICS.replace("UID:match-2@fotmob\r\n", "UID:match-2@fotmob\r\nSTATUS:CANCELLED\r\n")
    ours = [_ours("match-2@fotmob", "2027-03-25T20:45:00+01:00", "Italia – Norge Christian")]
    s = Session(ours=ours)
    stats = feeds.sync_feed(s, "cal", cancelled, ["Christian"], "f", TODAY)
    assert stats["deleted"] == 1 and s.deleted == ["ev-match-2@fotmob"]
    assert all("Italia" not in b["summary"] for b in s.posted)
