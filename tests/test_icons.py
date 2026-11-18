"""Icon lookup: Lucide SVG before PNG, fitted stroke, aliases for old names, downloads (no network)."""
import os
import sys

import pytest
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "aws_lambda"))

from designs import common  # noqa: E402

LUCIDE_LIKE = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
               'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
               '<path d="M4 4h16v16H4z" /><path d="M4 12h16" /></svg>')


@pytest.fixture(autouse=True)
def _fresh_icons(monkeypatch, tmp_path):
    monkeypatch.setenv("ICONS_CACHE_DIR", str(tmp_path))
    common.set_icon_manager(None)
    yield
    common.set_icon_manager(None)


def test_fit_stroke_sets_root_width_and_leaves_fill_icons_alone():
    import re
    out16 = common.fit_stroke(LUCIDE_LIKE, 16)
    root = re.search(r"<svg[^>]*>", out16).group(0)
    assert root.count("stroke-width") == 1 and 'stroke-width="2.250"' in root       # 1.5 px at 16
    assert 'stroke-width="2.400"' in common.fit_stroke(LUCIDE_LIKE, 20)              # 2 px at 20
    no_width = LUCIDE_LIKE.replace(' stroke-width="2"', "")
    assert 'stroke-width="2.250"' in common.fit_stroke(no_width, 16)                 # added when missing
    filled = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>'
    assert common.fit_stroke(filled, 16) == filled


def test_svg_beats_png_and_old_names_still_work():
    assert common._load_icon(["gift"], 16).endswith("gift.svg")          # a legacy gift.png is also there
    assert os.path.isfile(os.path.join(common.ICONS, "gift.png"))
    for old, new in (("school", "graduation-cap"), ("umbrella_beach", "tree-palm")):
        path = common._load_icon([common.ICON_ALIASES[old], old], 16)
        assert path.endswith(new + ".svg")
        assert common.icon(old, 16).size == (16, 16)
    for custom in ("skate", "gymnastics", "soccer"):
        assert common._load_icon([custom], 20).endswith(custom + ".svg")
    assert common._load_icon(["grave-stone"], 16).endswith(".png")       # no SVG anywhere: old PNG


class FakeManager:
    """Stands in for IconManager: '_download_icon' writes the SVG into the cache dir."""

    def __init__(self, cache, known):
        self.cache, self.known, self.calls = cache, known, []

    def _download_icon(self, name):
        self.calls.append(name)
        if name not in self.known:
            return None
        p = os.path.join(self.cache, name + ".svg")
        with open(p, "w") as f:
            f.write(self.known[name])
        return p

    def get_icon_image(self, name, size=None):       # must not be used
        raise AssertionError("pre-rasterised icon used")


def test_downloaded_svg_gets_the_fitted_stroke(tmp_path):
    import io
    import resvg_py
    mgr = FakeManager(str(tmp_path), {"made-up-box": LUCIDE_LIKE})
    common.set_icon_manager(mgr)
    got = common.icon("made-up-box", 16)
    assert mgr.calls == ["made-up-box"] and got.size == (16, 16)

    def raster(svg):
        im = Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg.replace("currentColor", "#000"),
                                                                width=16, height=16)))).convert("RGBA")
        return im.split()[3].point(lambda a: 255 if a >= 110 else 0).tobytes()
    assert got.split()[3].tobytes() == raster(common.fit_stroke(LUCIDE_LIKE, 16))
    assert got.split()[3].tobytes() != raster(LUCIDE_LIKE)
    common.icon("made-up-box", 20)                   # now cached on disk: no second download
    assert mgr.calls == ["made-up-box"]


def test_unknown_icon_falls_back_cleanly(tmp_path, monkeypatch):
    mgr = FakeManager(str(tmp_path), {})
    common.set_icon_manager(mgr)
    assert common.icon("no-such-icon", 16) is None
    monkeypatch.setitem(common.ICON_FALLBACK, "no-such-thing", "cake")
    assert common.icon("no-such-thing", 16).size == (16, 16)
    assert common.paste_icon(Image.new("RGB", (20, 20)), "no-such-icon", 0, 0, 16) == 0


def test_icon_manager_404_is_remembered_and_url_is_pinned(tmp_path, monkeypatch):
    import inky_icons_package as iip

    class Resp:
        def __init__(self, code, body=b""):
            self.status_code, self.content = code, body
    urls = []

    def fake_get(url, timeout=5):
        urls.append(url)
        if "no-such-icon" in url:
            return Resp(404)
        if "flaky" in url:
            raise OSError("network down")
        return Resp(200, LUCIDE_LIKE.encode())
    monkeypatch.setattr(iip.requests, "get", fake_get)
    empty = tmp_path / "bundled"
    empty.mkdir()
    mgr = iip.IconManager(icons_dir=str(empty), cache_dir=str(tmp_path / "cache"))

    assert mgr._download_icon("no-such-icon") is None
    assert os.path.isfile(tmp_path / "cache" / "no-such-icon.svg.404")
    assert mgr._download_icon("no-such-icon") is None
    fresh = iip.IconManager(icons_dir=str(empty), cache_dir=str(tmp_path / "cache"))
    assert fresh._download_icon("no-such-icon") is None          # the marker survives a new process
    assert len([u for u in urls if "no-such-icon" in u]) == 1

    assert mgr._download_icon("flaky") is None and mgr._download_icon("flaky") is None
    assert len([u for u in urls if "flaky" in u]) == 1             # not retried in this process
    assert not os.path.exists(tmp_path / "cache" / "flaky.svg.404")   # but not marked as missing

    p = mgr._download_icon("bike")
    assert p.endswith("bike.svg") and urls[-1] == "https://unpkg.com/lucide-static@0.460.0/icons/bike.svg"
    assert mgr._download_icon("umbrella_beach") is None            # not a Lucide-style name: no request
    assert not any("umbrella_beach" in u for u in urls)


def test_swimming_uses_waves_not_the_rain_droplet():
    import config_store
    import mappings
    rows = config_store.event_mappings({"people": [], "rules": [
        {"word": "Svømming", "icon": "droplet", "tag": "", "remove": False},
        {"word": "Regn", "icon": "droplet", "tag": "", "remove": False}]})
    icons = {r["keyword"]: r["icon"] for r in rows}
    assert icons == {"Svømming": "waves", "Regn": "droplet"}
    assert any(m["keyword"] == "svømm" and m["icon"] == "waves" for m in mappings.FALLBACK_EVENT_MAPPINGS)
