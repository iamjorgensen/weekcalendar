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

WEEKDAYS = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
KINDS = ["closed", "early_finish", "trip", "gym", "bring", "special", "deadline", "meeting"]

SUPPORTED_IMAGES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

SCHEMA = {
    "type": "object",
    "properties": {
        "week": {"type": "integer", "description": "ISO week number the letter is about (the coming week)"},
        "year": {"type": "integer", "description": "Year of that week, or 0 if the letter doesn't say"},
        "grade": {"type": "integer", "description": "School grade ('trinn'), or 0 if not stated"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "weekday": {"type": "string", "enum": WEEKDAYS},
                    "date": {"type": "string", "description": "YYYY-MM-DD if the letter gives an explicit date "
                                                              "(e.g. for something outside the week), else ''"},
                    "start": {"type": "string", "description": "HH:MM, or '' for all-day"},
                    "end": {"type": "string", "description": "HH:MM, or ''"},
                    "kind": {"type": "string", "enum": KINDS},
                    "title": {"type": "string", "description": "Short Norwegian calendar title, max ~45 chars"},
                    "bring": {"type": "array", "items": {"type": "string"},
                              "description": "Things to bring/wear that day, short words"},
                    "details": {"type": "string", "description": "One short sentence of extra info, or ''"},
                    "already_in_calendar": {"type": "boolean",
                                            "description": "true if the same thing on the same day is already "
                                                           "in the family calendar list (even if worded differently)"},
                },
                "required": ["weekday", "date", "start", "end", "kind", "title", "bring", "details",
                             "already_in_calendar"],
                "additionalProperties": False,
            },
        },
        "week_reminders": {"type": "array", "items": {"type": "string"},
                           "description": "Short reminders for the whole week without a specific day"},
        "dinner_question": {"type": "string", "description": "'Middagssamtalen' question if present, else ''"},
    },
    "required": ["week", "year", "grade", "items", "week_reminders", "dinner_question"],
    "additionalProperties": False,
}

SYSTEM = """Du er familiens assistent. Du leser ukebrev fra en norsk barneskole og finner det foreldrene MÅ vite eller gjøre, slik at det havner i familiekalenderen.

Prioriter (viktigst først):
1. Alt som starter med "Husk" eller krever handling fra foreldre: møter, foreldremøter, utviklingssamtaler, påmeldinger, frister, ting som skal signeres eller betales ("meeting"/"deadline"/"bring").
2. Skole og/eller SFO stengt, planleggingsdager, fridager ("closed").
3. Tidligere slutt enn vanlig. Finn den vanlige sluttiden i timeplanen (den som går igjen flest dager) og ta bare med dager som slutter tidligere ("early_finish", title "Slutt 13:20", start = sluttiden).
4. Turdager, uteskole, ekskursjoner - med det som skal tas med ("trip", utstyr i "bring").
5. Gym/kroppsøving/svømming/fysak - dager barnet trenger gymtøy ("gym").
6. Spesielle hendelser for barna: disco, aktivitetsdag, forestilling, kostymefest, bursdagsfeiring i klassen ("special").

Ikke ta med: fagbeskrivelser, læringsmål, ordbank, sosiale mål, grønne tips, hva som skjedde forrige uke, kontaktinfo, lærernavn, e-postadresser, telefonnumre, bilder.

Regler:
- Én post per dag og aktivitet. Slå sammen det som hører sammen (tur + utstyr blir én post med utstyret i "bring").
- Titler korte og konkrete på norsk, maks ~45 tegn, uten barnets navn (det legges på automatisk). Ta med klokkeslett i start/end når brevet oppgir det.
- Står det en dato (f.eks. "foreldremøte torsdag 3. desember kl. 18"), bruk "date" = YYYY-MM-DD, også når det er utenfor uka.
- Generelle påminnelser for hele uka uten bestemt dag (skiftetøy, innesko, ta med gamle klær) i "week_reminders", korte.
- Du får også en liste over hva som allerede ligger i familiekalenderen. Sett "already_in_calendar" = true når det samme allerede står der samme dag, selv om det er formulert annerledes ("Foreldremøte" = "Foreldremøte 6B kl 18"). Ved tvil: false.
- Ukenummer: uka brevet gjelder (overskriften, f.eks. "Uke 47"). Trinn: tallet i "6. trinn". Bruk 0 når noe ikke står i brevet.
- Finn aldri på noe som ikke står i brevet."""


class ExtractError(RuntimeError):
    pass


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
    if media_type.startswith("text/") or not media_type:
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
    return "Dette ligger allerede i familiekalenderen:\n" + "\n".join(lines[:400])


def call_model(client, data: bytes, media_type: str, today: date, existing=None):
    """One Claude call with structured output. Returns the parsed dict."""
    block = content_block(data, media_type)
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [
            block,
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
        return json.loads(text)
    except ValueError as e:
        raise ExtractError(f"Ugyldig svar fra modellen: {e}")


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


def to_calendar_items(result: dict, today: date):
    """Model result -> list of dicts: date, start, end, title, details, kind. Plus the week id."""
    week = int(result.get("week") or 0)
    if not 1 <= week <= 53:
        raise ExtractError("Fant ikke ukenummer i brevet.")
    monday = week_dates(week, int(result.get("year") or 0), today)
    iso_year = monday.isocalendar()[0]
    items = []
    for it in result.get("items") or []:
        d = None
        if it.get("date"):
            try:
                d = date.fromisoformat(it["date"])
            except ValueError:
                d = None
        if d is None:
            try:
                d = monday + timedelta(days=WEEKDAYS.index(it.get("weekday")))
            except ValueError:
                continue
        title = (it.get("title") or "").strip()
        if not title:
            continue
        bring = [b.strip() for b in it.get("bring") or [] if b and b.strip()]
        if bring:
            title = f"{title} – husk {', '.join(bring)}"
        items.append({
            "date": d,
            "start": (it.get("start") or "").strip(),
            "end": (it.get("end") or "").strip(),
            "title": title,
            "details": (it.get("details") or "").strip(),
            "kind": it.get("kind") or "special",
            "already_in_calendar": bool(it.get("already_in_calendar")),
        })
    reminders = [r.strip() for r in result.get("week_reminders") or [] if r and r.strip()]
    if reminders:
        items.append({"date": monday, "start": "", "end": "", "kind": "bring",
                      "title": "Husk denne uka: " + ", ".join(reminders), "details": "",
                      "already_in_calendar": False})
    return f"{iso_year}-W{week:02d}", items
