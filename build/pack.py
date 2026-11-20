"""Convert the extracted screenshots into web-sized images for the page.

usage: python pack.py
Writes shots/<set>/NNN.webp (the coach's marked-up screenshot) and shots/<set>/NNN-K.webp
(extra illustrations from that trade's page), at most 1600 px wide.
"""
import os, glob
from PIL import Image

BUILD = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BUILD)
total = 0
for key in ("momo", "mr"):
    out = os.path.join(ROOT, "shots", key)
    os.makedirs(out, exist_ok=True)
    for sub in ("shots", "extras"):
        for p in sorted(glob.glob(os.path.join(BUILD, key, sub, "*.png"))):
            im = Image.open(p).convert("RGB")
            if im.width > 1600:
                im = im.resize((1600, round(im.height * 1600 / im.width)), Image.LANCZOS)
            dst = os.path.join(out, os.path.splitext(os.path.basename(p))[0] + ".webp")
            im.save(dst, "WEBP", quality=80, method=6)
            total += os.path.getsize(dst)
print(f"images packed: {total / 1e6:.1f} MB")
