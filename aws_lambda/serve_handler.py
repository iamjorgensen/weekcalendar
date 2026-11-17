"""
AWS Lambda behind a Function URL: serves the rendered image to the Inky Frame.

Routes (token = the FRAME_TOKEN SSM parameter):
  GET  /image.png?token=...           latest PNG from S3 (instant)
  GET  /image.jpg?token=...           latest JPEG from S3 (instant)
       add &fresh=1                   render now (synchronously), then return the new
                                      image; on failure/timeout return the last image
                                      with header X-Render-Status: stale
  GET  /status?token=...              latest/meta.json
  POST /render   (X-Run-Token: ...)   start a render in the background -> 202

Uses only the stdlib and boto3 (both in the Lambda runtime), so it ships as a
small zip function.
"""

import base64
import hmac
import json
import logging
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

import aws_common

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

IMAGES = {
    "/image.png": ("latest/output.png", "image/png"),
    "/image.jpg": ("latest/output.jpg", "image/jpeg"),
}
META_KEY = "latest/meta.json"

TOKEN_TTL_SECONDS = 300  # re-read FRAME_TOKEN at most every 5 minutes
_token_cache = {"value": None, "at": 0.0}


def _frame_token():
    now = time.time()
    if _token_cache["value"] is None or now - _token_cache["at"] > TOKEN_TTL_SECONDS:
        found, _missing = aws_common.get_parameters([aws_common.FRAME_TOKEN_PARAM])
        _token_cache["value"] = found.get(aws_common.FRAME_TOKEN_PARAM, "")
        _token_cache["at"] = now
    return _token_cache["value"]


def reset_token_cache():
    _token_cache["value"] = None
    _token_cache["at"] = 0.0


def _token_ok(supplied, expected):
    if not supplied or not expected:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def _resp(status, body="", content_type="text/plain; charset=utf-8", headers=None, b64=False):
    h = {"Content-Type": content_type, "Cache-Control": "no-store"}
    h.update(headers or {})
    return {"statusCode": status, "headers": h, "body": body, "isBase64Encoded": b64}


def _is_missing(err):
    # Without s3:ListBucket, S3 reports a missing key as AccessDenied instead of NoSuchKey.
    return err.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "AccessDenied", "403")


def _header_safe(text):
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in str(text))[:300]


def _json(status, obj, headers=None):
    return _resp(status, json.dumps(obj), "application/json", headers)


def _lambda_client(timeout_s=None):
    if timeout_s is None:
        return aws_common.client("lambda")
    # Synchronous render: wait at most timeout_s, and never retry (a retry would
    # start a second render and blow the frame's HTTP timeout).
    return boto3.client("lambda", config=Config(read_timeout=max(1, int(timeout_s)), connect_timeout=5,
                                                retries={"total_max_attempts": 1}))


def _parse_battery(value):
    try:
        b = int(float(value))
    except (TypeError, ValueError):
        return None
    return b if 0 <= b <= 100 else None


def _invoke_render(invocation_type, timeout_s=None, extra=None):
    """Invoke the render function. Returns (ok, detail)."""
    name = os.environ["RENDER_FUNCTION_NAME"]
    body = {"source": "serve-fresh" if invocation_type == "RequestResponse" else "serve-post"}
    body.update(extra or {})
    payload = json.dumps(body)
    lam = _lambda_client(timeout_s)
    try:
        resp = lam.invoke(FunctionName=name, InvocationType=invocation_type, Payload=payload.encode("utf-8"))
    except (ClientError, BotoCoreError) as e:
        logger.error("Render invoke (%s) failed: %s", invocation_type, e)
        return False, str(e)
    if resp.get("FunctionError"):
        raw = resp["Payload"].read().decode("utf-8", "replace")[:2000] if resp.get("Payload") else ""
        logger.error("Render function error: %s", raw)
        detail = "function error"
        try:
            err = json.loads(raw)
            detail = "{}: {}".format(err.get("errorType", "Error"), err.get("errorMessage", ""))
        except (ValueError, AttributeError):
            pass
        return False, detail
    return True, "ok"


def _call_render(payload):
    """Invoke the render function for a small JSON task and return its JSON result."""
    try:
        resp = _lambda_client(60).invoke(FunctionName=os.environ["RENDER_FUNCTION_NAME"],
                                         InvocationType="RequestResponse",
                                         Payload=json.dumps(payload).encode("utf-8"))
        raw = resp["Payload"].read().decode("utf-8", "replace") if resp.get("Payload") else "{}"
        if resp.get("FunctionError"):
            logger.error("Render task error: %s", raw[:2000])
            try:
                return {"error": json.loads(raw).get("errorMessage", "feil")}
            except ValueError:
                return {"error": raw[:300]}
        return json.loads(raw or "{}")
    except (ClientError, BotoCoreError, ValueError) as e:
        logger.error("Render task failed: %s", e)
        return {"error": str(e)}


def _sync_render_budget(context):
    """Seconds we may wait for a synchronous render, leaving time to return the image."""
    configured = float(os.environ.get("FRESH_RENDER_TIMEOUT", "55"))
    if context is not None and hasattr(context, "get_remaining_time_in_millis"):
        configured = min(configured, context.get_remaining_time_in_millis() / 1000.0 - 5)
    return configured


def _serve_image(path, query, context):
    key, ctype = IMAGES[path]
    headers = {}
    detail = ""
    if query.get("fresh") in ("1", "true", "yes"):
        budget = _sync_render_budget(context)
        ok = False
        detail = "no time left for a render"
        if budget >= 5:
            battery = _parse_battery(query.get("batt"))
            ok, detail = _invoke_render("RequestResponse", timeout_s=budget,
                                        extra={"battery": battery} if battery is not None else None)
        headers["X-Render-Status"] = "fresh" if ok else "stale"
        if not ok:
            headers["X-Render-Error"] = _header_safe(detail)
    else:
        headers["X-Render-Status"] = "cached"

    s3 = aws_common.client("s3")
    try:
        obj = s3.get_object(Bucket=os.environ["BUCKET_NAME"], Key=key)
    except ClientError as e:
        if _is_missing(e):
            msg = "No image rendered yet"
            if detail and detail != "ok":
                msg += " - render failed: " + detail
            return _resp(404, msg, headers=headers)
        raise
    data = obj["Body"].read()
    if obj.get("LastModified"):
        headers["Last-Modified"] = obj["LastModified"].strftime("%a, %d %b %Y %H:%M:%S GMT")
    return _resp(200, base64.b64encode(data).decode("ascii"), ctype, headers, b64=True)


UPLOAD_TYPES = {
    "application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png",
    "image/webp": "webp", "image/gif": "gif", "text/plain": "txt",
    # rich text from apps' share sheets (the model reads the markup fine)
    "text/rtf": "rtf", "application/rtf": "rtf", "text/html": "html",
    "public.rtf": "rtf", "public.html": "html", "public.plain-text": "txt",
}
MAX_UPLOAD = 5 * 1024 * 1024


def _sniff_type(data, declared):
    declared = (declared or "").split(";")[0].strip().lower()
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"):
        return "image/heic"
    head = data[:200].lstrip().lower()
    if head.startswith(b"{\\rtf"):
        return "text/rtf"
    if head.startswith((b"<!doctype html", b"<html", b"<meta", b"<div", b"<p")):
        return "text/html"
    if declared in ("", "application/octet-stream"):
        try:
            data[:4096].decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass
    return declared


def _upload(event, headers, context):
    """Store an uploaded school letter in S3 and have the ingest function read it."""
    body = event.get("body") or ""
    try:
        data = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode("utf-8")
    except Exception:
        return _resp(400, "Kunne ikke lese opplastingen.")
    if not data:
        return _resp(400, "Ingen fil mottatt.")
    if len(data) > MAX_UPLOAD:
        return _resp(413, "Filen er for stor (maks 5 MB). Prøv et mindre bilde.")
    ctype = _sniff_type(data, headers.get("content-type"))
    if ctype == "image/heic":
        return _resp(415, "HEIC-bilder støttes ikke. Legg til 'Konverter bilde til JPEG' i snarveien.")
    ext = UPLOAD_TYPES.get(ctype)
    if not ext:
        return _resp(415, f"Filtypen støttes ikke ({ctype or 'ukjent'}). Send PDF, JPEG/PNG eller tekst.")

    import uuid
    key = time.strftime("inbox/%Y%m%d-%H%M%S-", time.gmtime()) + uuid.uuid4().hex[:8] + "." + ext
    bucket = os.environ["BUCKET_NAME"]
    aws_common.client("s3").put_object(Bucket=bucket, Key=key, Body=data, ContentType=ctype)

    budget = _sync_render_budget(context)
    lam = _lambda_client(max(5, budget))
    try:
        resp = lam.invoke(FunctionName=os.environ["INGEST_FUNCTION_NAME"], InvocationType="RequestResponse",
                          Payload=json.dumps({"bucket": bucket, "key": key, "content_type": ctype}).encode("utf-8"))
        result = json.loads(resp["Payload"].read() or b"{}")
    except (ClientError, BotoCoreError, ValueError) as e:
        logger.error("Ingest invoke failed: %s", e)
        return _resp(502, "Kunne ikke behandle brevet akkurat nå. Prøv igjen senere.")
    if resp.get("FunctionError"):
        logger.error("Ingest function error: %s", result)
        return _resp(500, "Feil under lesing av brevet: " + _header_safe(result.get("errorMessage", "")))
    status = 200 if result.get("ok") else 422
    return _resp(status, result.get("message") or "Ferdig.")


def _serve_status():
    s3 = aws_common.client("s3")
    try:
        obj = s3.get_object(Bucket=os.environ["BUCKET_NAME"], Key=META_KEY)
    except ClientError as e:
        if _is_missing(e):
            return _json(404, {"error": "no render yet"})
        raise
    return _resp(200, obj["Body"].read().decode("utf-8"), "application/json")


# ------------------------------------------------------------------ admin
ADMIN_PARAMS = ["ADMIN_TOKEN", "CHILDREN", "CHILDREN_SCHOOL_YEAR", "CALENDAR_FEEDS", "SPOND_EMAIL", "SPOND_PASSWORD",
                "TIBBER_TOKEN"]
FEEDS_STATE_KEY = "cache/feeds_sync.json"
LETTERS_LOG_KEY = "log/letters.json"
_admin_page = {"html": None}


def _admin_html():
    if _admin_page["html"] is None:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "admin.html"), encoding="utf-8") as f:
            _admin_page["html"] = f.read()
    return _admin_page["html"]


def _s3_json(key, default=None):
    try:
        obj = aws_common.client("s3").get_object(Bucket=os.environ["BUCKET_NAME"], Key=key)
        return json.loads(obj["Body"].read())
    except Exception:
        return default


def _admin_api(path, method, event, headers):
    import config_store
    params, _missing = aws_common.get_parameters(ADMIN_PARAMS)
    expected = params.get("ADMIN_TOKEN", "")
    if not expected:
        return _json(503, {"error": "ADMIN_TOKEN er ikke satt i Parameter Store"})
    if not _token_ok(headers.get("x-admin-token", ""), expected):
        return _json(401, {"error": "Feil eller manglende admin-nøkkel"})

    s3 = aws_common.client("s3")
    bucket = os.environ["BUCKET_NAME"]

    if path == "/api/config" and method == "GET":
        cfg = config_store.load(s3, bucket)
        if cfg is not None:
            return _json(200, {"config": cfg, "stored": True})
        cfg = config_store.bootstrap(children_spec=params.get("CHILDREN", ""),
                                     school_year=params.get("CHILDREN_SCHOOL_YEAR"),
                                     feeds_spec=params.get("CALENDAR_FEEDS", ""),
                                     design_options=os.environ.get("DESIGN_OPTIONS", ""))
        return _json(200, {"config": cfg, "stored": False})

    if path == "/api/config" and method == "PUT":
        try:
            body = event.get("body") or ""
            if event.get("isBase64Encoded"):
                body = base64.b64decode(body).decode("utf-8")
            saved = config_store.save(s3, bucket, json.loads(body))
        except config_store.ConfigError as e:
            return _json(400, {"error": str(e)})
        except ValueError:
            return _json(400, {"error": "Ugyldig JSON"})
        return _json(200, {"config": saved, "stored": True})

    if path == "/api/status" and method == "GET":
        return _json(200, {"meta": _s3_json(META_KEY, {}), "feeds": _s3_json(FEEDS_STATE_KEY, {}),
                           "frame_seen": _s3_json("cache/frame_seen.json", {}),
                           "letters": _s3_json(LETTERS_LOG_KEY, [])[-10:]})

    if path == "/api/preview" and method == "GET" and (event.get("queryStringParameters") or {}).get("date"):
        q = event.get("queryStringParameters") or {}
        result = _call_render({"action": "preview", "date": q.get("date"), "time": q.get("time") or "07:00"})
        if not result.get("png"):
            return _json(400 if "dato" in str(result.get("error", "")) else 502, result)
        return _resp(200, result["png"], "image/png", b64=True)

    if path == "/api/preview" and method == "GET":
        try:
            obj = s3.get_object(Bucket=bucket, Key=IMAGES["/image.png"][0])
        except ClientError as e:
            if _is_missing(e):
                return _json(404, {"error": "Ingen bilde ennå"})
            raise
        return _resp(200, base64.b64encode(obj["Body"].read()).decode("ascii"), "image/png", b64=True)

    if path == "/api/spond/groups" and method == "GET":
        import spond_client
        if not params.get("SPOND_EMAIL") or not params.get("SPOND_PASSWORD"):
            return _json(400, {"error": "Legg inn SPOND_EMAIL og SPOND_PASSWORD i Parameter Store først"})
        try:
            token = spond_client.login(params["SPOND_EMAIL"], params["SPOND_PASSWORD"])
            return _json(200, {"groups": spond_client.groups(token)})
        except spond_client.SpondError as e:
            return _json(502, {"error": str(e)})

    if path == "/api/tibber/test" and method == "POST":
        import tibber
        if not params.get("TIBBER_TOKEN"):
            return _json(400, {"error": "Legg inn TIBBER_TOKEN i Parameter Store først"})
        from datetime import date as _date
        try:
            data = tibber.fetch_history(params["TIBBER_TOKEN"])
            per_day = tibber.daily(data)
            homes = [h.get("appNickname") or "hjem" for h in (data.get("viewer") or {}).get("homes") or []]
            return _json(200, {"homes": homes, "days_with_data": len(per_day),
                               "first_day": min(per_day).isoformat() if per_day else None,
                               "summary": tibber.summary(per_day, _date.today()),
                               "vehicle_types": tibber.vehicle_types(params["TIBBER_TOKEN"])})
        except tibber.TibberError as e:
            return _json(502, {"error": str(e)})

    if path == "/api/spond/test" and method == "POST":
        result = _call_render({"action": "spond_test"})
        return _json(200, result)

    if path == "/api/spond/cleanup" and method in ("GET", "POST"):
        # Old events from Spond's own calendar sync: GET lists them, POST {"ids": [...]} deletes those.
        payload = {"action": "spond_cleanup", "q": str((event.get("queryStringParameters") or {}).get("q") or "")[:80]}
        if method == "POST":
            try:
                body = event.get("body") or ""
                if event.get("isBase64Encoded"):
                    body = base64.b64decode(body).decode("utf-8")
                ids = json.loads(body or "{}").get("ids") or []
            except (ValueError, AttributeError):
                return _json(400, {"error": "ugyldig JSON"})
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                return _json(400, {"error": "ids må være en liste"})
            payload["delete"] = ids
        result = _call_render(payload)
        if "error" in result:
            return _json(502, result)
        if method == "POST" and result.get("deleted"):
            _invoke_render("Event", extra={"force_feeds": True})   # our Spond sync fills the gaps
        return _json(200, result)

    if path == "/api/render" and method == "POST":
        ok, _detail = _invoke_render("Event", extra={"force_feeds": True})
        return _json(202 if ok else 502, {"status": "started" if ok else "error"})

    return _json(404, {"error": "Ukjent forespørsel"})


def handler(event, context):
    try:
        return _handle(event, context)
    except Exception as e:  # never let the Function URL turn this into a bare 502
        logger.exception("Unhandled error")
        return _resp(500, "Server error: {}".format(_header_safe(e)))


def _handle(event, context):
    event = event or {}
    http = (event.get("requestContext") or {}).get("http") or {}
    method = (http.get("method") or "GET").upper()
    path = event.get("rawPath") or http.get("path") or "/"
    query = event.get("queryStringParameters") or {}
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    if path == "/" and method == "GET":
        return _resp(200, "weekcalendar OK")

    if path == "/admin" and method == "GET":
        return _resp(200, _admin_html(), "text/html; charset=utf-8")
    if path.startswith("/api/"):
        return _admin_api(path, method, event, headers)

    known = set(IMAGES) | {"/status", "/render", "/upload"}
    if path not in known:
        return _resp(404, "Not found")

    expected = _frame_token()
    if not expected:
        logger.error("FRAME_TOKEN parameter is not configured")
        return _resp(503, "Server token not configured")

    if path == "/upload":
        if method != "POST":
            return _resp(405, "Use POST", headers={"Allow": "POST"})
        supplied = headers.get("x-run-token", "") or query.get("token", "")
        if not _token_ok(supplied, expected):
            return _resp(401, "Unauthorized")
        return _upload(event, headers, context)

    if path == "/render":
        if method != "POST":
            return _resp(405, "Use POST", headers={"Allow": "POST"})
        supplied = headers.get("x-run-token", "")
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        if not _token_ok(supplied, expected):
            return _resp(401, "Unauthorized")
        ok, _detail = _invoke_render("Event")
        if not ok:
            return _json(502, {"status": "error"})
        return _json(202, {"status": "started"})

    if method != "GET":
        return _resp(405, "Use GET", headers={"Allow": "GET"})
    if not _token_ok(query.get("token", ""), expected):
        return _resp(401, "Unauthorized")

    if path == "/status":
        return _serve_status()
    return _serve_image(path, query, context)
