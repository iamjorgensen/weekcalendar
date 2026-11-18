"""Event rows, person chips and the rolling month weeks."""
import os
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "aws_lambda"))

from designs import common, dense  # noqa: E402
from designs.blocks import event_row  # noqa: E402
from designs.common import BLACK, BLUE, GREEN, RED, WHITE, YELLOW  # noqa: E402

@pytest.fixture(autouse=True)
def _fresh_icons(monkeypatch, tmp_path):
    monkeypatch.setenv("ICONS_CACHE_DIR", str(tmp_path))
    common.set_icon_manager(None)
    yield
    common.set_icon_manager(None)


def _canvas():
    img = Image.new("RGB", (400, 200), WHITE)
    return img, ImageDraw.Draw(img)


# ------------------------------------------------------------------ event rows
@pytest.mark.parametrize("ev", [
    {"time": "09:00", "title": "Gym", "icon": "gymnastics", "people": [("N", YELLOW)]},
    {"time": "17:30", "title": "Tannlege", "icon": None, "people": []},
    {"time": "", "title": "Turdag: husk sitteunderlag og varm drikke og mye mer", "icon": "school",
     "people": [("E", GREEN), ("K", RED)]},
])
def test_event_row_measure_matches_draw(ev):
    img, draw = _canvas()
    for kw in (dense.ROW, dense.TODAY_ROW):
        measured = event_row(None, draw, 0, 0, 260, ev, draw_it=False, **kw)
        drawn = event_row(img, draw, 0, 0, 260, ev, **kw)
        assert measured == drawn > 0


def test_timed_titles_share_one_left_edge_and_all_day_uses_full_width():
    def title_left(ev):
        img, draw = _canvas()
        event_row(img, draw, 0, 0, 300, ev, **dense.ROW)
        # leftmost ink right of the icon slot (time column + icon)
        tw = common.text_w(draw, "00:00", common.f_tiny(dense.ROW["size"] - 2))
        x0 = tw + 7 + dense.ROW["icon_size"] + 1
        box = img.crop((x0, 0, 300, 40)).convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
        return x0 + box[0]
    a = title_left({"time": "9:00", "title": "Håndball", "icon": "volleyball"})
    b = title_left({"time": "17:30", "title": "Håndball", "icon": None})       # dot instead of an icon
    assert a == b

    img, draw = _canvas()
    event_row(img, draw, 0, 0, 300, {"time": "", "title": "Restavfall", "icon": "trash-2"}, **dense.ROW)
    ink = img.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
    assert ink[0] <= 2          # the all-day icon starts at the left edge


def test_timed_event_without_icon_gets_a_dot():
    img, draw = _canvas()
    event_row(img, draw, 0, 0, 300, {"time": "12:00", "title": "", "icon": None}, **dense.ROW)
    tw = common.text_w(draw, "00:00", common.f_tiny(dense.ROW["size"] - 2))
    slot = img.crop((tw + 7, 0, tw + 7 + dense.ROW["icon_size"], 30))
    assert BLACK in [c for _n, c in slot.getcolors()]


# ------------------------------------------------------------------ chips
@pytest.mark.parametrize("color,bg,ring", [
    (YELLOW, WHITE, BLACK), (GREEN, WHITE, BLACK), (BLUE, WHITE, None), (RED, WHITE, None),
    (BLUE, BLACK, WHITE), (RED, BLACK, WHITE), (BLACK, BLACK, WHITE), (YELLOW, BLACK, None),
])
def test_person_chip_ring(color, bg, ring):
    assert common.chip_ring(color, bg) == ring
    img = Image.new("RGB", (40, 40), bg)
    common.person_chip(ImageDraw.Draw(img), 10, 20, "", color, 20, bg=bg)
    assert img.getpixel((20, 10)) == (ring or color)      # top of the circle
    assert img.getpixel((20, 14)) == color


# ------------------------------------------------------------------ rolling month
def test_rolling_weeks_start_with_this_week():
    weeks = dense.month_weeks(date(2026, 11, 18), rolling=True)
    assert len(weeks) == 5 and weeks[0][0] == date(2026, 11, 16) and weeks[-1][-1] == date(2026, 12, 20)
    assert dense.month_heading(date(2026, 11, 18), rolling=True) == "November – desember"
    assert dense.month_heading(date(2026, 11, 18)) == "November 2026"


@pytest.mark.parametrize("day", [28, 29, 30, 31])
def test_rolling_weeks_across_new_year(day):
    weeks = dense.month_weeks(date(2026, 12, day), rolling=True)
    assert weeks[0][0] == date(2026, 12, 28) and weeks[-1][-1] == date(2027, 1, 31)
    assert [w[0].isocalendar()[1] for w in weeks] == [53, 1, 2, 3, 4]
    assert dense.month_heading(date(2026, 12, day), rolling=True) == "Desember – januar 2027"


def test_month_column_is_rolling_unless_classic_is_chosen(monkeypatch):
    from designs.adapter import to_design_data
    seen = []
    real = dense._month_light
    monkeypatch.setattr(dense, "_month_light", lambda *a, **k: (seen.append(k.get("rolling")), real(*a, **k))[1])
    now = datetime(2026, 12, 30, 7, 0, tzinfo=ZoneInfo("Europe/Oslo"))
    data = to_design_data({"events": [], "weather": [], "hourly_today": []}, days=14, now=now)
    a = dense.render(data, {"month_column": True})
    b = dense.render(data, {"month_column": True, "month_classic": True})
    dense.render(data, {"month_right": True})
    assert seen == [True, False, True]
    assert a.tobytes() != b.tobytes() and len(a.getcolors(1 << 24)) <= 6
    assert dense._light_month_metrics(date(2026, 11, 1), True, rolling=True)[0] == 5
    assert dense._light_month_metrics(date(2026, 11, 1), True)[0] == 6       # November 2026 spans six weeks


def test_view_option_month_classic_is_stored():
    import config_store
    cfg = config_store.validate({"view": {"options": ["month_column", "month_classic", "nonsense"]}})
    assert cfg["view"]["options"] == ["month_column", "month_classic"]
    assert "month_classic" not in config_store.DEFAULT_VIEW["options"]       # rolling weeks by default
