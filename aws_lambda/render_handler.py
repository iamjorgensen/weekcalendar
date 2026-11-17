"""
AWS Lambda: render the week calendar and publish it to S3.

Flow per invocation:
  1. Point all caches at /tmp (the only writable path on Lambda).
  2. Load config/secrets from SSM Parameter Store into os.environ. This must
     happen BEFORE data_provider / mappings are imported: they read their
     configuration from the environment at import time.
  3. Restore caches (AI icon cache, mappings cache, downloaded icons) from S3.
  4. Fetch data, render with the same options as main.py (the Pi path).
  5. Upload latest/output.png, latest/output.jpg and latest/meta.json.
  6. Save the caches back to S3.

The app modules are wrapped, not modified.
"""

import importlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from botocore.exceptions import BotoCoreError, ClientError

import aws_common

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

WIDTH, HEIGHT = 800, 480

PNG_KEY = "latest/output.png"
JPG_KEY = "latest/output.jpg"
META_KEY = "latest/meta.json"
CACHE_PREFIX = "cache/"

_app = None  # (main, data_provider, mappings) once imported in this container


def work_dir():
    return os.environ.get("WORK_DIR", "/tmp/weekcalendar")


def configure_paths():
    """Default every cache path to a writable location under WORK_DIR."""
    wd = work_dir()
    os.environ.setdefault("GS_CACHE_PATH", os.path.join(wd, "cache", "event_mappings_cache.json"))
    os.environ.setdefault("AI_ICON_CACHE_PATH", os.path.join(wd, "cache", "ai_icon_cache.json"))
    os.environ.setdefault("ICONS_CACHE_DIR", os.path.join(wd, "icons"))
    for d in (os.path.dirname(os.environ["GS_CACHE_PATH"]),
              os.path.dirname(os.environ["AI_ICON_CACHE_PATH"]),
              os.environ["ICONS_CACHE_DIR"],
              os.path.join(wd, "out")):
        os.makedirs(d, exist_ok=True)


def load_config():
    configure_paths()
    return aws_common.load_params_into_env(aws_common.DATA_PARAM_NAMES)


def import_app():
    """Import the app modules (once per container). Call load_config() first."""
    global _app
    if _app is None:
        # Make the app modules importable when running from a source checkout (tests).
        root = os.environ.get("APP_ROOT")
        if root and root not in sys.path:
            sys.path.insert(0, root)
        data_provider = importlib.import_module("data_provider")
        mappings = importlib.import_module("mappings")
        main = importlib.import_module("main")  # builds IconManager + render opts
        _app = (main, data_provider, mappings)
        return _app, True
    return _app, False


# --- S3 cache sync -----------------------------------------------------------

def _cache_files():
    """(local path, s3 key) pairs for the single-file caches."""
    return [
        (os.environ["AI_ICON_CACHE_PATH"], CACHE_PREFIX + "ai_icon_cache.json"),
        (os.environ["GS_CACHE_PATH"], CACHE_PREFIX + "event_mappings_cache.json"),
    ]


def _is_missing(err):
    code = err.response.get("Error", {}).get("Code", "")
    return code in ("NoSuchKey", "404", "NotFound", "AccessDenied")


def restore_caches(s3, bucket):
    """Download caches from S3. Returns the set of icon file names already in S3."""
    for path, key in _cache_files():
        try:
            s3.download_file(bucket, key, path)
        except ClientError as e:
            if not _is_missing(e):
                logger.warning("Could not restore %s: %s", key, e)
        except BotoCoreError as e:
            logger.warning("Could not restore %s: %s", key, e)

    icons_dir = os.environ["ICONS_CACHE_DIR"]
    known = set()
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=CACHE_PREFIX + "icons/"):
            for obj in page.get("Contents", []):
                name = obj["Key"].rsplit("/", 1)[-1]
                if not name.lower().endswith((".svg", ".png")):
                    continue
                known.add(name)
                target = os.path.join(icons_dir, name)
                if not os.path.exists(target):
                    s3.download_file(bucket, obj["Key"], target)
    except (ClientError, BotoCoreError) as e:
        logger.warning("Could not restore icon cache: %s", e)
    return known


def save_caches(s3, bucket, known_icons):
    for path, key in _cache_files():
        if os.path.exists(path):
            try:
                s3.upload_file(path, bucket, key)
            except (ClientError, BotoCoreError) as e:
                logger.warning("Could not save %s: %s", key, e)
    icons_dir = os.environ["ICONS_CACHE_DIR"]
    for name in sorted(os.listdir(icons_dir)):
        if name in known_icons or not name.lower().endswith((".svg", ".png")):
            continue
        try:
            s3.upload_file(os.path.join(icons_dir, name), bucket, CACHE_PREFIX + "icons/" + name)
        except (ClientError, BotoCoreError) as e:
            logger.warning("Could not save icon %s: %s", name, e)


# --- render ------------------------------------------------------------------

def fetch_data(data_provider, days):
    return data_provider.initial_fetch_all(days=days)


def last_known_battery(s3, bucket):
    """Battery % reported by the frame on an earlier render (from meta.json), or None."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=META_KEY)
        b = json.loads(obj["Body"].read()).get("battery")
        return b if isinstance(b, int) and 0 <= b <= 100 else None
    except Exception:
        return None


def render(main, mappings, data, days, errors):
    opts = dict(main.opts)
    opts["days"] = days
    # main.opts captured EVENT_MAPPINGS at import; use the current list
    opts["event_mappings"] = mappings.EVENT_MAPPINGS
    try:
        img = main._try_render_calendar(data, opts, width=WIDTH, height=HEIGHT, days=days)
    except Exception as e:
        logger.exception("Primary render failed; rendering empty calendar")
        errors.append(f"render: {e}")
        img = main._try_render_calendar({}, opts, width=WIDTH, height=HEIGHT, days=days)
    if isinstance(img, (list, tuple)):
        img = img[0]
    if not hasattr(img, "convert"):
        raise RuntimeError("render_calendar did not return an image")
    return img


FEEDS_STATE_KEY = CACHE_PREFIX + "feeds_sync.json"
# Bump when the way feed events are written changes, so the next render re-syncs
# (and corrects existing events) instead of waiting for FEED_SYNC_HOURS.
FEEDS_CODE_VERSION = "7"   # 4: Spond
FEED_SYNC_HOURS = float(os.environ.get("FEED_SYNC_HOURS", "6"))


def sync_calendar_feeds(s3, bucket, errors, force=False, cfg=None):
    """
    Copy subscribed calendar feeds (CALENDAR_FEEDS) into the family calendar, at most
    every FEED_SYNC_HOURS (or when the config changed). Never fails the render.
    Returns a short status dict for meta.json, or None when nothing was done.
    """
    import hashlib
    params, _missing = aws_common.get_parameters(["CALENDAR_FEEDS", "GOOGLE_SA_JSON", "CALENDAR_ID",
                                                  "SPOND_EMAIL", "SPOND_PASSWORD"])
    spond_cfg = (cfg or {}).get("spond") or {}
    spond_groups = [g for g in spond_cfg.get("groups", []) if g.get("on")] if spond_cfg.get("on") else []
    if cfg is not None:
        import config_store
        spec = config_store.feeds_spec(cfg)      # the admin page's feeds
    else:
        spec = params.get("CALENDAR_FEEDS") or ""
    if not spec.strip() and not spond_groups:
        return None
    if not params.get("GOOGLE_SA_JSON") or not params.get("CALENDAR_ID"):
        errors.append("feeds: GOOGLE_SA_JSON/CALENDAR_ID mangler")
        return None
    spec_hash = hashlib.sha1((FEEDS_CODE_VERSION + "\n" + spec + "\n" +
                              json.dumps(spond_groups, sort_keys=True)).encode("utf-8")).hexdigest()
    state = {}
    try:
        state = json.loads(s3.get_object(Bucket=bucket, Key=FEEDS_STATE_KEY)["Body"].read())
    except Exception:
        pass
    if not force and state.get("spec") == spec_hash and time.time() - state.get("at", 0) < FEED_SYNC_HOURS * 3600:
        return {"skipped": "synced recently"}

    import requests
    from school import feeds
    from school.calendar_sync import session_from_service_account
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Europe/Oslo")).date()
    except Exception:
        today = datetime.now().date()

    result = {}
    try:
        session = session_from_service_account(json.loads(params["GOOGLE_SA_JSON"]))
    except Exception as e:
        errors.append(f"feeds: {e}")
        return None
    for url, names, icon in feeds.parse_feeds(spec):
        fid = feeds.feed_id(url)
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "weekcalendar/1.0"})
            r.raise_for_status()
            result[fid] = feeds.sync_feed(session, params["CALENDAR_ID"], r.text, names, fid, today, icon=icon)
            result[fid]["name"] = url.split("//", 1)[-1].split("/", 1)[0]
        except Exception as e:
            logger.exception("Feed sync failed for %s", fid)
            errors.append(f"feed {fid}: {e}")
            result[fid] = {"name": url.split("//", 1)[-1].split("/", 1)[0], "error": str(e)[:300]}
    if spond_groups:
        import spond_client
        try:
            if not params.get("SPOND_EMAIL") or not params.get("SPOND_PASSWORD"):
                raise spond_client.SpondError("SPOND_EMAIL/SPOND_PASSWORD mangler i Parameter Store")
            token = spond_client.login(params["SPOND_EMAIL"], params["SPOND_PASSWORD"])
            mine = None
            for g in spond_groups:
                fid = "spond-" + g["id"][:16]
                try:
                    raw = spond_client.events(token, g["id"])
                    if g.get("only_accepted"):   # only events one of us has said yes to
                        if mine is None:
                            mine = spond_client.my_member_ids(token)
                        if not mine:   # never wipe a group because we could not tell who "we" are
                            raise spond_client.SpondError("fant ikke deg eller barna som medlem i gruppene")
                        raw = [e for e in raw if spond_client.accepted(e, mine)]
                    evs = spond_client.to_feed_events(raw, g.get("name", ""))
                    result[fid] = feeds.sync_events(session, params["CALENDAR_ID"], evs, g.get("tags", []), fid,
                                                    today, days_ahead=90, icon=g.get("icon", ""))
                    result[fid].update({"name": "Spond: " + (g.get("name") or ""), "found": len(evs)})
                except Exception as e:
                    logger.exception("Spond group sync failed")
                    errors.append(f"spond {g.get('name')}: {e}")
                    result[fid] = {"name": "Spond: " + (g.get("name") or ""), "error": str(e)[:300]}
        except Exception as e:
            errors.append(f"spond: {e}")
            result["spond"] = {"name": "Spond", "error": str(e)[:300]}
    try:
        s3.put_object(Bucket=bucket, Key=FEEDS_STATE_KEY,
                      Body=json.dumps({"at": time.time(), "spec": spec_hash, "result": result}).encode("utf-8"))
    except Exception:
        pass
    return result


DINNER_KEY = "log/dinner.json"


def dinner_question(s3, bucket):
    """The weekly letter's 'Middagssamtalen' question, if it is for this week."""
    try:
        d = json.loads(s3.get_object(Bucket=bucket, Key=DINNER_KEY)["Body"].read())
        y, w, _ = datetime.now(timezone.utc).isocalendar()
        return d.get("question", "") if d.get("week") == f"{y}-W{w:02d}" else ""
    except Exception:
        return ""


def spond_test():
    """Run the Spond part of the feed sync now and report what happened (admin 'Test Spond nå')."""
    bucket = os.environ["BUCKET_NAME"]
    s3 = aws_common.client("s3")
    import config_store
    cfg = config_store.load(s3, bucket)
    if cfg is None:
        return {"error": "Innstillingene fra admin-siden er ikke lagret ennå (trykk «Lagre endringer»)"}
    sp = cfg.get("spond") or {}
    report = {"spond_on": bool(sp.get("on")),
              "groups_on": [g.get("name") for g in sp.get("groups", []) if g.get("on")]}
    if not report["spond_on"] or not report["groups_on"]:
        report["error"] = "«Hent fra Spond» eller ingen grupper er slått på i de lagrede innstillingene"
        return report
    errors = []
    try:
        res = sync_calendar_feeds(s3, bucket, errors, force=True, cfg=cfg) or {}
    except Exception as e:
        logger.exception("Spond test crashed")
        errors.append(f"{type(e).__name__}: {e}")
        res = {}
    report["result"] = {k: v for k, v in res.items() if k.startswith("spond")}
    report["errors"] = errors
    return report


def spond_cleanup(event):
    """
    Old events from Spond's own calendar sync in the family calendar.
    {"action": "spond_cleanup"} lists them; add "delete": [ids] to delete those
    (only ids the listing would return). Range: a year back to a year ahead.
    """
    from school import feeds
    from school.calendar_sync import session_from_service_account
    params, _missing = aws_common.get_parameters(["GOOGLE_SA_JSON", "CALENDAR_ID"])
    if not params.get("GOOGLE_SA_JSON") or not params.get("CALENDAR_ID"):
        return {"error": "GOOGLE_SA_JSON/CALENDAR_ID mangler"}
    session = session_from_service_account(json.loads(params["GOOGLE_SA_JSON"]))
    today = datetime.now(timezone.utc).date()
    q = str(event.get("q") or "").strip()[:80]
    if q and len(q) < 3:
        return {"error": "Søk med minst 3 tegn"}
    found = feeds.find_foreign(session, params["CALENDAR_ID"], today - timedelta(days=365),
                               today + timedelta(days=365), title=q)
    ids = event.get("delete")
    if ids:
        n = feeds.delete_ids(session, params["CALENDAR_ID"], ids, {e["id"] for e in found})
        return {"deleted": n}
    return {"events": found}


def handler(event, context):
    t0 = time.time()
    event = event or {}
    if event.get("action") == "spond_cleanup":
        return spond_cleanup(event)
    if event.get("action") == "spond_test":
        return spond_test()
    bucket = os.environ["BUCKET_NAME"]
    days = int(os.environ.get("RENDER_DAYS", "7"))
    errors = []

    missing = load_config()
    s3 = aws_common.client("s3")
    known_icons = restore_caches(s3, bucket)

    # Settings from the admin page (config/config.json). Until it has been saved
    # once, the Google Sheet + Parameter Store are used as before.
    cfg = None
    try:
        import config_store
        cfg = config_store.load(s3, bucket)
    except Exception as e:
        logger.exception("Could not read config.json")
        errors.append(f"config: {e}")
    if cfg is not None:
        view = cfg.get("view") or {}
        os.environ["DESIGN_OPTIONS"] = "+".join((view.get("options") or [])
                                                + (["moments"] if view.get("moments", True) else []))
        os.environ["EVENING_HOUR"] = str(view.get("evening_hour", 17))
        days = int(view.get("days") or days)

    # Subscribed calendars (e.g. the national team's fixtures) go into the family
    # calendar before we read it, so new matches show up in this same render.
    feeds_status = None
    try:
        feeds_status = sync_calendar_feeds(s3, bucket, errors, force=bool(event.get("force_feeds")), cfg=cfg)
    except Exception as e:
        logger.exception("Feed sync crashed")
        errors.append(f"feeds: {e}")

    (main, data_provider, mappings), first_import = import_app()
    if cfg is not None:
        # Tags and icons from the admin page replace the Google Sheet
        import config_store
        mappings.EVENT_MAPPINGS = config_store.event_mappings(cfg)
        mappings.EVENT_MAPPINGS_SOURCE = "config"
    elif not first_import:
        # Warm container: mappings were loaded at the first import; refresh them.
        try:
            mappings.reload_event_mappings()
        except Exception as e:
            errors.append(f"mappings: {e}")

    try:
        data = fetch_data(data_provider, days) or {}
    except Exception as e:
        logger.exception("Data fetch failed")
        errors.append(f"fetch: {e}")
        data = {}

    if cfg is not None:      # birthdays for the banner, this week's dinner question
        import config_store
        data["people"] = config_store.people_for_design(cfg)
    data["dinner_question"] = dinner_question(s3, bucket)

    battery = event.get("battery")
    if not isinstance(battery, int) or not 0 <= battery <= 100:
        battery = last_known_battery(s3, bucket)  # e.g. a POST /render or a schedule run
    data["battery"] = battery

    img = render(main, mappings, data, days, errors)

    out_dir = os.path.join(work_dir(), "out")
    png_path = main.save_png(img, out_path=os.path.join(out_dir, "output.png"))
    jpg_path = main.save_jpeg_fast(img, out_path=os.path.join(out_dir, "output.jpg"))

    common = {"CacheControl": "no-store"}
    s3.upload_file(str(png_path), bucket, PNG_KEY, ExtraArgs={"ContentType": "image/png", **common})
    s3.upload_file(str(jpg_path), bucket, JPG_KEY, ExtraArgs={"ContentType": "image/jpeg", **common})

    meta = {
        "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trigger": event.get("source", "unknown"),
        "days": days,
        "event_count": len(data.get("events") or []),
        "weather_days": len(data.get("weather") or []),
        "png_bytes": os.path.getsize(png_path),
        "jpg_bytes": os.path.getsize(jpg_path),
        "duration_s": round(time.time() - t0, 2),
        "missing_params": sorted(missing),
        "errors": errors,
        "battery": battery,
        "feeds": feeds_status,
        "config": "admin" if cfg is not None else "sheet",
    }
    s3.put_object(Bucket=bucket, Key=META_KEY, Body=json.dumps(meta, indent=1).encode("utf-8"),
                  ContentType="application/json", CacheControl="no-store")

    save_caches(s3, bucket, known_icons)
    logger.info("Render done: %s", json.dumps(meta))
    return {"ok": True, **meta}
