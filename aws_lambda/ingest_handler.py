"""
AWS Lambda: read an uploaded school letter from S3 with Claude (Amazon Bedrock)
and write its events into the family Google Calendar.

Invoked synchronously by the serve function after POST /upload:
  event = {"bucket": ..., "key": "inbox/...", "content_type": "application/pdf"}
Returns {"ok": bool, "message": "<Norwegian summary for the iPhone Shortcut>", ...}

SSM parameters (under /weekcalendar/):
  GOOGLE_SA_JSON        service-account JSON key with access to CALENDAR_ID (SecureString)
  CALENDAR_ID           family calendar (also used by the render function)
  CHILDREN              e.g. "Amalie:6,Sigrid:3"  - grade per child ...
  CHILDREN_SCHOOL_YEAR  ... in the school year starting this year (e.g. "2026"); grades advance each August
  ANTHROPIC_API_KEY     optional: call the Claude API directly (model claude-sonnet-5-5) instead of Bedrock
  CLAUDE_MODEL          optional model id override (Bedrock ids start with "anthropic.")
"""
import json
import logging
import os
from datetime import datetime, timedelta

import aws_common

logger = logging.getLogger()
logger.setLevel(logging.INFO)

try:
    from zoneinfo import ZoneInfo
    OSLO = ZoneInfo("Europe/Oslo")
except Exception:  # pragma: no cover
    OSLO = None

PARAMS = ["GOOGLE_SA_JSON", "CALENDAR_ID", "CHILDREN", "CHILDREN_SCHOOL_YEAR", "CLAUDE_MODEL",
          "ANTHROPIC_API_KEY"]

DIRECT_MODEL = "claude-sonnet-5-5"   # Claude API (Anthropic) model id; override with CLAUDE_MODEL

_anthropic_client = None


def anthropic_client(api_key=None):
    """Claude API client when an Anthropic API key is configured, else Claude in Amazon Bedrock."""
    global _anthropic_client
    if api_key:
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)
    if _anthropic_client is None:
        from anthropic import AnthropicBedrockMantle
        _anthropic_client = AnthropicBedrockMantle(aws_region=os.environ.get("BEDROCK_REGION")
                                                   or os.environ.get("AWS_REGION", "eu-west-1"))
    return _anthropic_client


def calendar_session(sa_json):
    from school.calendar_sync import session_from_service_account
    return session_from_service_account(json.loads(sa_json))


def _fail(message, **extra):
    logger.warning("Ingest failed: %s", message)
    return {"ok": False, "message": message, **extra}


LETTERS_LOG_KEY = "log/letters.json"


def _log_letter(s3, bucket, message, key):
    """Keep the last 50 results for the admin page's status tab (best effort)."""
    import time
    try:
        try:
            log = json.loads(s3.get_object(Bucket=bucket, Key=LETTERS_LOG_KEY)["Body"].read())
        except Exception:
            log = []
        log = (log + [{"at": time.time(), "message": message, "key": key}])[-50:]
        s3.put_object(Bucket=bucket, Key=LETTERS_LOG_KEY, Body=json.dumps(log, ensure_ascii=False).encode("utf-8"),
                      ContentType="application/json")
    except Exception:
        logger.exception("Could not write letters log")


def handler(event, context):
    from school import calendar_sync, extract

    event = event or {}
    today = (datetime.now(OSLO) if OSLO else datetime.now()).date()
    params, missing = aws_common.get_parameters(PARAMS)
    s3 = aws_common.client("s3")
    cfg = None
    try:
        import config_store
        cfg = config_store.load(s3, os.environ.get("BUCKET_NAME") or event.get("bucket"))
    except Exception:
        logger.exception("Could not read config.json")
    for required in ("GOOGLE_SA_JSON", "CALENDAR_ID") + (() if cfg else ("CHILDREN",)):
        if not params.get(required):
            return _fail(f"Mangler innstillingen {required} i AWS Parameter Store.")

    obj = s3.get_object(Bucket=event["bucket"], Key=event["key"])
    data = obj["Body"].read()
    content_type = event.get("content_type") or obj.get("ContentType") or ""

    try:
        session = calendar_session(params["GOOGLE_SA_JSON"])
        existing = calendar_sync.family_events(session, params["CALENDAR_ID"],
                                               today - timedelta(days=7), today + timedelta(days=300))
    except Exception as e:
        logger.exception("Reading the calendar failed")
        return _fail(f"Kunne ikke lese Google Kalender: {e}")

    if cfg is not None:   # admin page: children, grades and groups
        import config_store
        kids = config_store.children(cfg)
        children = [(n, g) for n, g, _groups in kids]
        groups = {n: gr for n, _g, gr in kids}
        base_year = int(cfg.get("school_year") or extract.school_year_start(today))
    else:
        children = extract.parse_children(params["CHILDREN"])
        groups = {}
        try:
            base_year = int(params.get("CHILDREN_SCHOOL_YEAR") or extract.school_year_start(today))
        except ValueError:
            base_year = extract.school_year_start(today)
    kids_now = [(n, g, groups.get(n, [])) for n, g in extract.children_now(children, base_year, today)]

    try:
        api_key = params.get("ANTHROPIC_API_KEY")
        chosen = ((cfg or {}).get("ai") or {}).get("model")   # admin page: Haiku / Sonnet / Opus
        if api_key:   # Claude API directly: plain model ids, no Bedrock fallbacks
            models = [chosen or params.get("CLAUDE_MODEL") or DIRECT_MODEL]
        else:         # Claude in Amazon Bedrock: same models with the "anthropic." prefix
            first = ("anthropic." + chosen) if chosen else (params.get("CLAUDE_MODEL") or extract.MODEL)
            models = [first] + [m for m in extract.FALLBACK_MODELS if m != first]
        result = extract.call_model(anthropic_client(api_key), data, content_type, today,
                                    existing=existing, children_now=kids_now, models=models)
        grade = int(result.get("grade") or 0)
        letter_child = extract.child_for_grade(grade, children, base_year, today) if grade else None
        doc_key, items = extract.to_calendar_items(result, today,
                                                   default_for=[letter_child] if letter_child else None)
    except extract.ExtractError as e:
        return _fail(str(e))
    except Exception as e:  # model/network errors
        logger.exception("Extraction failed")
        return _fail(f"Kunne ikke lese dokumentet: {type(e).__name__}: {e}")

    known = {n for n, _ in children}
    for i in items:
        i["for"] = [n for n in i["for"] if n in known]

    def last_day(i):   # a period (ferie) counts until its last day
        return i.get("end_date") or i["date"]
    past = [i for i in items if last_day(i) < today]
    skipped = [i for i in items if last_day(i) >= today and i.get("already_in_calendar")]
    new = [i for i in items if last_day(i) >= today and not i.get("already_in_calendar")]

    scope = None
    if doc_key:
        if not letter_child:
            return _fail(f"Fant ikke hvilket barn ukebrevet gjelder (trinn: {grade or 'ukjent'}).", week=doc_key)
        scope = {"week": doc_key, "letter_child": letter_child}

    try:
        deleted, created = calendar_sync.sync_items(session, params["CALENDAR_ID"], new, scope)
    except Exception as e:
        logger.exception("Calendar sync failed")
        return _fail(f"Kunne ikke skrive til Google Kalender: {e}", week=doc_key)

    who = letter_child or ", ".join(sorted({n for i in new for n in i["for"]})) or "familien"
    what = f"uke {doc_key.split('-W')[1].lstrip('0')}" if doc_key else "fra dokumentet"
    msg = f"La til {created} hendelser for {who}, {what}" if created else f"Ingen nye hendelser {what}"
    if deleted:
        msg += f" (erstattet {deleted} fra før)"
    if skipped:
        msg += ". Fantes fra før: " + ", ".join(f"{i['title']} ({i['date'].strftime('%d.%m')})" for i in skipped)
    if past:
        msg += ". Allerede passert: " + ", ".join(f"{i['title']} ({i['date'].strftime('%d.%m.%Y')})" for i in past)
    logger.info("Ingest %s: %s | %s", event.get("key"), msg,
                "; ".join(f"{i['date']}: {i['title']}" for i in new))
    _log_letter(s3, event.get("bucket"), msg, event.get("key"))
    question = (result.get("dinner_question") or "").strip()
    if doc_key and question:       # shown on the frame in the evening that week
        try:
            s3.put_object(Bucket=event.get("bucket"), Key="log/dinner.json",
                          Body=json.dumps({"week": doc_key, "question": question[:200]}, ensure_ascii=False)
                          .encode("utf-8"), ContentType="application/json")
        except Exception:
            logger.exception("Could not store the dinner question")
    return {"ok": True, "message": msg, "week": doc_key, "child": letter_child, "model": models[0],
            "created": created, "deleted": deleted, "skipped": len(skipped), "past": len(past),
            "items": [{"date": i["date"].isoformat(), "title": i["title"], "start": i["start"],
                       "for": i["for"]} for i in new]}
