"""
Daily check that the frame is alive (scheduled, 12:00 Oslo time).

- The frame has not fetched a picture for more than STALE_HOURS: battery flat or Wi-Fi gone.
- The battery reported by the frame is below LOW_BATTERY.

Alerts go as a push notification through ntfy (https://ntfy.sh): install the ntfy app,
subscribe to a long random topic name, and store that name as the SSM parameter
NTFY_TOPIC. Each problem is reported once (battery at most every 3 days).
"""
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import aws_common

logger = logging.getLogger()
logger.setLevel(logging.INFO)

FRAME_SEEN_KEY = "cache/frame_seen.json"
STATE_KEY = "cache/watchdog.json"
STALE_HOURS = 26
LOW_BATTERY = 15
BATTERY_REPEAT_S = 3 * 86400


def _read(s3, bucket, key):
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    except Exception:
        return {}


def push(topic, title, message, server="https://ntfy.sh"):
    req = urllib.request.Request(f"{server}/{urllib.parse.quote(topic)}", data=message.encode("utf-8"),
                                 method="POST", headers={"Title": title.encode("utf-8").decode("latin-1", "ignore"),
                                                         "Tags": "warning", "Priority": "default"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def check(seen, state, now):
    """-> (alerts [(title, message)], new_state). Pure, for tests."""
    alerts, state = [], dict(state or {})
    at = seen.get("at")
    if at:
        age_h = (now - at) / 3600
        if age_h > STALE_HOURS and state.get("stale_for") != at:
            when = datetime.fromtimestamp(at, timezone.utc).astimezone(_oslo()).strftime("%d.%m kl %H:%M")
            alerts.append(("Ukekalenderen har ikke oppdatert seg",
                           f"Rammen hentet sist bilde {when}. Sjekk batteriet og Wi-Fi."))
            state["stale_for"] = at
    batt = seen.get("battery")
    if isinstance(batt, int) and batt < LOW_BATTERY and now - state.get("battery_at", 0) > BATTERY_REPEAT_S:
        alerts.append(("Bytt batteri i ukekalenderen", f"Batteriet er på {batt} %."))
        state["battery_at"] = now
    return alerts, state


def _oslo():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Oslo")
    except Exception:
        return timezone.utc


def handler(event, context):
    bucket = os.environ["BUCKET_NAME"]
    s3 = aws_common.client("s3")
    alerts, state = check(_read(s3, bucket, FRAME_SEEN_KEY), _read(s3, bucket, STATE_KEY), time.time())
    if not alerts:
        return {"ok": True, "alerts": 0}
    params, _missing = aws_common.get_parameters(["NTFY_TOPIC"])
    topic = params.get("NTFY_TOPIC")
    sent = 0
    for title, msg in alerts:
        logger.warning("Watchdog: %s - %s", title, msg)
        if topic:
            try:
                push(topic, title, msg)
                sent += 1
            except Exception as e:
                logger.error("ntfy push failed: %s", e)
    s3.put_object(Bucket=bucket, Key=STATE_KEY, Body=json.dumps(state).encode("utf-8"),
                  ContentType="application/json")
    return {"ok": True, "alerts": len(alerts), "sent": sent}
