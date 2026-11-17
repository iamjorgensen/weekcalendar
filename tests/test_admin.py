"""Admin page: config store, admin API, and config consumers (render, ingest)."""
import base64
import io
import json

import pytest

import config_store
import ingest_handler
import render_handler
import serve_handler
from test_aws_handlers import BUCKET, TOKEN, FakeContext, _put_params, _url_event, aws, fake_lambda, served  # noqa: F401
from test_school import UKE47, FakeAnthropic, FakeSession

ADMIN = "admin-key-123"
SHEET = [
    {"keyword": "Movar:", "icon": "trash", "replacement": "", "mode": "replace_icon", "color": ""},
    {"keyword": "amalie", "icon": "", "replacement": "A", "mode": "replace_text", "color": "YELLOW"},
    {"keyword": "a:", "icon": "", "replacement": "A", "mode": "replace_text", "color": "YELLOW"},
    {"keyword": "sigrid", "icon": "", "replacement": "S", "mode": "replace_text", "color": "RED"},
    {"keyword": "JR IK", "icon": "soccer", "replacement": "P", "mode": "add_all", "color": "BLUE"},
    {"keyword": "peter", "icon": "", "replacement": "P", "mode": "replace_text", "color": "BLUE"},
    {"keyword": "japp", "icon": "dog", "replacement": "Japp", "mode": "replace_all", "color": "GRAY"},
]


def _cfg():
    return config_store.bootstrap(SHEET, "Amalie:6,Sigrid:3", 2026,
                                  "https://pub.fotmob.com/prod/pub/api/v2/calendar/team/8492.ics | Amalie", "collapse+month")


# ------------------------------------------------------------------ config_store
def test_bootstrap_from_sheet_and_ssm():
    cfg = _cfg()
    names = [p["name"] for p in cfg["people"]]
    assert names == ["Amalie", "Sigrid", "Peter"]
    amalie = cfg["people"][0]
    assert amalie == {"name": "Amalie", "letter": "A", "color": "YELLOW", "kind": "barn", "grade": 6,
                      "groups": [], "words": ["amalie", "a:"], "birthday": "", "nameday": "", "celebrate": True}
    rules = {r["word"]: r for r in cfg["rules"]}
    assert rules["Movar:"] == {"word": "Movar:", "icon": "trash", "tag": "", "remove": True}
    assert rules["JR IK"]["tag"] == "Peter" and rules["JR IK"]["remove"] is False
    assert rules["japp"] == {"word": "japp", "icon": "dog", "tag": "", "remove": True}
    assert cfg["feeds"][0]["icon"] == "soccer" and cfg["feeds"][0]["tags"] == ["Amalie"]
    assert cfg["view"]["options"] == ["collapse", "month"]


def test_event_mappings_modes_round_trip():
    rows = {r["keyword"]: r for r in config_store.event_mappings(_cfg())}
    assert rows["amalie"] == {"keyword": "amalie", "icon": "", "replacement": "A", "mode": "replace_text",
                              "color": "YELLOW", "match_type": "contains", "size_px": 18}
    assert rows["Movar:"]["mode"] == "replace_icon" and rows["Movar:"]["icon"] == "trash"
    assert rows["JR IK"]["mode"] == "add_all" and rows["JR IK"]["replacement"] == "P"
    assert rows["japp"]["mode"] == "replace_icon"


@pytest.mark.parametrize("mutate,msg", [
    (lambda c: c["people"][0].update(color="PINK"), "farge"),
    (lambda c: c["people"].append(dict(c["people"][0])), "to ganger"),
    (lambda c: c["rules"].append({"word": "x", "tag": "Ola"}), "Ola"),
    (lambda c: c["feeds"].append({"url": "ftp://x"}), "https"),
    (lambda c: c["people"][1].update(grade=14), "1–13"),
    (lambda c: c["rules"].append({"word": "y", "icon": "Bad Icon"}), "ikonnavn"),
])
def test_validate_rejects_bad_input(mutate, msg):
    cfg = _cfg()
    mutate(cfg)
    with pytest.raises(config_store.ConfigError, match=msg):
        config_store.validate(cfg)


def test_children_and_feeds_spec():
    cfg = _cfg()
    cfg["people"][1]["groups"] = ["Sild"]
    assert config_store.children(cfg) == [("Amalie", 6, []), ("Sigrid", 3, ["Sild"])]
    assert config_store.feeds_spec(cfg) == "https://pub.fotmob.com/prod/pub/api/v2/calendar/team/8492.ics | Amalie | soccer"
    cfg["feeds"][0]["on"] = False
    assert config_store.feeds_spec(cfg) == ""


# ------------------------------------------------------------------ admin API
def _api(path, method="GET", key=ADMIN, body=None):
    ev = _url_event(path, method=method, headers={"x-admin-token": key} if key else {})
    if body is not None:
        ev["body"] = json.dumps(body)
    return serve_handler.handler(ev, FakeContext())


def test_admin_page_and_auth(aws, monkeypatch):
    _s3, ssm = aws
    resp = serve_handler.handler(_url_event("/admin"), FakeContext())
    assert resp["statusCode"] == 200 and "text/html" in resp["headers"]["Content-Type"]
    assert "/api/config" in resp["body"]
    assert _api("/api/config")["statusCode"] == 503            # ADMIN_TOKEN not set
    _put_params(ssm, {"ADMIN_TOKEN": ADMIN, "FRAME_TOKEN": TOKEN})
    assert _api("/api/config", key="wrong")["statusCode"] == 401
    assert _api("/api/config", key=TOKEN)["statusCode"] == 401   # the frame token is not an admin key


def test_admin_bootstrap_then_save(aws, monkeypatch):
    s3, ssm = aws
    _put_params(ssm, {"ADMIN_TOKEN": ADMIN, "CHILDREN": "Amalie:6,Sigrid:3", "CHILDREN_SCHOOL_YEAR": "2026"})
    monkeypatch.setattr(config_store, "_fetch_sheet_rows", lambda *a, **k: SHEET)
    first = json.loads(_api("/api/config")["body"])
    assert first["stored"] is False and first["config"]["people"][1]["grade"] == 3
    cfg = first["config"]
    cfg["people"][1]["groups"] = ["Sild"]
    saved = _api("/api/config", "PUT", body=cfg)
    assert saved["statusCode"] == 200
    again = json.loads(_api("/api/config")["body"])
    assert again["stored"] is True and again["config"]["people"][1]["groups"] == ["Sild"]
    cfg["people"][0]["color"] = "PINK"
    bad = _api("/api/config", "PUT", body=cfg)
    assert bad["statusCode"] == 400 and "farge" in json.loads(bad["body"])["error"]
    # a second save keeps the previous version in history
    cfg["people"][0]["color"] = "GREEN"
    assert _api("/api/config", "PUT", body=cfg)["statusCode"] == 200
    hist = s3.list_objects_v2(Bucket=BUCKET, Prefix="config/history/").get("KeyCount", 0)
    assert hist >= 1


def test_admin_status_preview_and_render(served, fake_lambda):
    s3 = served
    import test_aws_handlers as T
    T._put_params(T.boto3.client("ssm", region_name=T.REGION), {"ADMIN_TOKEN": ADMIN})
    s3.put_object(Bucket=BUCKET, Key="log/letters.json", Body=json.dumps([{"at": 1, "message": "La til 6"}]).encode())
    st = json.loads(_api("/api/status")["body"])
    assert st["meta"]["event_count"] == 3 and st["letters"][0]["message"] == "La til 6"
    prev = _api("/api/preview")
    assert prev["statusCode"] == 200 and prev["isBase64Encoded"] and base64.b64decode(prev["body"])[:4] == b"\x89PNG"
    r = _api("/api/render", "POST")
    assert r["statusCode"] == 202 and json.loads(fake_lambda.calls[-1]["Payload"])["force_feeds"] is True


# ------------------------------------------------------------------ consumers
def test_ingest_uses_config_children_groups_and_logs(aws, monkeypatch):
    s3, ssm = aws
    _put_params(ssm, {"GOOGLE_SA_JSON": "{}", "CALENDAR_ID": "fam@group"})   # no CHILDREN in SSM
    cfg = _cfg()
    cfg["people"][1]["groups"] = ["Sild"]
    config_store.save(s3, BUCKET, cfg)
    s3.put_object(Bucket=BUCKET, Key="inbox/a.pdf", Body=b"%PDF-1.7", ContentType="application/pdf")
    fake_ai = FakeAnthropic(UKE47)
    monkeypatch.setattr(ingest_handler, "anthropic_client", lambda api_key=None: fake_ai)
    monkeypatch.setattr(ingest_handler, "calendar_session", lambda sa: FakeSession([]))
    out = ingest_handler.handler({"bucket": BUCKET, "key": "inbox/a.pdf"}, None)
    assert out["ok"] and out["child"] == "Amalie"
    kids_text = fake_ai.requests[0]["messages"][0]["content"][1]["text"]
    assert "Sigrid (3. trinn, gruppe Sild)" in kids_text and "Gruppe Sild" in fake_ai.requests[0]["system"]
    log = json.loads(s3.get_object(Bucket=BUCKET, Key="log/letters.json")["Body"].read())
    assert log[-1]["message"] == out["message"]


def test_render_feeds_come_from_config(aws, monkeypatch):
    import requests
    import school.calendar_sync as cs
    from test_feeds import ICS, Session
    s3, ssm = aws
    _put_params(ssm, {"GOOGLE_SA_JSON": "{}", "CALENDAR_ID": "fam@group",
                      "CALENDAR_FEEDS": "https://ignored.example/old.ics | Christian"})
    cfg = _cfg()
    session, fetched = Session(), []

    class R:
        text = ICS
        def raise_for_status(self):
            pass
    monkeypatch.setattr(requests, "get", lambda url, **kw: (fetched.append(url), R())[1])
    monkeypatch.setattr(cs, "session_from_service_account", lambda info: session)
    render_handler.sync_calendar_feeds(s3, BUCKET, [], cfg=cfg)
    assert fetched == ["https://pub.fotmob.com/prod/pub/api/v2/calendar/team/8492.ics"]
    assert all(b["summary"].endswith(" Amalie") for b in session.posted)
    assert all(b["extendedProperties"]["private"]["icon"] == "soccer" for b in session.posted)


def test_ai_model_from_config(aws, monkeypatch):
    s3, ssm = aws
    _put_params(ssm, {"GOOGLE_SA_JSON": "{}", "CALENDAR_ID": "fam@group", "ANTHROPIC_API_KEY": "sk-ant-x"})
    cfg = _cfg()
    cfg["ai"] = {"model": "claude-haiku-5-5"}
    config_store.save(s3, BUCKET, cfg)
    s3.put_object(Bucket=BUCKET, Key="inbox/a.pdf", Body=b"%PDF-1.7", ContentType="application/pdf")
    fake_ai = FakeAnthropic(UKE47)
    monkeypatch.setattr(ingest_handler, "anthropic_client", lambda api_key=None: fake_ai)
    monkeypatch.setattr(ingest_handler, "calendar_session", lambda sa: FakeSession([]))
    out = ingest_handler.handler({"bucket": BUCKET, "key": "inbox/a.pdf"}, None)
    assert out["ok"] and [r["model"] for r in fake_ai.requests] == ["claude-haiku-5-5"]
    cfg["ai"] = {"model": "gpt-4"}
    with pytest.raises(config_store.ConfigError, match="AI-modell"):
        config_store.validate(cfg)
    assert config_store.validate({"people": []})["ai"] == {"model": "claude-sonnet-5-5"}
