# inky_icons_package.py
import os
import io
import logging
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

class IconManager:
    def __init__(self, icons_dir=None, load_size=24):
        self.icons_dir = icons_dir or ICONS_DIR
        self.load_size = load_size
        self._icons = {}
        
        if not os.path.exists(self.icons_dir):
            os.makedirs(self.icons_dir, exist_ok=True)
            
        self._load_icons_from_dir()
    
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
                            
    def _load_icons_from_dir(self):
        if not os.path.isdir(self.icons_dir):
            return
        for fn in os.listdir(self.icons_dir):
            if fn.lower().endswith((".png", ".svg")):
                name = os.path.splitext(fn)[0].lower()
                path = os.path.join(self.icons_dir, fn)
                img = self._process_file(path, self.load_size)
                if img:
                    self._icons[name] = img

    def _download_icon(self, name):
        """Try to fetch missing icon as SVG from Lucide CDN."""
        # Replace spaces with hyphens for the URL
        clean_name = name.lower().strip().replace(" ", "-")
        url = f"https://unpkg.com/lucide-static@latest/icons/{clean_name}.svg"
        target_path = os.path.join(self.icons_dir, f"{clean_name}.svg")
        
        try:
            logger.info(f"Downloading icon: {clean_name}...")
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                with open(target_path, "wb") as f:
                    f.write(r.content)
                return target_path
        except Exception as e:
            logger.error(f"Download failed for {clean_name}: {e}")
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