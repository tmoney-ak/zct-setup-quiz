"""Make reading aids for each screenshot: an enlarged header strip (symbol, exchange, publish
time) and an enlarged time-axis strip, stacked into one image per trade.

usage: python crops.py <outdir of extract.py>
Writes <outdir>/read/NNN.png
"""
import sys, os
from PIL import Image

outdir = sys.argv[1]
os.makedirs(os.path.join(outdir, "read"), exist_ok=True)
for name in sorted(os.listdir(os.path.join(outdir, "shots"))):
    im = Image.open(os.path.join(outdir, "shots", name)).convert("RGB")
    w, h = im.size
    W = 1560
    head = im.crop((0, 0, int(w * 0.5), max(40, int(h * 0.075))))
    head = head.resize((W, int(head.height * W / head.width)), Image.LANCZOS)
    full = im.resize((W, int(h * W / w)), Image.LANCZOS)
    out = Image.new("RGB", (W, head.height + full.height + 6), (255, 0, 255))
    out.paste(head, (0, 0))
    out.paste(full, (0, head.height + 6))
    out.save(os.path.join(outdir, "read", name))
print("ok")
