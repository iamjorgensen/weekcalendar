"""
Read a school letter ("ukebrev": PDF, image or text) with Claude and turn it
into calendar items for one child.

Pure logic + one model call; no AWS or Google code here so it can be tested
with a fake client.
"""
import base64
import json
from datetime import date, timedelta

MODEL = "anthropic.claude-opus-5-5"   # Claude in Amazon Bedrock (bedrock-mantle)
# Used if MODEL is not available to the AWS account (Bedrock lists it as open to all customers)
FALLBACK_MODELS = ["anthropic.claude-opus-4-8"]

WEEKDAYS = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
KINDS = ["closed", "early_finish", "trip", "gym", "bring", "special", "deadline", "meeting"]

SUPPORTED_IMAGES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": ["ukebrev", "other"],
                     "description": "'ukebrev' = weekly letter for one class/grade; 'other' = flyer, invitation, info letter"},
        "week": {"type": "integer", "description": "ISO week number a weekly letter is about, else 0"},
        "year": {"type": "integer", "description": "Year of that week, or 0 if the letter doesn't say"},
        "grade": {"type": "integer", "description": "School grade ('trinn'), or 0 if not stated"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "weekday": {"type": "string", "enum": WEEKDAYS + [""],
                                "description": "Weekday within the letter's week, or '' when 'date' is given"},
                    "date": {"type": "string", "description": "YYYY-MM-DD if the letter gives an explicit date "
                                                              "(e.g. for something outside the week), else ''"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD last day when this is a period "
                                                                  "over several days (ferie, uke 40), else ''"},
                    "start": {"type": "string", "description": "HH:MM, or '' for all-day"},
                    "end": {"type": "string", "description": "HH:MM, or ''"},
                    "kind": {"type": "string", "enum": KINDS},
                    "title": {"type": "string", "description": "Short Norwegian calendar title, max ~45 chars"},
                    "bring": {"type": "array", "items": {"type": "string"},
                              "description": "Things to bring/wear that day, short words"},
                    "details": {"type": "string", "description": "One short sentence of extra info, or ''"},
                    "for": {"type": "array", "items": {"type": "string"},
                            "description": "Which of the family's children this applies to (names from the list); "
                                           "empty = the whole family / not child-specific"},
                    "already_in_calendar": {"type": "boolean",
                                            "description": "true if the same thing on the same day is already "
                                                           "in the family calendar list (even if worded differently)"},
                },
                "required": ["weekday", "date", "end_date", "start", "end", "kind", "title", "bring", "details",
                             "for", "already_in_calendar"],
                "additionalProperties": False,
            },
        },
        "week_reminders": {"type": "array", "items": {"type": "string"},
                           "description": "Short reminders for the whole week without a specific day"},
        "dinner_question": {"type": "string", "description": "'Middagssamtalen' question if present, else ''"},
        "timetable": {
            "type": "array",
            "description": "The week's timetable (timeplan) for the child's class, one entry per school day "
                           "Mandag-Fredag that the letter shows; empty if the letter has no timetable",
            "items": {
                "type": "object",
                "properties": {
                    "weekday": {"type": "string", "enum": WEEKDAYS[:5]},
                    "start": {"type": "string", "description": "HH:MM the school day starts, or ''"},
                    "end": {"type": "string", "description": "HH:MM the school day ends ('Slutt 14.45'), or ''"},
                    "lunch": {"type": "string", "description": "HH:MM the lunch break (spising/lunsj) starts, or ''"},
                    "lessons": {"type": "array", "items": {"type": "string"},
                                "description": "Subjects/activities in order, short Norwegian names"},
                    "closed": {"type": "boolean", "description": "true if there is no school that day"},
                    "note": {"type": "string", "description": "Why it is closed (short), else ''"},
                },
                "required": ["weekday", "start", "end", "lunch", "lessons", "closed", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["doc_type", "week", "year", "grade", "items", "week_reminders", "dinner_question", "timetable"],
    "additionalProperties": False,
}

SYSTEM = """Du er familiens assistent. Du får et dokument fra skole, SFO, idrettslag, kommune eller lignende - et ukebrev, et informasjonsskriv, en invitasjon eller en plakat - og finner det foreldrene MÅ vite eller gjøre, slik at det havner i familiekalenderen.

Dokumenttype: "ukebrev" er et ukentlig brev for én klasse/ett trinn (har som regel "Uke NN" og "N. trinn"). Alt annet er "other".

Prioriter (viktigst først):
1. Alt som krever handling fra foreldre: "Husk ...", møter, foreldremøter, utviklingssamtaler, påmeldinger, frister, ting som skal signeres eller betales ("meeting"/"deadline"/"bring"). En påmeldingsfrist blir en egen post på fristdagen, f.eks. "Frist: påmelding Barnas frimarked", og hvordan man melder på (e-post/lenke) står i "details".
2. Skole og/eller SFO stengt, planleggingsdager, fridager ("closed").
3. Tidligere slutt enn vanlig. Finn den vanlige sluttiden i timeplanen (den som går igjen flest dager) og ta bare med dager som slutter tidligere ("early_finish", title alltid på formen "Skoleslutt 13:20", start = sluttiden).
4. Turdager, uteskole, ekskursjoner - med det som skal tas med ("trip", utstyr i "bring").
5. Gym/kroppsøving/svømming/fysak - dager barnet trenger gymtøy ("gym").
6. Arrangementer for barna eller familien: disco, aktivitetsdag, forestilling, marked, kostymefest, cup, konsert ("special") - med sted i "details" og det som må tas med i "bring".

Ikke ta med: fagbeskrivelser, læringsmål, ordbank, sosiale mål, grønne tips, hva som skjedde forrige uke, lærernavn, telefonnumre, bilder. Kontaktinfo bare når den trengs for å gjøre noe (påmelding, svar).

Regler:
- Én post per dag og aktivitet. Slå sammen det som hører sammen (tur + utstyr blir én post med utstyret i "bring").
- En periode over flere dager - ferie, "uke 40 (28.09-02.10)", "fri 21.12-01.01" - blir ÉN post med "date" = første dag og "end_date" = siste dag (heldags). Ta med alle slike perioder i dokumentet, også i skoleruter med mange datoer.
- Titler korte og konkrete på norsk, maks ~45 tegn, uten barnenes navn (det legges på automatisk). Klokkeslett i start/end når dokumentet oppgir det.
- Ukebrev: bruk "weekday" for dager i uka. Står det en egen dato (f.eks. "foreldremøte torsdag 3. desember kl. 18"), bruk "date" = YYYY-MM-DD.
- Andre dokumenter: bruk alltid "date" = YYYY-MM-DD og "weekday" = "". Mangler årstall, velg første dato fra og med i dag.
- "for": hvilke av familiens barn posten gjelder (navn fra listen). For ukebrev: barnet på det trinnet. Gjelder det alle barn/hele familien, eller er det uklart: tom liste.
- Grupper: står det at noe gjelder en bestemt gruppe (f.eks. "Gruppe Sild: gym tirsdag", "Gruppe Torsk: gym onsdag"), ta bare med det som gjelder barnets egen gruppe fra listen. Gjelder noe annenhver uke / partallsuker / oddetallsuker, bruk ukenummeret for å avgjøre om det gjelder denne uka.
- Generelle påminnelser for hele uka uten bestemt dag (skiftetøy, innesko) i "week_reminders" (bare ukebrev), korte.
- Du får en liste over hva som allerede ligger i familiekalenderen. Sett "already_in_calendar" = true når det samme allerede står der samme dag, selv om det er formulert annerledes ("Foreldremøte" = "Foreldremøte 6B kl 18"). Ved tvil: false.
- Ukenummer og trinn: bare når dokumentet sier det, ellers 0.
- Timeplan ("timetable", bare ukebrev): har brevet en timeplan for uka, ta med hver skoledag mandag-fredag: når dagen starter (første økt) og slutter ("Slutt 14.45" -> "14:45"), når spisepausen/lunsjen starter ("lunch", tom hvis timeplanen ikke viser den den dagen), og fagene/aktivitetene i rekkefølge med korte navn ("Norsk", "Matte", "Kroppsøving", "Kunst og håndverk", "Turdag"). Hopp over samling, friminutt, spising, lunsj og logg, og slå sammen samme fag rett etter hverandre. "Fysak / Norsk" o.l. for to grupper: bruk barnets gruppe hvis den er kjent, ellers skriv begge. Dager uten skole: "closed" = true og grunnen kort i "note" ("Kursdag – skole og SFO stengt"). Ingen timeplan i brevet: tom liste.
- Finn aldri på noe som ikke står i dokumentet."""


class ExtractError(RuntimeError):
    pass


# Claude API list prices, USD per million tokens (input, output). Used only to show an
# estimated cost on the admin page; Bedrock is billed by AWS at its own rates.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-4-8": (5.00, 25.00),
}


def usage_of(response, model):
    """{'model', 'input_tokens', 'output_tokens'} from a Messages response (zeros if absent)."""
    u = getattr(response, "usage", None)
    tokens = lambda name: int(getattr(u, name, 0) or 0)   # noqa: E731
    return {"model": getattr(response, "model", None) or model,
            "input_tokens": tokens("input_tokens") + tokens("cache_creation_input_tokens")
            + tokens("cache_read_input_tokens"),
            "output_tokens": tokens("output_tokens")}


def estimate_usd(usage):
    """Estimated cost in USD for a usage dict, or None for a model without a known price."""
    model = (usage.get("model") or "").removeprefix("anthropic.")
    price = PRICES.get(model) or next((p for m, p in PRICES.items() if model.startswith(m)), None)
    if not price:
        return None
    return (usage.get("input_tokens", 0) * price[0] + usage.get("output_tokens", 0) * price[1]) / 1_000_000


def content_block(data: bytes, media_type: str):
    """The user content block for the uploaded letter."""
    media_type = (media_type or "").split(";")[0].strip().lower()
    if media_type == "application/pdf" or data[:4] == b"%PDF":
        return {"type": "document",
                "source": {"type": "base64", "media_type": "application/pdf",
                           "data": base64.standard_b64encode(data).decode("ascii")}}
    if media_type in SUPPORTED_IMAGES:
        return {"type": "image",
                "source": {"type": "base64", "media_type": media_type,
                           "data": base64.standard_b64encode(data).decode("ascii")}}
    if media_type.startswith("text/") or media_type in ("application/rtf", "") or data[:5] == b"{\\rtf":
        try:
            return {"type": "text", "text": data.decode("utf-8")}
        except UnicodeDecodeError:
            pass
    raise ExtractError(f"Filtypen støttes ikke ({media_type or 'ukjent'}). Send PDF, JPEG/PNG eller tekst.")


def format_existing(existing):
    """[(date, 'HH:MM' or '', title)] -> text list for the prompt."""
    if not existing:
        return "Familiekalenderen har ingen hendelser i perioden."
    lines = [f"- {d.isoformat()} {t + ' ' if t else ''}{title}" for d, t, title in sorted(existing)]
    return "Dette ligger allerede i familiekalenderen:\n" + "\n".join(lines[:600])


def format_children(children_now):
    """[(name, grade_now[, groups])] -> prompt text."""
    if not children_now:
        return "Familiens barn er ikke oppgitt."
    parts = []
    for c in children_now:
        n, g = c[0], c[1]
        groups = list(c[2]) if len(c) > 2 and c[2] else []
        extra = f", gruppe {' og '.join(groups)}" if groups else ""
        parts.append(f"{n} ({g}. trinn{extra})")
    return "Familiens barn: " + ", ".join(parts) + "."


def call_model(client, data: bytes, media_type: str, today: date, existing=None, children_now=None,
               models=None):
    """
    One Claude call with structured output. Returns the parsed dict, with the call's
    token usage under "_usage" (see usage_of).
    Tries each model in `models` (default: MODEL, then FALLBACK_MODELS) and moves on
    only when a model is unavailable to the account (not found / no access).
    """
    import anthropic
    candidates = [m for m in (models or [MODEL] + FALLBACK_MODELS) if m]
    last = None
    for i, model in enumerate(candidates):
        try:
            return _call_one(client, model, data, media_type, today, existing, children_now)
        except (anthropic.NotFoundError, anthropic.PermissionDeniedError) as e:
            last = e
            if i + 1 < len(candidates):
                continue
    raise last


def _call_one(client, model, data, media_type, today, existing, children_now):
    block = content_block(data, media_type)
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [
            block,
            {"type": "text", "text": format_children(children_now)},
            {"type": "text", "text": format_existing(existing)},
            {"type": "text", "text": f"Dagens dato er {today.isoformat()}. Hent ut kalenderpostene fra ukebrevet."},
        ]}],
    )
    if response.stop_reason == "refusal":
        raise ExtractError("Modellen avviste forespørselen.")
    if response.stop_reason == "max_tokens":
        raise ExtractError("Svaret ble for langt (max_tokens).")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        result = json.loads(text)
    except ValueError as e:
        raise ExtractError(f"Ugyldig svar fra modellen: {e}")
    result["_usage"] = usage_of(response, model)
    return result


# ------------------------------------------------------------------ children
def school_year_start(d: date) -> int:
    """Calendar year in which the current school year started (August)."""
    return d.year if d.month >= 8 else d.year - 1


def parse_children(spec: str):
    """'Amalie:6,Sigrid:3' -> [('Amalie', 6), ('Sigrid', 3)] (grades in CHILDREN_SCHOOL_YEAR)."""
    out = []
    for part in (spec or "").split(","):
        if ":" in part:
            name, grade = part.split(":", 1)
            try:
                out.append((name.strip(), int(grade)))
            except ValueError:
                pass
    return out


def children_now(children, base_year: int, today: date):
    """Grades this school year: [(name, grade)]."""
    shift = school_year_start(today) - base_year
    return [(n, g + shift) for n, g in children]


def child_for_grade(grade: int, children, base_year: int, today: date):
    """Name of the child in `grade` now, given grades as of the school year starting `base_year`."""
    shift = school_year_start(today) - base_year
    for name, g in children:
        if g + shift == grade:
            return name
    return None


# ------------------------------------------------------------------ dates
def week_dates(week: int, year: int, today: date):
    """Monday of ISO week; if year is unknown pick the occurrence nearest to today."""
    if year:
        return date.fromisocalendar(year, week, 1)
    candidates = []
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(date.fromisocalendar(y, week, 1))
        except ValueError:
            pass
    return min(candidates, key=lambda d: abs((d - today).days))


def to_calendar_items(result: dict, today: date, default_for=None):
    """
    Model result -> (doc_key, items). Items: date, start, end, title, details, kind,
    for (list of child names), already_in_calendar.
    doc_key is 'YYYY-Www' for weekly letters (used to replace a re-uploaded week), else None.
    """
    week = int(result.get("week") or 0)
    is_week = result.get("doc_type", "ukebrev") == "ukebrev" and 1 <= week <= 53
    monday = week_dates(week, int(result.get("year") or 0), today) if is_week else None
    items = []
    for it in result.get("items") or []:
        d = None
        if it.get("date"):
            try:
                d = date.fromisoformat(it["date"])
            except ValueError:
                d = None
        if d is None and monday is not None and it.get("weekday") in WEEKDAYS:
            d = monday + timedelta(days=WEEKDAYS.index(it["weekday"]))
        title = (it.get("title") or "").strip()
        if d is None or not title:
            continue
        bring = [b.strip() for b in it.get("bring") or [] if b and b.strip()]
        if bring:
            title = f"{title} – husk {', '.join(bring)}"
        who = [n for n in (it.get("for") or []) if n] or list(default_for or [])
        end_date = None
        if it.get("end_date"):
            try:
                end_date = date.fromisoformat(it["end_date"])
            except ValueError:
                end_date = None
            if end_date is not None and not (d < end_date <= d + timedelta(days=80)):
                end_date = None
        items.append({
            "date": d,
            "end_date": end_date,
            "start": (it.get("start") or "").strip(),
            "end": (it.get("end") or "").strip(),
            "title": title,
            "details": (it.get("details") or "").strip(),
            "kind": it.get("kind") or "special",
            "for": who,
            "already_in_calendar": bool(it.get("already_in_calendar")),
        })
    reminders = [r.strip() for r in result.get("week_reminders") or [] if r and r.strip()]
    if reminders and monday is not None:
        items.append({"date": monday, "start": "", "end": "", "kind": "bring",
                      "title": "Husk denne uka: " + ", ".join(reminders), "details": "",
                      "for": list(default_for or []), "already_in_calendar": False})
    if not is_week and not items:
        raise ExtractError("Fant ingen datoer eller hendelser i dokumentet.")
    doc_key = f"{monday.isocalendar()[0]}-W{week:02d}" if is_week else None
    return doc_key, items


def to_timetable(result: dict):
    """The letter's timetable -> [{weekday 0-4, start, end, lunch, lessons, closed, note}] (cleaned, by weekday)."""
    import re

    def hhmm(t):
        m = re.match(r"^\s*(\d{1,2})[.:](\d{2})\s*$", t or "")
        return f"{int(m.group(1)):02d}:{m.group(2)}" if m and int(m.group(1)) < 24 else ""
    out = {}
    for d in result.get("timetable") or []:
        if d.get("weekday") not in WEEKDAYS[:5]:
            continue
        lessons = [str(x).strip()[:30] for x in d.get("lessons") or [] if str(x).strip()][:10]
        closed = bool(d.get("closed"))
        if not closed and not lessons and not hhmm(d.get("end")):
            continue
        out[WEEKDAYS.index(d["weekday"])] = {
            "weekday": WEEKDAYS.index(d["weekday"]), "start": "" if closed else hhmm(d.get("start")),
            "end": "" if closed else hhmm(d.get("end")), "lunch": "" if closed else hhmm(d.get("lunch")),
            "lessons": [] if closed else lessons,
            "closed": closed, "note": str(d.get("note") or "").strip()[:60]}
    return [out[k] for k in sorted(out)]


def title_with_names(title, names):
    """
    'Skoleslutt 13:20', ['Amalie'] -> 'Skoleslutt 13:20 Amalie'. Names go LAST, separated only by
    spaces, so the calendar's tag mapping (which removes a name and shows it as a coloured
    tag) leaves a clean title behind.
    """
    names = [n for n in names or [] if n]
    return " ".join([title] + names) if names else title
