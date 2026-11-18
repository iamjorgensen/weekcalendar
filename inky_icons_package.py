# inky_icons_package.py
import os
import io
import logging
import re
import requests
from PIL import Image

# The likely version of resvg_py on your system uses this simple import
import resvg_py

try:
    from mappings import mapping_info_for_event, weather_to_icon, color_to_rgb
except Exception:
    mapping_info_for_event = None
    weather_to_icon = None
    color_to_rgb = None

logger = logging.getLogger(__name__)

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
ICONS_DIR = os.path.join(ASSETS_DIR, "icons")

# Pinned so icon names and shapes do not change underneath us (bundled SVGs are the same version)
LUCIDE_VERSION = "0.460.0"
LUCIDE_URL = "https://unpkg.com/lucide-static@{version}/icons/{name}.svg"

class IconManager:
    def __init__(self, icons_dir=None, load_size=24, cache_dir=None):
        self.icons_dir = icons_dir or ICONS_DIR
        # Where downloaded icons are written. Defaults to icons_dir (as on the Pi).
        # Set ICONS_CACHE_DIR when icons_dir is read-only (e.g. /tmp/icons on AWS Lambda);
        # bundled icons are still read from icons_dir.
        self.cache_dir = cache_dir or os.environ.get("ICONS_CACHE_DIR") or self.icons_dir
        self.load_size = load_size
        self._icons = {}
        self._failed = set()     # names whose download failed in this process

        for d in {self.icons_dir, self.cache_dir}:
            if not os.path.exists(d):
                try:
                    os.makedirs(d, exist_ok=True)
                except OSError as e:
                    logger.warning(f"Could not create icon dir {d}: {e}")

        self._load_icons_from_dir(self.icons_dir)
        if self.cache_dir != self.icons_dir:
            # downloaded icons override bundled ones with the same name
            self._load_icons_from_dir(self.cache_dir)

    def _process_file(self, path, size):
            """Standardizes icon loading using the confirmed 'svg_to_bytes' with string input."""
            try:
                if path.lower().endswith(".svg"):
                    # Open as text string (not bytes) to satisfy the library requirement
                    with open(path, "r", encoding="utf-8") as f:
                        svg_text = f.read()

                    # Call the confirmed method with the text string
                    png_data = resvg_py.svg_to_bytes(svg_text, width=size, height=size)

                    return Image.open(io.BytesIO(png_data)).convert("RGBA")

                else:
                    # Standard PNG handling
                    im = Image.open(path).convert("RGBA")
                    aspect = im.size[0] / im.size[1]
                    return im.resize((int(size * aspect), size), Image.Resampling.LANCZOS)
            except Exception as e:
                logger.error(f"Error processing {path}: {e}")
                return None

    def _load_icons_from_dir(self, directory=None):
        directory = directory or self.icons_dir
        if not os.path.isdir(directory):
            return
        for fn in os.listdir(directory):
            if fn.lower().endswith((".png", ".svg")):
                name = os.path.splitext(fn)[0].lower()
                path = os.path.join(directory, fn)
                img = self._process_file(path, self.load_size)
                if img:
                    self._icons[name] = img

    def _download_icon(self, name):
        """Fetch a missing icon as SVG from the Lucide CDN (pinned version) into cache_dir.
        Returns the file path, or None. A name Lucide does not have (404) is remembered with a
        '<name>.svg.404' marker, so it is not asked for again on every render; other failures
        (network) are only remembered for this process."""
        clean_name = name.lower().strip().replace(" ", "-")
        if not re.fullmatch(r"[a-z0-9-]+", clean_name):
            return None
        target_path = os.path.join(self.cache_dir, f"{clean_name}.svg")
        if os.path.isfile(target_path):
            return target_path
        marker = target_path + ".404"
        if clean_name in self._failed or os.path.isfile(marker):
            return None
        url = LUCIDE_URL.format(version=LUCIDE_VERSION, name=clean_name)
        try:
            logger.info(f"Downloading icon: {clean_name}...")
            r = requests.get(url, timeout=5)
        except Exception as e:
            logger.error(f"Download failed for {clean_name}: {e}")
            self._failed.add(clean_name)
            return None
        if r.status_code == 200 and b"<svg" in r.content:
            with open(target_path, "wb") as f:
                f.write(r.content)
            return target_path
        self._failed.add(clean_name)
        if r.status_code == 404:
            try:
                with open(marker, "w") as f:
                    f.write(url + "\n")
            except OSError:
                pass
        return None

    def get_icon_image(self, name, size=None):
        if not name: return None
        name = name.lower().strip()
        target_size = size or self.load_size

        if name in self._icons:
            img = self._icons[name]
            if img.size[1] != target_size:
                aspect = img.size[0] / img.size[1]
                return img.resize((int(target_size * aspect), target_size), Image.Resampling.LANCZOS)
            return img.copy()

        dl_path = self._download_icon(name)
        if dl_path:
            img = self._process_file(dl_path, target_size)
            if img:
                self._icons[name] = img
                return img
        return None

    def find_for_keyword(self, text, size=None):
        if not text: return None
        text_norm = text.lower()
        if text_norm in self._icons:
            return self.get_icon_image(text_norm, size)
        for icon_name in self._icons.keys():
            if icon_name in text_norm:
                return self.get_icon_image(icon_name, size)
        return None

_manager = None
def get_default_icon_manager():
    global _manager
    if _manager is None:
        _manager = IconManager()
    return _manager