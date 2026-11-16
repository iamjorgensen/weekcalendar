"""
Tests for the AWS Lambda handlers (aws_lambda/). AWS is mocked with moto and
all outbound HTTP is blocked, so these run offline with fake credentials.

    pip install -r infra/requirements-lambda.txt boto3 "moto[s3,ssm]" pytest
    pytest tests/test_aws_handlers.py
"""

import base64
import io
import json
import sys
from datetime import date, timedelta

import boto3
import pytest
import requests
from botocore.exceptions import ReadTimeoutError
from moto import mock_aws
from PIL import Image

import aws_common
import render_handler
import serve_handler

REGION = "eu-west-1"
BUCKET = "weekcalendar-test-bucket"
PREFIX = "/weekcalendar/"
TOKEN = "test-frame-token-123"
APP_MODULES = ("main", "data_provider", "mappings", "layout_renderer", "inky_icons_package", "weather_provider")


# --- fixtures -----------------------------------------------------------------

@pytest.fixture
def aws(monkeypatch, tmp_path):
    # Never touch real AWS (or the invalid credentials in the environment)
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN", "AWS_ROLE_ARN",
                "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_REGION", REGION)

    monkeypatch.setenv("BUCKET_NAME", BUCKET)
    monkeypatch.setenv("PARAM_PREFIX", PREFIX)
    monkeypatch.setenv("RENDER_FUNCTION_NAME", "weekcalendar-render")
    monkeypatch.setenv("WORK_DIR", str(tmp_path / "work"))
    # Let configure_paths() derive the cache paths under WORK_DIR
    for var in ("GS_CACHE_PATH", "AI_ICON_CACHE_PATH", "ICONS_CACHE_DIR"):
        monkeypatch.delenv(var, raising=False)
    # Values must come from SSM, not from the developer's shell
    for name in aws_common.DATA_PARAM_NAMES + [aws_common.FRAME_TOKEN_PARAM]:
        monkeypatch.delenv(name, raising=False)

    with mock_aws():
        aws_common.reset_clients()
        serve_handler.reset_token_cache()
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        ssm = boto3.client("ssm", region_name=REGION)
        yield s3, ssm
        aws_common.reset_clients()
        serve_handler.reset_token_cache()


@pytest.fixture
def offline(monkeypatch):
    """Block all HTTP made with requests (Google Sheet CSV, icon downloads, APIs)."""
    def _blocked(self, method, url, *a, **k):
        raise requests.ConnectionError(f"network blocked in tests: {method} {url}")
    monkeypatch.setattr(requests.sessions.Session, "request", _blocked)


@pytest.fixture
def fresh_app(monkeypatch):
    """Force the app modules to be imported again inside the test (env read at import)."""
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)  # ignore any local .env
    for name in APP_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(render_handler, "_app", None)


def _put_params(ssm, values):
    for name, value in values.items():
        ssm.put_parameter(Name=PREFIX + name, Value=value, Type="SecureString")


def _sample_data():
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()
    return {
        "events": [
            {"date": d(0), "time": "08:30", "name": "Tannlege"},
            {"date": d(1), "time": "", "name": "Restavfall"},
            {"date": d(2), "time": "18:00", "name": "Fotballtrening"},
        ],
        "weather": [
            {"date": d(0), "temp_max": 7, "temp_min": 1, "precip_mm": 2.4, "wind_ms": 4, "symbol_code": "rain"},
            {"date": d(1), "temp_max": 5, "temp_min": -1, "precip_mm": 0.0, "wind_ms": 2, "symbol_code": "clearsky_day"},
        ],
        "hourly_today": [],
        "meta": {},
    }


def _png_bytes(color, size=(800, 480)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _url_event(path, method="GET", query=None, headers=None):
    return {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "&".join(f"{k}={v}" for k, v in (query or {}).items()),
        "queryStringParameters": query,
        "headers": headers or {},
        "requestContext": {"http": {"method": method, "path": path}},
        "isBase64Encoded": False,
    }


def _decode_image(resp):
    assert resp["isBase64Encoded"] is True
    return Image.open(io.BytesIO(base64.b64decode(resp["body"])))


class FakeContext:
    def __init__(self, remaining_ms=75_000):
        self._remaining = remaining_ms

    def get_remaining_time_in_millis(self):
        return self._remaining


# --- render handler -------------------------------------------------------------

def _prepare_render(aws, monkeypatch, fetch):
    """Load config + import the app like the handler does, then stub the data fetch."""
    render_handler.load_config()
    (main, data_provider, mappings), first = render_handler.import_app()
    assert first
    monkeypatch.setattr(data_provider, "initial_fetch_all", fetch)
    return main, data_provider, mappings


def test_render_handler_loads_params_renders_and_uploads(aws, monkeypatch, offline, fresh_app, tmp_path):
    s3, ssm = aws
    _put_params(ssm, {
        "API_KEY_GOOGLE": "test-google-key",
        "CALENDAR_ID": "test-calendar@example.com",
        "LAT": "59.9",
        "LON": "10.7",
        # OPENAI_API_KEY, MOVAR_* etc. deliberately missing: must not crash
    })
    # A cache from an earlier run should be restored before data_provider uses it
    s3.put_object(Bucket=BUCKET, Key="cache/ai_icon_cache.json", Body=b'{"Tannlege": "stethoscope"}')
    s3.put_object(Bucket=BUCKET, Key="cache/icons/old-icon.svg", Body=b"<svg xmlns='http://www.w3.org/2000/svg'/>")

    calls = {}

    def fake_fetch(days=7, **kwargs):
        import os
        calls["days"] = days
        # simulate IconManager downloading a new icon during the run
        with open(os.path.join(os.environ["ICONS_CACHE_DIR"], "new-icon.svg"), "w") as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg'/>")
        return _sample_data()

    main, data_provider, mappings = _prepare_render(aws, monkeypatch, fake_fetch)

    # env was populated from SSM before data_provider was imported
    assert data_provider.API_KEY_GOOGLE == "test-google-key"
    assert data_provider.CALENDAR_ID == "test-calendar@example.com"
    assert data_provider.LAT == 59.9
    assert data_provider.OPENAI_API_KEY == ""
    # caches point at the writable work dir, not the (read-only) code dir
    work = str(tmp_path / "work")
    assert data_provider.AI_ICON_CACHE_PATH.startswith(work)
    assert mappings.GS_CACHE_PATH.startswith(work)
    assert main.opts["icon_manager"].cache_dir.startswith(work)

    result = render_handler.handler({"source": "test"}, None)

    assert result["ok"] is True
    assert calls["days"] == 7

    png = Image.open(io.BytesIO(s3.get_object(Bucket=BUCKET, Key="latest/output.png")["Body"].read()))
    assert png.format == "PNG" and png.size == (800, 480)
    jpg_obj = s3.get_object(Bucket=BUCKET, Key="latest/output.jpg")
    assert jpg_obj["ContentType"] == "image/jpeg"
    assert Image.open(io.BytesIO(jpg_obj["Body"].read())).size == (800, 480)

    meta = json.loads(s3.get_object(Bucket=BUCKET, Key="latest/meta.json")["Body"].read())
    assert meta["event_count"] == 3
    assert meta["trigger"] == "test"
    assert meta["errors"] == []
    assert "OPENAI_API_KEY" in meta["missing_params"]
    assert "API_KEY_GOOGLE" not in meta["missing_params"]
    assert "rendered_at" in meta

    # caches restored and saved back
    with open(data_provider.AI_ICON_CACHE_PATH) as f:
        assert json.load(f)["Tannlege"] == "stethoscope"
    keys = {o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET, Prefix="cache/")["Contents"]}
    assert "cache/ai_icon_cache.json" in keys
    assert "cache/icons/new-icon.svg" in keys
    assert "cache/icons/old-icon.svg" in keys


def test_render_handler_survives_fetch_failure(aws, monkeypatch, offline, fresh_app):
    s3, _ssm = aws  # no SSM parameters at all

    def broken_fetch(days=7, **kwargs):
        raise RuntimeError("calendar API down")

    _prepare_render(aws, monkeypatch, broken_fetch)
    result = render_handler.handler({}, None)

    assert result["ok"] is True
    meta = json.loads(s3.get_object(Bucket=BUCKET, Key="latest/meta.json")["Body"].read())
    assert meta["event_count"] == 0
    assert any("calendar API down" in e for e in meta["errors"])
    assert set(aws_common.DATA_PARAM_NAMES) <= set(meta["missing_params"])
    png = Image.open(io.BytesIO(s3.get_object(Bucket=BUCKET, Key="latest/output.png")["Body"].read()))
    assert png.size == (800, 480)


# --- serve handler --------------------------------------------------------------

@pytest.fixture
def served(aws):
    s3, ssm = aws
    _put_params(ssm, {"FRAME_TOKEN": TOKEN})
    s3.put_object(Bucket=BUCKET, Key="latest/output.png", Body=_png_bytes("white"), ContentType="image/png")
    jpg = io.BytesIO()
    Image.new("RGB", (800, 480), "white").save(jpg, "JPEG")
    s3.put_object(Bucket=BUCKET, Key="latest/output.jpg", Body=jpg.getvalue(), ContentType="image/jpeg")
    s3.put_object(Bucket=BUCKET, Key="latest/meta.json", Body=b'{"event_count": 3, "errors": []}')
    return s3


class FakeLambda:
    """Stands in for the boto3 Lambda client used by serve_handler."""

    def __init__(self, on_invoke=None):
        self.calls = []
        self.on_invoke = on_invoke

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        if self.on_invoke:
            return self.on_invoke(**kwargs)
        return {"StatusCode": 202 if kwargs["InvocationType"] == "Event" else 200}


@pytest.fixture
def fake_lambda(monkeypatch):
    fake = FakeLambda()
    timeouts = []

    def factory(timeout_s=None):
        timeouts.append(timeout_s)
        return fake

    monkeypatch.setattr(serve_handler, "_lambda_client", factory)
    fake.timeouts = timeouts
    return fake


@pytest.mark.parametrize("query", [None, {"token": "wrong"}, {"token": ""}, {"token": TOKEN + "x"}])
def test_serve_rejects_bad_token(served, fake_lambda, query):
    resp = serve_handler.handler(_url_event("/image.png", query=query), FakeContext())
    assert resp["statusCode"] == 401
    assert fake_lambda.calls == []


def test_serve_png_ok(served, fake_lambda):
    resp = serve_handler.handler(_url_event("/image.png", query={"token": TOKEN}), FakeContext())
    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "image/png"
    assert resp["headers"]["Cache-Control"] == "no-store"
    assert resp["headers"]["X-Render-Status"] == "cached"
    img = _decode_image(resp)
    assert img.format == "PNG" and img.size == (800, 480)
    assert fake_lambda.calls == []  # no render without fresh=1


def test_serve_jpg_ok(served, fake_lambda):
    resp = serve_handler.handler(_url_event("/image.jpg", query={"token": TOKEN}), FakeContext())
    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "image/jpeg"
    assert _decode_image(resp).format == "JPEG"


def test_serve_status(served, fake_lambda):
    assert serve_handler.handler(_url_event("/status"), FakeContext())["statusCode"] == 401
    resp = serve_handler.handler(_url_event("/status", query={"token": TOKEN}), FakeContext())
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["event_count"] == 3


def test_serve_post_render_starts_async(served, fake_lambda):
    bad = serve_handler.handler(_url_event("/render", "POST", headers={"X-Run-Token": "nope"}), FakeContext())
    assert bad["statusCode"] == 401
    assert serve_handler.handler(_url_event("/render", "GET", query={"token": TOKEN}), FakeContext())["statusCode"] == 405

    resp = serve_handler.handler(_url_event("/render", "POST", headers={"X-Run-Token": TOKEN}), FakeContext())
    assert resp["statusCode"] == 202
    assert len(fake_lambda.calls) == 1
    assert fake_lambda.calls[0]["InvocationType"] == "Event"
    assert fake_lambda.calls[0]["FunctionName"] == "weekcalendar-render"


def test_serve_fresh_renders_then_returns_new_image(served, fake_lambda):
    def render_now(**kwargs):
        served.put_object(Bucket=BUCKET, Key="latest/output.png", Body=_png_bytes((255, 0, 0)))
        return {"StatusCode": 200}

    fake_lambda.on_invoke = render_now
    resp = serve_handler.handler(_url_event("/image.png", query={"token": TOKEN, "fresh": "1"}), FakeContext())

    assert resp["statusCode"] == 200
    assert resp["headers"]["X-Render-Status"] == "fresh"
    assert fake_lambda.calls[0]["InvocationType"] == "RequestResponse"
    # waits less than the time this invocation has left
    assert 0 < fake_lambda.timeouts[0] <= 70
    assert _decode_image(resp).convert("RGB").getpixel((10, 10)) == (255, 0, 0)


def test_serve_fresh_falls_back_to_stale_on_function_error(served, fake_lambda):
    fake_lambda.on_invoke = lambda **kw: {"StatusCode": 200, "FunctionError": "Unhandled",
                                          "Payload": io.BytesIO(b'{"errorMessage": "boom"}')}
    resp = serve_handler.handler(_url_event("/image.png", query={"token": TOKEN, "fresh": "1"}), FakeContext())
    assert resp["statusCode"] == 200
    assert resp["headers"]["X-Render-Status"] == "stale"
    assert _decode_image(resp).convert("RGB").getpixel((10, 10)) == (255, 255, 255)


def test_serve_fresh_falls_back_to_stale_on_timeout(served, fake_lambda):
    def too_slow(**kwargs):
        raise ReadTimeoutError(endpoint_url="https://lambda.eu-west-1.amazonaws.com")

    fake_lambda.on_invoke = too_slow
    resp = serve_handler.handler(_url_event("/image.jpg", query={"token": TOKEN, "fresh": "1"}), FakeContext())
    assert resp["statusCode"] == 200
    assert resp["headers"]["X-Render-Status"] == "stale"
    assert resp["headers"]["Content-Type"] == "image/jpeg"


def test_serve_fresh_skips_render_when_no_time_left(served, fake_lambda):
    resp = serve_handler.handler(_url_event("/image.png", query={"token": TOKEN, "fresh": "1"}),
                                 FakeContext(remaining_ms=6_000))
    assert resp["headers"]["X-Render-Status"] == "stale"
    assert fake_lambda.calls == []


def test_serve_fresh_end_to_end_with_real_render(served, fake_lambda, monkeypatch, offline, fresh_app):
    """fresh=1 -> (fake) Lambda invoke -> real render_handler -> new image served."""
    _prepare_render(None, monkeypatch, lambda days=7, **kw: _sample_data())

    def invoke_render(**kwargs):
        render_handler.handler(json.loads(kwargs["Payload"]), None)
        return {"StatusCode": 200}

    fake_lambda.on_invoke = invoke_render
    resp = serve_handler.handler(_url_event("/image.png", query={"token": TOKEN, "fresh": "1"}), FakeContext())
    assert resp["headers"]["X-Render-Status"] == "fresh"
    img = _decode_image(resp)
    assert img.size == (800, 480)
    meta = json.loads(served.get_object(Bucket=BUCKET, Key="latest/meta.json")["Body"].read())
    assert meta["trigger"] == "serve-fresh" and meta["event_count"] == 3


def test_serve_missing_image_and_unknown_path(aws, fake_lambda):
    _s3, ssm = aws
    _put_params(ssm, {"FRAME_TOKEN": TOKEN})
    assert serve_handler.handler(_url_event("/image.png", query={"token": TOKEN}), FakeContext())["statusCode"] == 404
    assert serve_handler.handler(_url_event("/nope", query={"token": TOKEN}), FakeContext())["statusCode"] == 404


def test_serve_503_when_token_not_configured(aws, fake_lambda):
    resp = serve_handler.handler(_url_event("/image.png", query={"token": "anything"}), FakeContext())
    assert resp["statusCode"] == 503


def test_serve_fresh_render_fails_and_no_image_gives_404_with_reason(aws, fake_lambda, monkeypatch):
    """Regression: first render failed + S3 AccessDenied for a missing key used to crash (502)."""
    from botocore.exceptions import ClientError
    _s3, ssm = aws
    _put_params(ssm, {"FRAME_TOKEN": TOKEN})
    fake_lambda.on_invoke = lambda **kw: {"StatusCode": 200, "FunctionError": "Unhandled",
                                          "Payload": io.BytesIO(b'{"errorType": "ImportError", "errorMessage": "no module x"}')}

    class DeniedS3:
        def get_object(self, **kw):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetObject")

    real_client = serve_handler.aws_common.client
    monkeypatch.setattr(serve_handler.aws_common, "client",
                        lambda name, *a, **k: DeniedS3() if name == "s3" else real_client(name, *a, **k))
    resp = serve_handler.handler(_url_event("/image.png", query={"token": TOKEN, "fresh": "1"}), FakeContext())
    assert resp["statusCode"] == 404
    assert "ImportError: no module x" in resp["body"]
    assert resp["headers"]["X-Render-Error"] == "ImportError: no module x"


def test_serve_unexpected_error_is_500_not_crash(served, fake_lambda, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(serve_handler, "_serve_image", boom)
    resp = serve_handler.handler(_url_event("/image.png", query={"token": TOKEN}), FakeContext())
    assert resp["statusCode"] == 500 and "kaboom" in resp["body"]


def test_serve_fresh_passes_battery_to_render(served, fake_lambda):
    import json as _json
    serve_handler.handler(_url_event("/image.png", query={"token": TOKEN, "fresh": "1", "batt": "64"}), FakeContext())
    payload = _json.loads(fake_lambda.calls[-1]["Payload"])
    assert payload["battery"] == 64
    serve_handler.handler(_url_event("/image.png", query={"token": TOKEN, "fresh": "1", "batt": "999"}), FakeContext())
    assert "battery" not in _json.loads(fake_lambda.calls[-1]["Payload"])


# ------------------------------------------------------------------ school letters
import ingest_handler  # noqa: E402
from test_school import UKE47, FakeAnthropic, FakeSession  # noqa: E402


def _upload_event(data, content_type="application/pdf", token=TOKEN):
    ev = _url_event("/upload", method="POST", headers={"content-type": content_type, "x-run-token": token})
    ev["body"] = base64.b64encode(data).decode("ascii")
    ev["isBase64Encoded"] = True
    return ev


def test_upload_rejects_bad_token_heic_and_get(aws, fake_lambda):
    _s3, ssm = aws
    _put_params(ssm, {"FRAME_TOKEN": TOKEN})
    assert serve_handler.handler(_upload_event(b"%PDF", token="nope"), FakeContext())["statusCode"] == 401
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20
    resp = serve_handler.handler(_upload_event(heic, "image/heic"), FakeContext())
    assert resp["statusCode"] == 415 and "JPEG" in resp["body"]
    assert serve_handler.handler(_url_event("/upload", query={"token": TOKEN}), FakeContext())["statusCode"] == 405
    assert fake_lambda.calls == []


def test_upload_stores_file_and_returns_ingest_message(aws, fake_lambda, monkeypatch):
    s3, ssm = aws
    _put_params(ssm, {"FRAME_TOKEN": TOKEN})
    monkeypatch.setenv("INGEST_FUNCTION_NAME", "weekcalendar-ingest")
    fake_lambda.on_invoke = lambda **kw: {"StatusCode": 200, "Payload": io.BytesIO(
        json.dumps({"ok": True, "message": "La til 6 hendelser for Amalie, uke 47"}).encode())}
    resp = serve_handler.handler(_upload_event(b"%PDF-1.7 letter"), FakeContext())
    assert resp["statusCode"] == 200 and resp["body"] == "La til 6 hendelser for Amalie, uke 47"
    payload = json.loads(fake_lambda.calls[-1]["Payload"])
    assert fake_lambda.calls[-1]["FunctionName"] == "weekcalendar-ingest"
    assert payload["key"].startswith("inbox/") and payload["key"].endswith(".pdf")
    assert s3.get_object(Bucket=BUCKET, Key=payload["key"])["Body"].read() == b"%PDF-1.7 letter"


def test_ingest_end_to_end(aws, monkeypatch):
    s3, ssm = aws
    _put_params(ssm, {"GOOGLE_SA_JSON": '{"type": "service_account"}', "CALENDAR_ID": "fam@group",
                      "CHILDREN": "Amalie:6,Sigrid:3", "CHILDREN_SCHOOL_YEAR": "2026"})
    s3.put_object(Bucket=BUCKET, Key="inbox/a.pdf", Body=b"%PDF-1.7", ContentType="application/pdf")
    fake_ai = FakeAnthropic(UKE47)
    session = FakeSession([{"summary": "Foreldremøte 6B", "start": {"dateTime": "2026-12-03T17:00:00Z"}}])
    monkeypatch.setattr(ingest_handler, "anthropic_client", lambda: fake_ai)
    monkeypatch.setattr(ingest_handler, "calendar_session", lambda sa: session)

    class FixedDT(ingest_handler.datetime):
        @classmethod
        def now(cls, tz=None):
            return ingest_handler.datetime(2026, 11, 16, 20, 0, tzinfo=tz)
    monkeypatch.setattr(ingest_handler, "datetime", FixedDT)

    out = ingest_handler.handler({"bucket": BUCKET, "key": "inbox/a.pdf", "content_type": "application/pdf"}, None)
    assert out["ok"] and out["child"] == "Amalie" and out["week"] == "2026-W47"
    assert out["created"] == 6 and out["skipped"] == 1
    assert "Fantes fra før: Foreldremøte (03.12)" in out["message"]
    assert "Foreldremøte 6B" in fake_ai.requests[0]["messages"][0]["content"][1]["text"]
    assert all(b["summary"].startswith("Amalie: ") for b in session.posted)


def test_ingest_reports_missing_settings(aws):
    _s3, ssm = aws
    out = ingest_handler.handler({"bucket": BUCKET, "key": "inbox/x.pdf"}, None)
    assert out["ok"] is False and "GOOGLE_SA_JSON" in out["message"]
