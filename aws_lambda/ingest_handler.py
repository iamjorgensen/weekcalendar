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

PARAMS = ["GOOGLE_SA_JSON", "CALENDAR_ID", "CHILDREN", "CHILDREN_SCHOOL_YEAR"]

_anthropic_client = None


def anthropic_client():
    global _anthropic_client
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


def handler(event, context):
    from school import calendar_sync, extract

    event = event or {}
    today = (datetime.now(OSLO) if OSLO else datetime.now()).date()
    params, missing = aws_common.get_parameters(PARAMS)
    for required in ("GOOGLE_SA_JSON", "CALENDAR_ID", "CHILDREN"):
        if not params.get(required):
            return _fail(f"Mangler innstillingen {required} i AWS Parameter Store.")

    s3 = aws_common.client("s3")
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

    children = extract.parse_children(params["CHILDREN"])
    try:
        base_year = int(params.get("CHILDREN_SCHOOL_YEAR") or extract.school_year_start(today))
    except ValueError:
        base_year = extract.school_year_start(today)
    kids_now = extract.children_now(children, base_year, today)

    try:
        result = extract.call_model(anthropic_client(), data, content_type, today,
                                    existing=existing, children_now=kids_now)
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

    past = [i for i in items if i["date"] < today]
    skipped = [i for i in items if i["date"] >= today and i.get("already_in_calendar")]
    new = [i for i in items if i["date"] >= today and not i.get("already_in_calendar")]

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
    return {"ok": True, "message": msg, "week": doc_key, "child": letter_child,
            "created": created, "deleted": deleted, "skipped": len(skipped), "past": len(past),
            "items": [{"date": i["date"].isoformat(), "title": i["title"], "start": i["start"],
                       "for": i["for"]} for i in new]}
