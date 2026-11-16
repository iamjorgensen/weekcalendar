"""E-ink calendar designs. Entry point: render_design(name, data, days)."""
import importlib
import os

DESIGNS = ("hero", "agenda", "band")


def render_design(name, data, days, icon_manager=None, now=None):
    """Render initial_fetch_all() data with the named design. Returns an 800x480 RGB image."""
    if name not in DESIGNS:
        raise ValueError(f"unknown design {name!r}; choose one of {DESIGNS}")
    from designs import common
    from designs.adapter import to_design_data

    common.set_icon_manager(icon_manager)

    def _f(env):
        try:
            return float(os.environ.get(env, ""))
        except ValueError:
            return None

    design_data = to_design_data(data, days=int(days or 10), now=now, lat=_f("LAT"), lon=_f("LON"))
    mod = importlib.import_module(f"designs.{name}")
    return mod.render(design_data)
