import os
import requests
from datetime import datetime

# --- Configuration copied from layout_renderer.py ---
# Ensure these match the paths used by the renderer script
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
ICONS_DIR = os.path.join(ASSETS_DIR, "icons")

# Base URL pointing to the modern Material Symbols repository (rounded, 24px filled)
MD_ICONS_BASE_URL = "https://raw.githubusercontent.com/google/material-symbols/main/png/24px/symbols/rounded/"

# --- List of commonly used icon names (use these names from fonts.google.com/icons) ---
KNOWN_MATERIAL_SYMBOLS = [
    # UI and Status
    "home", "settings", "menu", "close", "search", "check", "delete", 
    "favorite", "add", "edit", "info", "warning", "error", "visibility", 
    "lock", "alarm", "schedule", "calendar_today", "event", "star",
    
    # Transportation and Activity
    "directions_run", "directions_bike", "directions_car", "local_parking", 
    "airport_shuttle", "hiking", "bike_scooter", "fitness_center", 
    
    # Weather and Nature
    "wb_sunny", "cloud", "nights_stay", "partly_cloudy_day", "partly_cloudy_night",
    "cloudy_snowing", "ac_unit", "thunderstorm", "foggy", "thermostat", 
    "air", "wind_power", "water_drop", "light_mode", "dark_mode",
    
    # Places and Objects
    "place", "map", "mail", "person", "shopping_cart", "local_dining", 
    "local_laundry_service", "pets", "school", "work", "recycling", "delete_sweep",
    
    # The icon requested in previous turns (should now resolve)
    "sledding",
]
# -----------------------------------------------------------------------------------

def _ensure_icon_dir():
    """Ensure the icons directory exists."""
    if not os.path.exists(ICONS_DIR):
        try:
            os.makedirs(ICONS_DIR)
            print(f"[INFO] Created icon directory: {ICONS_DIR}")
        except OSError as e:
            print(f"[ERROR] Could not create icon directory {ICONS_DIR}: {e}")
            return False
    return True

def download_all_icons(icon_list):
    """
    Attempts to download a list of icons from the remote source and cache them locally.
    """
    if not _ensure_icon_dir():
        return

    success_count = 0
    fail_count = 0
    
    print(f"\n--- Starting icon download from: {MD_ICONS_BASE_URL} ---")

    for icon_base_name in icon_list:
        icon_base_name = icon_base_name.lower().replace('-', '_')
        md_filename = f"{icon_base_name}.png"
        download_url = MD_ICONS_BASE_URL + md_filename 
        file_path = os.path.join(ICONS_DIR, f"{icon_base_name}.png")
        fail_path = os.path.join(ICONS_DIR, f"{icon_base_name}.png.404_fail")

        if os.path.exists(file_path):
            print(f"  [SKIP] {icon_base_name}.png already exists locally.")
            success_count += 1
            continue

        if os.path.exists(fail_path):
            print(f"  [SKIP] {icon_base_name}.png previously failed to download (404 cached).")
            fail_count += 1
            continue

        try:
            response = requests.get(download_url, timeout=5)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            with open(file_path, 'wb') as f:
                f.write(response.content)
                
            print(f"  [OK] Downloaded and cached {icon_base_name}.png")
            success_count += 1
            
            if os.path.exists(fail_path):
                os.remove(fail_path) # Clear failure cache on success

        except requests.exceptions.HTTPError as err:
            # Cache this failure to prevent repeat requests for missing icons
            try:
                with open(fail_path, 'w') as f:
                    f.write(str(datetime.now()))
            except Exception:
                pass
            print(f"  [FAIL] {icon_base_name}.png not found (HTTP Error {err.response.status_code}).")
            fail_count += 1
        except requests.exceptions.RequestException as err:
            print(f"  [ERROR] Connection error for {icon_base_name}: {err}")
            fail_count += 1
        except Exception as e:
            print(f"  [ERROR] Unexpected error saving icon {icon_base_name}: {e}")
            fail_count += 1
            
    print(f"\n--- Icon Download Summary ---")
    print(f"Successful downloads: {success_count}")
    print(f"Failures (404/Connection): {fail_count}")
    print(f"Check the '{ICONS_DIR}' directory to see available icons.")

if __name__ == '__main__':
    download_all_icons(KNOWN_MATERIAL_SYMBOLS)