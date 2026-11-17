"""
One settings file for the whole system: s3://<bucket>/config/config.json.
Edited in the admin page; read by the render (tags/icons, design, feeds) and
the school-letter reader (children, grades, groups).

stdlib + boto3 only (used by the small serve function too).

Shape:
{
  "version": 1,
  "school_year": 2026,                 # grades below are for the school year starting this year
  "people": [{"name": "Sigrid", "letter": "S", "color": "RED", "kind": "barn",
              "grade": 3, "groups": ["Sild"], "words": ["sigrid", "s:"]}],
  "rules":  [{"word": "Movar:", "icon": "trash", "tag": "", "remove": true}],
  "feeds":  [{"name": "Herrelandslaget", "url": "https://...ics", "tags": ["Christian"],
              "icon": "soccer", "on": true}],
  "view":   {"options": ["collapse", "month", ...], "evening_hour": 17, "days": 14}
}
"""
import csv
import io
import json
import re
import time
import urllib.request

CONFIG_KEY = "config/config.json"
HISTORY_PREFIX = "config/history/"
COLORS = ["BLACK", "RED", "GREEN", "BLUE", "YELLOW"]
KINDS = ["barn", "voksen", ""]
VIEW_OPTIONS = ["collapse", "month", "month_right", "month_column", "husk", "upcoming", "weather5",
                "tomorrow", "evening", "advice", "morning"]
AI_MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
DEFAULT_AI = {"model": "claude-sonnet-5-5"}
DEFAULT_VIEW = {"options": ["collapse", "month_column", "upcoming", "tomorrow", "evening", "advice"],
                "evening_hour": 17, "days": 14}

SHEET_CSV_URL = ("https://docs.google.com/spreadsheets/d/e/2PACX-1vTYL3NSfO_r0l9HItyeakQjkqC00XVTgoXrmHgGcSS3HAT_"
                 "cGGkPmCMibmVKizL33m585mmlHVV0rOV/pub?output=csv")


class ConfigError(ValueError):
    pass


# ------------------------------------------------------------------ S3
def load(s3, bucket):
    """The stored config, or None if there is none yet."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=CONFIG_KEY)
    except Exception as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "AccessDenied", "403"):
            return None
        raise
    return json.loads(obj["Body"].read())


def save(s3, bucket, config):
    """Validate, keep a timestamped copy of the previous version, store."""
    config = validate(config)
    prev = load(s3, bucket)
    if prev is not None:
        s3.put_object(Bucket=bucket, Key=f"{HISTORY_PREFIX}{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}.json",
                      Body=json.dumps(prev, ensure_ascii=False).encode("utf-8"), ContentType="application/json")
    s3.put_object(Bucket=bucket, Key=CONFIG_KEY, Body=json.dumps(config, ensure_ascii=False, indent=1).encode("utf-8"),
                  ContentType="application/json", CacheControl="no-store")
    return config


# ------------------------------------------------------------------ validation
def _s(v, maxlen=200):
    return str(v if v is not None else "").strip()[:maxlen]


def validate(cfg):
    if not isinstance(cfg, dict):
        raise ConfigError("config må være et objekt")
    out = {"version": 1}
    try:
        out["school_year"] = int(cfg.get("school_year") or time.gmtime().tm_year)
    except (TypeError, ValueError):
        raise ConfigError("school_year må være et årstall")

    people, names = [], set()
    for p in cfg.get("people") or []:
        name = _s(p.get("name"), 40)
        if not name:
            continue
        if name.lower() in names:
            raise ConfigError(f"Navnet {name} finnes to ganger")
        names.add(name.lower())
        color = _s(p.get("color")).upper() or "BLACK"
        if color not in COLORS:
            raise ConfigError(f"Ugyldig farge for {name}: {color}")
        grade = p.get("grade")
        if grade in ("", None):
            grade = None
        else:
            try:
                grade = int(grade)
            except (TypeError, ValueError):
                raise ConfigError(f"Ugyldig trinn for {name}")
            if not 1 <= grade <= 13:
                raise ConfigError(f"Trinn for {name} må være 1–13")
        kind = _s(p.get("kind")).lower()
        people.append({
            "name": name,
            "letter": (_s(p.get("letter"), 2) or name[0]).upper(),
            "color": color,
            "kind": kind if kind in KINDS else "",
            "grade": grade,
            "groups": [g for g in (_s(x, 40) for x in p.get("groups") or []) if g],
            "words": [w for w in (_s(x, 60) for x in p.get("words") or []) if w],
        })
    out["people"] = people

    rules = []
    for r in cfg.get("rules") or []:
        word = _s(r.get("word"), 60)
        if not word:
            continue
        tag = _s(r.get("tag"), 40)
        if tag and tag.lower() not in names:
            raise ConfigError(f"Regelen «{word}» merker {tag}, som ikke finnes i Familie")
        icon = _s(r.get("icon"), 60)
        if icon and not re.fullmatch(r"[a-z0-9_-]+", icon):
            raise ConfigError(f"Ugyldig ikonnavn «{icon}» (små bokstaver, tall og bindestrek)")
        rules.append({"word": word, "icon": icon, "tag": tag, "remove": bool(r.get("remove"))})
    out["rules"] = rules

    feeds = []
    for f in cfg.get("feeds") or []:
        url = _s(f.get("url"), 500)
        if not url:
            continue
        if not re.match(r"^(https?|webcal)://", url, re.I):
            raise ConfigError(f"Kalenderadressen må starte med https:// eller webcal:// ({url[:40]})")
        tags = [t for t in (_s(x, 40) for x in f.get("tags") or []) if t]
        for t in tags:
            if t.lower() not in names:
                raise ConfigError(f"Kalenderen «{_s(f.get('name'))}» merker {t}, som ikke finnes i Familie")
        icon = _s(f.get("icon"), 60)
        if icon and not re.fullmatch(r"[a-z0-9_-]+", icon):
            raise ConfigError(f"Ugyldig ikonnavn «{icon}»")
        feeds.append({"name": _s(f.get("name"), 80) or url[:60], "url": url, "tags": tags,
                      "icon": icon, "on": f.get("on", True) is not False})
    out["feeds"] = feeds

    sp = cfg.get("spond") or {}
    sgroups = []
    for g in sp.get("groups") or []:
        gid = _s(g.get("id"), 80)
        if not gid:
            continue
        tags = [t for t in (_s(x, 40) for x in g.get("tags") or []) if t]
        for t in tags:
            if t.lower() not in names:
                raise ConfigError(f"Spond-gruppen «{_s(g.get('name'))}» merker {t}, som ikke finnes i Familie")
        icon = _s(g.get("icon"), 60)
        if icon and not re.fullmatch(r"[a-z0-9_-]+", icon):
            raise ConfigError(f"Ugyldig ikonnavn «{icon}»")
        sgroups.append({"id": gid, "name": _s(g.get("name"), 80) or gid, "tags": tags, "icon": icon,
                        "on": g.get("on", True) is not False})
    out["spond"] = {"on": bool(sp.get("on")), "groups": sgroups}

    model = _s((cfg.get("ai") or {}).get("model")) or DEFAULT_AI["model"]
    if model not in AI_MODELS:
        raise ConfigError(f"Ukjent AI-modell: {model}")
    out["ai"] = {"model": model}

    v = cfg.get("view") or {}
    try:
        hour = int(v.get("evening_hour", DEFAULT_VIEW["evening_hour"]))
        days = int(v.get("days", DEFAULT_VIEW["days"]))
    except (TypeError, ValueError):
        raise ConfigError("Ugyldig visningsinnstilling")
    out["view"] = {
        "options": [o for o in v.get("options", DEFAULT_VIEW["options"]) if o in VIEW_OPTIONS],
        "evening_hour": min(23, max(12, hour)),
        "days": min(21, max(3, days)),
    }
    return out


# ------------------------------------------------------------------ bootstrap
def _fetch_sheet_rows(url=SHEET_CSV_URL, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "weekcalendar/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def bootstrap(sheet_rows=None, children_spec="", school_year=None, feeds_spec="", design_options=""):
    """Build a first config from today's sources (Google Sheet rows, SSM values)."""
    if sheet_rows is None:
        try:
            sheet_rows = _fetch_sheet_rows()
        except Exception:
            sheet_rows = []
    grades = {}
    for part in (children_spec or "").split(","):
        if ":" in part:
            n, g = part.split(":", 1)
            try:
                grades[n.strip().lower()] = int(g)
            except ValueError:
                pass

    # 1) people: rows that only tag (no icon) with a short letter
    people = {}   # letter -> person
    order = []
    for r in sheet_rows:
        kw, icon, rep = (r.get("keyword") or "").strip(), (r.get("icon") or "").strip(), (r.get("replacement") or "").strip()
        color = (r.get("color") or "").strip().upper()
        if icon or not rep or len(rep) > 2 or color not in COLORS:
            continue
        p = people.get(rep.upper())
        if p is None:
            p = {"name": "", "letter": rep.upper(), "color": color, "kind": "", "grade": None, "groups": [], "words": []}
            people[rep.upper()] = p
            order.append(rep.upper())
        p["words"].append(kw)
        if not p["name"] and re.fullmatch(r"[A-Za-zÆØÅæøå]{3,}", kw):
            p["name"] = kw.capitalize()
    for p in people.values():
        p["name"] = p["name"] or p["letter"]
        g = grades.get(p["name"].lower())
        if g:
            p["grade"], p["kind"] = g, "barn"

    by_letter = {p["letter"]: p for p in people.values()}
    # 2) rules: everything else
    rules = []
    for r in sheet_rows:
        kw, icon, rep = (r.get("keyword") or "").strip(), (r.get("icon") or "").strip(), (r.get("replacement") or "").strip()
        mode = (r.get("mode") or "").strip()
        color = (r.get("color") or "").strip().upper()
        if not kw or (not icon and rep and len(rep) <= 2 and color in COLORS):
            continue   # a person word, handled above
        tag = ""
        if rep and rep.upper() in by_letter:
            tag = by_letter[rep.upper()]["name"]
        rules.append({"word": kw, "icon": re.sub(r"[^a-z0-9_-]", "", icon.lower()), "tag": tag,
                      "remove": mode.startswith("replace_")})

    feeds = []
    for line in (feeds_spec or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if not parts[0] or parts[0].startswith("#"):
            continue
        tags = [t for t in (parts[1].split() if len(parts) > 1 else []) if t.lower() in {p["name"].lower() for p in people.values()}]
        icon = parts[2] if len(parts) > 2 else ("soccer" if "fotmob.com" in parts[0] else "")
        name = "Herrelandslaget (fotball)" if "fotmob.com" in parts[0] and "8492" in parts[0] else parts[0].split("/")[2]
        feeds.append({"name": name, "url": parts[0], "tags": tags, "icon": icon, "on": True})

    opts = [o for o in re.split(r"[+, ]+", design_options or "") if o in VIEW_OPTIONS] or DEFAULT_VIEW["options"]
    cfg = {
        "version": 1,
        "school_year": int(school_year or time.gmtime().tm_year),
        "people": [people[k] for k in order],
        "rules": rules,
        "feeds": feeds,
        "view": dict(DEFAULT_VIEW, options=opts),
    }
    return validate(cfg)


# ------------------------------------------------------------------ consumers
def event_mappings(cfg):
    """Config -> rows in the mappings.py / Google Sheet format (keyword, icon, replacement, mode, color)."""
    people = {p["name"].lower(): p for p in cfg.get("people", [])}
    rows = []
    for p in cfg.get("people", []):
        for w in p.get("words", []):
            rows.append({"keyword": w, "icon": "", "replacement": p["letter"], "mode": "replace_text",
                         "color": p["color"], "match_type": "contains", "size_px": 18})
    for r in cfg.get("rules", []):
        p = people.get((r.get("tag") or "").lower())
        icon, remove = r.get("icon", ""), r.get("remove", False)
        if icon and p:
            mode = "replace_all" if remove else "add_all"
        elif icon:
            mode = "replace_icon" if remove else "add_icon"
        elif p:
            mode = "replace_text" if remove else "add_all"
        else:
            mode = "replace_text" if remove else "add_icon"
        rows.append({"keyword": r["word"], "icon": icon, "replacement": p["letter"] if p else "", "mode": mode,
                     "color": p["color"] if p else "", "match_type": "contains", "size_px": 18})
    # Longest keywords first, so "G16 IK" wins over "IK"
    return sorted(rows, key=lambda x: -len(x["keyword"]))


def feeds_spec(cfg):
    """Config feeds -> the 'url | names | icon' lines feeds.parse_feeds() reads."""
    return "\n".join(f"{f['url']} | {' '.join(f.get('tags', []))} | {f.get('icon', '')}"
                     for f in cfg.get("feeds", []) if f.get("on", True))


def children(cfg):
    """[(name, grade, groups)] for people with a grade (school-letter reader)."""
    return [(p["name"], p["grade"], p.get("groups", [])) for p in cfg.get("people", []) if p.get("grade")]
