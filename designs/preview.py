"""Render every design concept with the sample week: python -m designs.preview OUT_DIR"""
import importlib
import os
import sys

from designs.sample_data import sample_week

CONCEPTS = ["hero", "agenda", "band"]

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)
    names = sys.argv[2:] or CONCEPTS
    for name in names:
        try:
            mod = importlib.import_module(f"designs.{name}")
        except ModuleNotFoundError:
            continue
        img = mod.render(sample_week())
        p = os.path.join(out, f"design_{name}.png")
        img.save(p, optimize=True)
        print("wrote", p, img.size, f"{os.path.getsize(p)//1024} KB")
