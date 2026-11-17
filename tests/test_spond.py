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
    assert cfg["spond"]["groups"][0] == {"id": "G1", "name": "JR IK G16", "tags": ["Peter"], "icon": "soccer", "on": True}
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
