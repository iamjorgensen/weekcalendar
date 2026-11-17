"""Spond integration (no network)."""
import io
import json
from datetime import date, datetime, timezone

import pytest

import config_store
import render_handler
import serve_handler
import spond_client
from test_admin import ADMIN, _api, _cfg
from test_aws_handlers import BUCKET, _put_params, aws  # noqa: F401
from test_feeds import Session

EVENTS = [
    {"id": "E1", "heading": "Trening G16", "startTimestamp": "2026-11-18T17:00:00Z", "endTimestamp": "2026-11-18T18:30:00Z",
     "location": {"feature": "Melløs stadion", "address": "Moss"}},
    {"id": "E2", "heading": "Kamp mot Sprint", "startTimestamp": "2026-11-21T11:00:00Z", "endTimestamp": "2026-11-21T12:30:00Z",
     "cancelled": True},
    {"id": "E3", "heading": "", "startTimestamp": "2026-11-22T11:00:00Z"},
]


def test_to_feed_events():
    evs = spond_client.to_feed_events(EVENTS)
    assert [e["uid"] for e in evs] == ["spond-E1", "spond-E2"]        # no heading -> skipped
    assert evs[0]["location"] == "Melløs stadion, Moss" and evs[0]["start"].tzinfo is not None
    assert evs[1]["status"] == "CANCELLED" and evs[0]["status"] == ""


def test_login_parses_token(monkeypatch):
    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass
    seen = []
    monkeypatch.setattr(spond_client.urllib.request, "urlopen",
                        lambda req, timeout=None: (seen.append(req), R(json.dumps({"accessToken": {"token": "tok"}}).encode()))[1])
    assert spond_client.login("a@b.no", "pw") == "tok"
    assert seen[0].full_url.endswith("/core/v1/auth2/login") and json.loads(seen[0].data) == {"email": "a@b.no", "password": "pw"}
    monkeypatch.setattr(spond_client.urllib.request, "urlopen", lambda req, timeout=None: R(b'{"error": "nope"}'))
    with pytest.raises(spond_client.SpondError):
        spond_client.login("a@b.no", "bad")


def _spond_cfg():
    cfg = _cfg()
    cfg["feeds"] = []          # Spond only in these tests
    cfg["spond"] = {"on": True, "groups": [{"id": "G1", "name": "JR IK G16", "tags": ["Peter"], "icon": "soccer", "on": True},
                                           {"id": "G2", "name": "Korps", "tags": [], "icon": "", "on": False}]}
    return config_store.validate(cfg)


def test_config_validates_spond():
    cfg = _spond_cfg()
    assert cfg["spond"]["groups"][0] == {"id": "G1", "name": "JR IK G16", "tags": ["Peter"], "icon": "soccer", "on": True, "only_accepted": False}
    bad = dict(cfg, spond={"on": True, "groups": [{"id": "G1", "tags": ["Ola"]}]})
    with pytest.raises(config_store.ConfigError, match="Ola"):
        config_store.validate(bad)


def test_render_syncs_spond_and_removes_cancelled(aws, monkeypatch):
    import school.calendar_sync as cs
    s3, ssm = aws
    _put_params(ssm, {"GOOGLE_SA_JSON": "{}", "CALENDAR_ID": "fam@group", "SPOND_EMAIL": "a@b.no", "SPOND_PASSWORD": "pw"})
    already = {"id": "ev-E2", "summary": "Kamp mot Sprint Peter",
               "start": {"dateTime": "2026-11-21T11:00:00+00:00"}, "end": {"dateTime": "2026-11-21T12:30:00+00:00"},
               "extendedProperties": {"private": {"source": "weekcalendar-feed", "feed": "spond-G1", "uid": "spond-E2"}}}
    session = Session(ours=[already])
    calls = []
    monkeypatch.setattr(spond_client, "login", lambda e, p: "tok")
    monkeypatch.setattr(spond_client, "events", lambda tok, gid, **k: (calls.append(gid), EVENTS)[1])
    monkeypatch.setattr(cs, "session_from_service_account", lambda info: session)

    class FixedDT(render_handler.datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 17, 6, 0, tzinfo=tz or timezone.utc)
    monkeypatch.setattr(render_handler, "datetime", FixedDT)
    errors = []
    res = render_handler.sync_calendar_feeds(s3, BUCKET, errors, cfg=_spond_cfg())
    assert errors == [] and calls == ["G1"]                      # only enabled groups
    assert res["spond-G1"]["created"] == 1 and res["spond-G1"]["deleted"] == 1
    assert session.deleted == ["ev-E2"]                            # cancelled match removed
    b = session.posted[0]
    assert b["summary"] == "Trening G16 Peter" and b["extendedProperties"]["private"]["icon"] == "soccer"


def test_admin_spond_groups(aws, monkeypatch):
    _s3, ssm = aws
    _put_params(ssm, {"ADMIN_TOKEN": ADMIN})
    r = _api("/api/spond/groups")
    assert r["statusCode"] == 400 and "SPOND_EMAIL" in json.loads(r["body"])["error"]
    _put_params(ssm, {"SPOND_EMAIL": "a@b.no", "SPOND_PASSWORD": "pw"})
    monkeypatch.setattr(spond_client, "login", lambda e, p: "tok")
    monkeypatch.setattr(spond_client, "groups", lambda tok: [{"id": "G1", "name": "JR IK G16", "subGroups": []}])
    r = _api("/api/spond/groups")
    assert r["statusCode"] == 200 and json.loads(r["body"])["groups"][0]["name"] == "JR IK G16"


SPOND_OLD = {"id": "old1", "summary": "Trening G16", "start": {"dateTime": "2026-11-20T17:00:00+01:00"},
             "description": "https://spond.com/client/sponds/ABC", "iCalUID": "abc@spond.com"}
FAMILY = {"id": "fam1", "summary": "Tannlege", "start": {"dateTime": "2026-11-20T09:00:00+01:00"}}
OURS = {"id": "our1", "summary": "Trening G16 Peter", "start": {"dateTime": "2026-11-20T17:00:00+01:00"},
        "description": "spond", "extendedProperties": {"private": {"source": "weekcalendar-feed", "uid": "spond-E1"}}}


def test_find_and_delete_old_spond_events():
    from school import feeds
    s = Session(manual=[SPOND_OLD, FAMILY, OURS])
    found = feeds.find_foreign(s, "cal", date(2026, 1, 1), date(2027, 1, 1))
    assert [e["id"] for e in found] == ["old1"]                    # not the family's own, not ours
    n = feeds.delete_ids(s, "cal", ["old1", "fam1", "our1"], {e["id"] for e in found})
    assert n == 1 and s.deleted == ["old1"]                        # never deletes anything not listed


def test_render_cleanup_action(aws, monkeypatch):
    import school.calendar_sync as cs
    _s3, ssm = aws
    _put_params(ssm, {"GOOGLE_SA_JSON": "{}", "CALENDAR_ID": "fam@group"})
    s = Session(manual=[SPOND_OLD, FAMILY])
    monkeypatch.setattr(cs, "session_from_service_account", lambda info: s)
    res = render_handler.handler({"action": "spond_cleanup"}, None)
    assert [e["summary"] for e in res["events"]] == ["Trening G16"] and s.deleted == []
    res = render_handler.handler({"action": "spond_cleanup", "delete": ["old1", "fam1"]}, None)
    assert res == {"deleted": 1} and s.deleted == ["old1"]


def test_admin_cleanup_endpoint(aws, monkeypatch):
    _s3, ssm = aws
    _put_params(ssm, {"ADMIN_TOKEN": ADMIN})
    calls = []

    def fake_call(payload):
        calls.append(payload)
        return {"deleted": len(payload["delete"])} if "delete" in payload else {"events": [{"id": "old1"}]}
    monkeypatch.setattr(serve_handler, "_call_render", fake_call)
    monkeypatch.setattr(serve_handler, "_invoke_render", lambda *a, **k: calls.append(("render", k)) or (True, "ok"))
    assert _api("/api/spond/cleanup", key="wrong")["statusCode"] == 401
    r = _api("/api/spond/cleanup")
    assert r["statusCode"] == 200 and json.loads(r["body"])["events"][0]["id"] == "old1"
    r = _api("/api/spond/cleanup", method="POST", body={"ids": ["old1"]})
    assert r["statusCode"] == 200 and json.loads(r["body"]) == {"deleted": 1}
    assert calls[1] == {"action": "spond_cleanup", "delete": ["old1"]} and calls[2][0] == "render"
    assert _api("/api/spond/cleanup", method="POST", body={"ids": "x"})["statusCode"] == 400


def test_only_accepted_filters_on_our_members(aws, monkeypatch):
    import school.calendar_sync as cs
    s3, ssm = aws
    _put_params(ssm, {"GOOGLE_SA_JSON": "{}", "CALENDAR_ID": "fam@group", "SPOND_EMAIL": "a@b.no", "SPOND_PASSWORD": "pw"})
    group = {"id": "G1", "members": [
        {"id": "M-PETER", "profile": {"id": "P-KID"}, "guardians": [{"id": "x", "profile": {"id": "P-ME"}}]},
        {"id": "M-OTHER", "profile": {"id": "P-OTHER"}, "guardians": []}]}

    def fake_request(method, path, token=None, **k):
        return {"profile": {"id": "P-ME"}, "groups/": [group]}[path]
    monkeypatch.setattr(spond_client, "_request", fake_request)
    assert spond_client.my_member_ids("tok") == {"M-PETER"}

    evs = [{"id": "E1", "heading": "Trening", "startTimestamp": "2026-11-20T16:00:00Z",
            "responses": {"acceptedIds": ["M-PETER"]}},
           {"id": "E2", "heading": "Cup", "startTimestamp": "2026-11-21T09:00:00Z",
            "responses": {"acceptedIds": ["M-OTHER"], "declinedIds": ["M-PETER"]}}]
    monkeypatch.setattr(spond_client, "login", lambda e, p: "tok")
    monkeypatch.setattr(spond_client, "events", lambda tok, gid, **k: evs)
    session = Session()
    monkeypatch.setattr(cs, "session_from_service_account", lambda info: session)
    cfg = _spond_cfg()
    for g in cfg["spond"]["groups"]:
        g["only_accepted"] = True
    cfg = config_store.validate(cfg)
    assert all(g["only_accepted"] for g in cfg["spond"]["groups"])
    errors = []
    res = render_handler.sync_calendar_feeds(s3, BUCKET, errors, force=True, cfg=cfg)
    assert errors == [] and res["spond-G1"]["found"] == 1
    assert [b["summary"] for b in session.posted] == ["Trening Peter"]


def test_only_accepted_never_wipes_when_members_unknown(aws, monkeypatch):
    import school.calendar_sync as cs
    s3, ssm = aws
    _put_params(ssm, {"GOOGLE_SA_JSON": "{}", "CALENDAR_ID": "fam@group", "SPOND_EMAIL": "a@b.no", "SPOND_PASSWORD": "pw"})
    monkeypatch.setattr(spond_client, "login", lambda e, p: "tok")
    monkeypatch.setattr(spond_client, "events", lambda tok, gid, **k: [])
    monkeypatch.setattr(spond_client, "my_member_ids", lambda tok: set())
    ours = {"id": "ev-1", "summary": "Trening Peter", "start": {"dateTime": "2026-12-20T16:00:00+00:00"},
            "extendedProperties": {"private": {"source": "weekcalendar-feed", "feed": "spond-G1", "uid": "spond-E1"}}}
    session = Session(ours=[ours])
    monkeypatch.setattr(cs, "session_from_service_account", lambda info: session)
    cfg = _spond_cfg()
    cfg["spond"]["groups"][0]["only_accepted"] = True
    errors = []
    res = render_handler.sync_calendar_feeds(s3, BUCKET, errors, force=True, cfg=cfg)
    assert session.deleted == [] and "error" in res["spond-G1"] and errors


def test_spond_test_action_reports(aws, monkeypatch):
    import school.calendar_sync as cs
    s3, ssm = aws
    _put_params(ssm, {"GOOGLE_SA_JSON": "{}", "CALENDAR_ID": "fam@group", "SPOND_EMAIL": "a@b.no", "SPOND_PASSWORD": "pw"})
    assert "error" in render_handler.handler({"action": "spond_test"}, None)          # nothing saved yet
    config_store.save(s3, BUCKET, _spond_cfg())
    monkeypatch.setattr(spond_client, "login", lambda e, p: "tok")
    monkeypatch.setattr(spond_client, "events", lambda tok, gid, **k: EVENTS)
    monkeypatch.setattr(cs, "session_from_service_account", lambda info: Session())
    rep = render_handler.handler({"action": "spond_test"}, None)
    assert rep["groups_on"] == ["JR IK G16"] and rep["errors"] == []
    assert rep["result"]["spond-G1"]["name"] == "Spond: JR IK G16" and rep["result"]["spond-G1"]["found"] == 2   # the one without a title is dropped
