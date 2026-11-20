"""Pull the answer key and the trade screenshots out of one '100 screenshots' PDF.

usage: python extract.py <pdf> <outdir> <kind>

Trade N is always on page N+6 (pages 1-6 are the introduction). The "Trade #N: link"
heading can sit at the bottom of the previous page, so headings are never used to number
a page; links are taken in document order instead.

Writes <outdir>/key.json, <outdir>/shots/NNN.png (the trade screenshot: top-most image on
the page) and <outdir>/extras/NNN-K.png (any further illustrations on that page).
"""
import sys, os, re, json
import pymupdf as fitz

pdf, outdir, kind = sys.argv[1], sys.argv[2], sys.argv[3]
for d in ("shots", "extras", "intro"):
    os.makedirs(os.path.join(outdir, d), exist_ok=True)
doc = fitz.open(pdf)
FIRST = 6            # index of the first trade page
MARKS = {"✅": "yes", "❌": "no", "⚠": "mid"}
STRIP = "[✅❌⚠️​]"
LINK = r"https://www\.tradingview\.com/x/\w+/?"


def save(xref, path):
    pix = fitz.Pixmap(doc, xref)
    if pix.n - pix.alpha >= 4:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    pix.save(path)
    return [pix.width, pix.height]


def images(page):
    out = []
    for img in page.get_images(full=True):
        info = doc.extract_image(img[0])
        if info["width"] == 500 and info["height"] == 500:      # ZCT logo
            continue
        rects = page.get_image_rects(img[0])
        out.append((rects[0].y0 if rects else 0, img[0]))
    return [x for _, x in sorted(out)]


# links in document order, de-duplicated
links = []
for page in list(doc)[FIRST:]:
    for l in re.findall(LINK, page.get_text()):
        l = l.rstrip("/") + "/"
        if l not in links:
            links.append(l)

trades, problems = [], []
for pno in range(FIRST, len(doc)):
    page, n = doc[pno], pno - FIRST + 1
    lines = [re.sub("​", "", l).strip() for l in page.get_text().splitlines()]
    lines = [l for l in lines if l]
    qs, notes, mode = [], [], None
    for l in lines:
        if re.match(r"Trade\s*#\s*\d+\s*:", l) or re.match(LINK, l):
            mode = None
            continue
        if re.match(r"(Did|Was|Were|Is|Does)\b", l):
            qs.append(l)
            mode = "q"
        elif re.match(r"NOTE", l):
            rest = re.sub(r"^NOTE[^:]*:\s*", "", l)
            mode = "n"
            if rest:
                notes.append(rest)
        elif mode == "q":
            qs[-1] += " " + l
        elif mode == "n":
            if l.startswith("●"):
                notes.append(l.lstrip("●").strip())
            elif notes:
                notes[-1] = (notes[-1] + " " + l).strip()
            else:
                notes.append(l)
    marks = []
    for q in qs:
        found = [v for k, v in MARKS.items() if k in q]
        mark = found[0] if len(found) == 1 else None
        extra = re.sub(STRIP, "", re.sub(r"^[^?]*\?", "", q)).strip()
        if mark is None and re.search(r"unclear", extra, re.I):
            mark = "mid"
        marks.append({"q": re.sub(STRIP, "", q.split("?")[0]).strip() + "?", "mark": mark, "extra": extra})
    xs = images(page)
    size = save(xs[0], os.path.join(outdir, "shots", f"{n:03d}.png")) if xs else [0, 0]
    for k, x in enumerate(xs[1:], 1):
        save(x, os.path.join(outdir, "extras", f"{n:03d}-{k}.png"))
    if not xs:
        problems.append(f"#{n}: no image")
    if len(marks) != 3 or any(m["mark"] is None for m in marks):
        problems.append(f"#{n} p{pno+1}: marks={[(m['q'][:34], m['mark']) for m in marks]}")
    trades.append({"n": n, "kind": kind, "page": pno + 1, "link": links[n - 1] if n <= len(links) else None,
                   "marks": marks, "notes": notes, "img": size, "extras": len(xs) - 1})

# teaching images from the introduction
for pno in range(FIRST):
    for k, x in enumerate(images(doc[pno]), 1):
        save(x, os.path.join(outdir, "intro", f"p{pno+1}-{k}.png"))

json.dump(trades, open(os.path.join(outdir, "key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
open(os.path.join(outdir, "problems.txt"), "w", encoding="utf-8").write("\n".join(problems))
tally = {}
for t in trades:
    key = "".join({"yes": "Y", "mid": "m", "no": "N", None: "?"}[m["mark"]] for m in t["marks"])
    tally[key] = tally.get(key, 0) + 1
print(kind, "trades", len(trades), "links", len(links), "problems", len(problems), "| mark patterns", dict(sorted(tally.items(), key=lambda kv: -kv[1])))
