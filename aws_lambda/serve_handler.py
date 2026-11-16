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


def _invoke_render(invocation_type, timeout_s=None):
    """Invoke the render function. Returns (ok, detail)."""
    name = os.environ["RENDER_FUNCTION_NAME"]
    payload = json.dumps({"source": "serve-fresh" if invocation_type == "RequestResponse" else "serve-post"})
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
            ok, detail = _invoke_render("RequestResponse", timeout_s=budget)
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


def _serve_status():
    s3 = aws_common.client("s3")
    try:
        obj = s3.get_object(Bucket=os.environ["BUCKET_NAME"], Key=META_KEY)
    except ClientError as e:
        if _is_missing(e):
            return _json(404, {"error": "no render yet"})
        raise
    return _resp(200, obj["Body"].read().decode("utf-8"), "application/json")


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

    known = set(IMAGES) | {"/status", "/render"}
    if path not in known:
        return _resp(404, "Not found")

    expected = _frame_token()
    if not expected:
        logger.error("FRAME_TOKEN parameter is not configured")
        return _resp(503, "Server token not configured")

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
