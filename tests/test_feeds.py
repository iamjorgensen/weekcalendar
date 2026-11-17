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
    assert feeds.parse_feeds(spec) == [("https://ics.example.com/norway.ics", ["Christian"]),
                                       ("https://x/y.ics", [])]


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
    assert "Norge - Danmark Christian" in titles and "Italia - Norge Christian" in titles
    assert all("Sverige" not in t for t in titles)       # September match is in the past
    m1 = next(b for b in s.posted if b["summary"].startswith("Norge - Danmark"))
    assert m1["start"]["dateTime"].startswith("2026-11-17T19:45") and m1["location"] == "Ullevaal Stadion, Oslo"
    assert m1["extendedProperties"]["private"] == {"source": feeds.SOURCE, "feed": "f", "uid": "match-1@fotmob"}
    camp = next(b for b in s.posted if b["summary"].startswith("Landslagssamling"))
    assert camp["start"] == {"date": "2026-11-20"} and camp["end"] == {"date": "2026-11-21"}


def test_sync_updates_changed_time_and_deletes_cancelled():
    ours = [
        _ours("match-1@fotmob", "2026-11-17T18:00:00+00:00", "Norge - Danmark Christian"),   # time changed
        _ours("match-2@fotmob", "2027-03-25T20:45:00+01:00", "Italia - Norge Christian"),
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
