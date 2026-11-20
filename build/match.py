"""Align every screenshot's trade with real 1-minute candles and write the quiz data.

usage: python match.py [momo|mr] [trade numbers...]

For each trade read off a screenshot (build/<set>/meta/*.json) this:
  1. loads 1-minute candles from the exchange named on the screenshot (Binance or Bybit futures),
  2. checks the chart's time axis against the candles using the price samples read across the
     chart, and searches other UTC offsets if the screenshot's own offset does not fit,
  3. finds the entry candle (first candle near the read entry time that holds the entry price),
  4. works out how the trade ended (target, stop, or closed in between),
  5. writes data/<set>/NNN.js (candles + moving averages) and data/<set>.js (the list).

Everything it is unsure about is recorded in build/<set>/aligned.json under "flags".
"""
import sys, os, re, json, glob, time, urllib.request, urllib.error
import datetime as dt

BUILD = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BUILD)
CACHE = os.path.join(BUILD, "cache")
MIN, DAY = 60_000, 86_400_000
LOOKBACK = 480        # candles shown before the entry (8 hours: the doc's "previous 4-8 hrs")
WARM = 1000           # extra candles before that, so the moving averages have settled
MAX_AFTER = 480       # longest a trade is followed after the entry
GOOD = 0.10           # a time-axis fit below this is accepted without searching further
HOLD = r"weak time-axis|more than one date|min from the time|% outside the candles|wrong side|reading says|stop or target missing"
# A coach's own verdicts after checking a trade in the review page win over the automatic rule:
# build/decisions.json = {"momo": {"release": [12], "hold": [40]}, "mr": {"release": [23], "hold": []}}
DECISIONS = os.path.join(BUILD, "decisions.json")


def ms(s):
    """'YYYY-MM-DD HH:MM' read as if it were UTC."""
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})", str(s or ""))
    if not m:
        return None
    y, mo, d, h, mi = map(int, m.groups())
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc).timestamp() * 1000)


def http(url, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "candle-fetch"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(1.5 * (k + 1))
        except Exception:
            time.sleep(1.5 * (k + 1))
    raise RuntimeError("no answer from " + url)


def day_bars(exchange, sym, day):
    """One UTC day of 1-minute candles as {openMs: [o, h, l, c, usdVolume]}, cached on disk."""
    path = os.path.join(CACHE, f"{exchange}_{sym}_{day // DAY}.json")
    if os.path.exists(path):
        return {int(k): v for k, v in json.load(open(path)).items()}
    out = {}
    if exchange == "BINANCE":
        rows = http(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1m&startTime={day}&endTime={day + DAY - 1}&limit=1500")
        for k in rows or []:
            out[int(k[0])] = [float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[7])]
    else:
        for s in (day, day + DAY // 2):
            j = http(f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval=1&start={s}&end={s + DAY // 2 - 1}&limit=1000")
            for k in ((j or {}).get("result") or {}).get("list") or []:
                out[int(k[0])] = [float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[6])]
    complete = day + DAY < time.time() * 1000
    if complete:
        os.makedirs(CACHE, exist_ok=True)
        json.dump(out, open(path, "w"))
    return out


def bars_between(exchange, sym, s, e):
    out = {}
    for day in range(s // DAY * DAY, e + 1, DAY):
        out.update(day_bars(exchange, sym, day))
    return {t: v for t, v in out.items() if s <= t <= e}


def ticker(m):
    s = re.sub(r"\.P$|PERP$", "", str(m.get("symbol") or "").upper().strip())
    s = re.sub(r"[^A-Z0-9]", "", s)
    if not s:
        base = re.sub(r"[^A-Z0-9]", "", str(m.get("pair_text") or "").split("/")[0].upper())
        s = base + "USDT"
    if not re.search(r"(USDT|USDC|USD)$", s):
        s += "USDT"
    return s


def envelope_miss(bars, t, p, tol, step=MIN):
    """How far price p is from the candles within tol candles of t (0 if a candle holds it)."""
    best, t = None, t // step * step
    for k in range(-tol, tol + 1):
        b = bars.get(t + k * step)
        if b:
            miss = 0.0 if b[2] <= p <= b[1] else min(abs(p - b[1]), abs(p - b[2]))
            best = miss if best is None else min(best, miss)
    return best


def fit(bars, m, shift, tf, step=MIN):
    """Mean miss of the chart's price samples against the candles when chart time = UTC + shift (ms).
    0 = every sample sits inside a candle. step is the candles' size (1 minute, or 15 for the day search)."""
    pts = [(ms(t), float(p)) for t, p in (m.get("path") or []) if ms(t) is not None and p is not None]
    plan = [float(x) for x in (m.get("entry_price"), m.get("stop_price"), m.get("target_price")) if x is not None]
    prices = [p for _, p in pts] + plan
    if len(pts) < 4:
        return None
    span = max(max(prices) - min(prices), 0.002 * max(prices))
    fine = step == MIN
    tol = (3 if tf <= 1 else int(tf * 1.5)) if fine else 0
    errs = []
    for t, p in pts:
        miss = envelope_miss(bars, t - shift, p, tol, step)
        if miss is not None:
            errs.append(min(1.0, miss / span))
    if len(errs) < max(4, len(pts) - 2):
        return None
    et, ep = ms(m.get("entry_time")), m.get("entry_price")
    if et is not None and ep is not None:
        miss = envelope_miss(bars, et - shift, float(ep), (8 if tf <= 1 else tf + 3) if fine else 0, step)
        if miss is not None:
            errs += [min(1.0, miss / span)] * 3
    return sum(errs) / len(errs)


def coarse_bars(exchange, sym, s, e):
    """15-minute candles over a long span as {openMs: [o, h, l, c]}, cached on disk."""
    path = os.path.join(CACHE, f"{exchange}_{sym}_15m_{s // DAY}_{e // DAY}.json")
    if os.path.exists(path):
        return {int(k): v for k, v in json.load(open(path)).items()}
    out, step, t = {}, 15 * MIN, s
    while t < e:
        if exchange == "BINANCE":
            rows = http(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=15m&startTime={t}&endTime={e}&limit=1500")
            if not rows:
                break
            for k in rows:
                out[int(k[0])] = [float(k[1]), float(k[2]), float(k[3]), float(k[4])]
            t = int(rows[-1][0]) + step
            if len(rows) < 1500:
                break
        else:
            j = http(f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval=15&start={t}&end={min(e, t + 1000 * step - 1)}&limit=1000")
            for k in ((j or {}).get("result") or {}).get("list") or []:
                out[int(k[0])] = [float(k[1]), float(k[2]), float(k[3]), float(k[4])]
            t += 1000 * step
    os.makedirs(CACHE, exist_ok=True)
    json.dump(out, open(path, "w"))
    return out


DAYS_BACK = 92


def day_search(exchange, sym, m, tf, et_local, off0, latest_utc):
    """A chart scrolled back to an earlier day shows clock times but no date. Try every day in the
    three months before the date read, at every whole-hour offset, against 15-minute candles and
    return the best few as (score, shift_ms, offset_h, days)."""
    s = (et_local - (DAYS_BACK + 3) * DAY) // DAY * DAY
    cb = coarse_bars(exchange, sym, s, (et_local + 3 * DAY) // DAY * DAY)
    if len(cb) < 50:
        return []
    best = {}
    for d in range(-DAYS_BACK, 2):
        for o in sorted(set(list(range(-12, 15)) + [off0])):
            shift = int(o * 3600_000) - d * DAY
            if latest_utc is not None and et_local - shift > latest_utc + 3600_000:
                continue                                     # the trade cannot be after the screenshot was published
            sc = fit(cb, m, shift, tf, 15 * MIN)
            if sc is None:
                continue
            sc += 0 if o == off0 else 0.03                   # prefer the screenshot's own offset
            if shift not in best or sc < best[shift][0]:
                best[shift] = (sc, shift, o, d)
    return sorted(best.values())[:6]


def aliases(sym):
    """Small-priced coins trade as 1000X contracts on the futures exchanges (prices x1000)."""
    out = [(sym, 1)]
    if not re.match(r"(1000|1M)", sym):
        out.append(("1000" + sym, 1000))
    return out


def scale_prices(m, f):
    if f == 1:
        return m
    mm = dict(m)
    for k in ("entry_price", "stop_price", "target_price"):
        if mm.get(k) is not None:
            mm[k] = float(mm[k]) * f
    mm["path"] = [[t, float(p) * f] for t, p in (m.get("path") or []) if p is not None]
    return mm


def smma(vals, n):
    out, prev = [], None
    for i, v in enumerate(vals):
        if i < n - 1:
            out.append(None)
        elif i == n - 1:
            prev = sum(vals[:n]) / n
            out.append(prev)
        else:
            prev = (prev * (n - 1) + v) / n
            out.append(prev)
    return out


def sma(vals, n):
    out, run = [], 0.0
    for i, v in enumerate(vals):
        run += v
        if i >= n:
            run -= vals[i - n]
        out.append(run / n if i >= n - 1 else None)
    return out


def sig(x, n=6):
    return None if x is None else float(f"{x:.{n}g}")


def align(m, key):
    """Returns (record for aligned.json, payload for the data file or None)."""
    flags, n = [], m["n"]
    rec = {"n": n, "flags": flags}
    tf = int(re.sub(r"\D", "", str(m.get("timeframe") or "1")) or 1)
    side = str(m.get("side") or "").lower()
    E, S, T = m.get("entry_price"), m.get("stop_price"), m.get("target_price")
    et_local, off0 = ms(m.get("entry_time")), m.get("utc_offset")
    if side not in ("long", "short") or E is None or et_local is None:
        flags.append("FATAL: side, entry price or entry time missing from the reading")
        return rec, None
    off0 = float(off0 or 0)
    sym = ticker(m)
    stated = str(m.get("exchange") or "").upper()
    order = ["BYBIT", "BINANCE"] if "BYBIT" in stated else ["BINANCE", "BYBIT"]
    if stated and not any(x in stated for x in ("BINANCE", "BYBIT")):
        flags.append(f"screenshot is from {stated}: prices can differ slightly")

    pub = ms(m.get("published"))
    latest = pub - int(off0 * 3600_000) if pub is not None else None
    sh0 = int(off0 * 3600_000)
    # candles for checking a hypothesis: the whole width of the screenshot (some are zoomed out to a day or more)
    pts = [ms(t) for t, _ in (m.get("path") or []) if ms(t) is not None] + [et_local]
    w_lo = max(min(pts), et_local - 3 * DAY) - 30 * MIN
    w_hi = min(max(pts), et_local + 2 * DAY) + 30 * MIN
    around = lambda ex, sy, sh: bars_between(ex, sy, min(w_lo, et_local - 11 * 60 * MIN) - sh, max(w_hi, et_local + 9 * 60 * MIN) - sh)
    chosen = None
    for exch in order:
        for sym2, factor in aliases(sym):
            mm, hyps = scale_prices(m, factor), []
            near = around(exch, sym2, sh0)
            sc = fit(near, mm, sh0, tf) if len(near) >= 300 else None
            if sc is not None:
                hyps.append((sc, sh0, off0, 0))
            if sc is None or sc >= GOOD:
                # the date or offset read off the screenshot does not fit: look for the day that does
                for _, sh, o, d in day_search(exch, sym2, mm, tf, et_local, off0, latest):
                    if sh == sh0:
                        continue
                    nb = around(exch, sym2, sh)
                    s1 = fit(nb, mm, sh, tf) if len(nb) >= 300 else None
                    if s1 is not None:
                        hyps.append((s1 + (0 if o == off0 else 0.03), sh, o, d))
            if not hyps:
                continue
            hyps.sort()
            # a second date counts as a rival only if it fits about as well as the best one
            twin = len(hyps) > 1 and hyps[0][0] < GOOD and hyps[1][0] < max(0.02, hyps[0][0] * 2.5)
            rec["hyps"] = [[round(h[0], 3), h[2], h[3]] for h in hyps[:3]]
            cand = (hyps[0][0], exch, sym2, factor, hyps[0][1], hyps[0][2], hyps[0][3], twin)
            if chosen is None or cand[0] < chosen[0]:
                chosen = cand
            if chosen[0] < GOOD:
                break
        if chosen is not None and chosen[0] < GOOD:
            break
    if chosen is None:
        flags.append(f"FATAL: no {sym} candles on Binance or Bybit around that time")
        return rec, None
    score, exch, sym, factor, shift, off, dshift, twin = chosen
    m = scale_prices(m, factor)
    E, S, T = m.get("entry_price"), m.get("stop_price"), m.get("target_price")
    rec.update(symbol=sym, exchange=exch, fit=round(score, 3), utc_offset=off, day_shift=dshift)
    if factor != 1:
        flags.append(f"prices are x{factor}: the futures contract is {sym}")
    if dshift:
        flags.append(f"date set by matching candles: {abs(dshift)} day{'s' if abs(dshift) > 1 else ''} {'before' if dshift < 0 else 'after'} the date read off the screenshot")
    if off != off0:
        flags.append(f"time axis fits UTC{off:+g}, not the screenshot's UTC{off0:+g}")
    if twin:
        flags.append("more than one date fits the chart: check against the screenshot")
    if score >= GOOD:
        flags.append(f"weak time-axis fit ({score:.2f}): check against the screenshot")
    if exch not in stated:
        flags.append(f"candles from {exch.title()} (screenshot: {stated or 'unknown'})")

    et = et_local - shift
    bars = bars_between(exch, sym, et - (LOOKBACK + WARM + 20) * MIN, et + (MAX_AFTER + 140) * MIN)
    E = float(E)
    lo_w, hi_w = (et - 8 * MIN, et + 8 * MIN) if tf <= 1 else (et - 3 * MIN, et + (tf + 3) * MIN)
    tol = E * 0.0003
    holds = lambda t: t in bars and bars[t][2] - tol <= E <= bars[t][1] + tol
    cands = [t for t in range(lo_w, hi_w + 1, MIN) if holds(t)]
    scale = 1.0
    if cands:
        t0 = min(cands, key=lambda t: (abs(t - et), t)) if tf <= 1 else cands[0]
        for _ in range(3):                      # first candle of the run that reaches the entry price
            if holds(t0 - MIN) and t0 - MIN >= lo_w:
                t0 -= MIN
    else:
        near = [t for t in range(lo_w, hi_w + 1, MIN) if t in bars]
        if not near:
            flags.append("FATAL: no candles at the entry time")
            return rec, None
        dist = lambda t: min(abs(E - bars[t][1]), abs(E - bars[t][2]))
        t0 = min(near, key=lambda t: (dist(t), abs(t - et)))
        b = bars[t0]
        snapped = min(max(E, b[2]), b[1])
        scale = snapped / E
        gap = abs(1 - scale) * 100
        flags.append(f"entry {E:g} is {gap:.2f}% off the candles (another exchange's price): plan moved onto the candle" if gap < 0.3
                     else f"entry {E:g} is {gap:.2f}% outside the candles near the entry time: plan moved onto the candle")
    rec["entry_shift_min"] = (t0 - et) // MIN
    if abs(t0 - et) > 4 * MIN and tf <= 1:
        flags.append(f"entry candle is {abs(t0 - et) // MIN} min from the time read off the screenshot")

    E2 = E * scale
    S2 = float(S) * scale if S is not None else None
    T2 = float(T) * scale if T is not None else None
    sgn = 1 if side == "long" else -1
    if S2 is not None and (S2 - E2) * sgn >= 0:
        flags.append("stop is on the wrong side of the entry for a " + side)
        S2 = None
    if T2 is not None and (T2 - E2) * sgn <= 0:
        flags.append("target is on the wrong side of the entry for a " + side)
        T2 = None
    if S2 is None or T2 is None:
        flags.append("stop or target missing: the trade is played forward without a result")

    # how it ended: first touch of target or stop after the entry
    seen = str(m.get("outcome_seen") or "")
    xt_local = ms(m.get("exit_time"))
    xt = xt_local - shift if xt_local is not None else None

    def resolve(start):
        t = start
        while t <= t0 + MAX_AFTER * MIN:
            b = bars.get(t)
            if b:
                hit_t = T2 is not None and (b[1] >= T2 if sgn > 0 else b[2] <= T2)
                hit_s = S2 is not None and (b[2] <= S2 if sgn > 0 else b[1] >= S2)
                if hit_t and hit_s:
                    return ("target" if seen == "target" else "stop"), t, True
                if hit_t:
                    return "target", t, False
                if hit_s:
                    return "stop", t, False
            t += MIN
        return None, None, False

    a = resolve(t0)
    b2 = resolve(t0 + MIN)
    res, rt, both = a if (a[0] == seen or a[0] == b2[0] or b2[0] is None) else b2
    if both:
        flags.append("target and stop inside the same candle: result taken from the screenshot")
    out = {"type": "open", "t": None, "r": None}
    risk = abs(E2 - S2) if S2 is not None else None
    manual = seen == "between" and xt is not None and xt > t0 and (rt is None or xt < rt - 2 * MIN)
    if manual and xt in bars:
        px = bars[xt][3]
        out = {"type": "manual", "t": xt, "r": round((px - E2) * sgn / risk, 2) if risk else None, "price": px}
    elif res == "target":
        out = {"type": "target", "t": rt, "r": round(abs(T2 - E2) / risk, 2) if risk else None}
    elif res == "stop":
        out = {"type": "stop", "t": rt, "r": -1.0}
    if seen in ("target", "stop") and out["type"] in ("target", "stop") and out["type"] != seen:
        flags.append(f"candles say {out['type']}, the screenshot reading says {seen}")
    if out["type"] == "open" and S2 is not None and T2 is not None:
        flags.append(f"neither target nor stop reached within {MAX_AFTER // 60} hours")
    rec["outcome"] = out["type"]

    # the candles to ship: LOOKBACK before the entry, then to the exit plus a tail
    end_t = out["t"] if out["t"] is not None else t0 + 120 * MIN
    tail = max(20, int((end_t - t0) / MIN * 0.25))
    first, last = t0 - LOOKBACK * MIN, min(end_t + tail * MIN, t0 + (MAX_AFTER + 120) * MIN)
    series = sorted(t for t in bars if first - WARM * MIN <= t <= last)
    closes, vols = [bars[t][3] for t in series], [bars[t][4] for t in series]
    m30, m120, va = smma(closes, 30), smma(closes, 120), sma(vols, 60)
    keep = [i for i, t in enumerate(series) if t >= first]
    ts = [series[i] for i in keep]
    missing = (ts[-1] - ts[0]) // MIN + 1 - len(ts) if ts else 0
    if not ts or ts[0] > first + 30 * MIN:
        flags.append("FATAL: fewer than 7.5 hours of candles before the entry (coin newly listed?)")
        return rec, None
    if missing:
        flags.append(f"{missing} one-minute candles missing from the exchange data")
    idx = {t: i for i, t in enumerate(ts)}
    payload = {
        "k": key, "n": n, "ts": ts if missing else None, "t": ts[0], "i": idx[t0],
        "x": idx.get(out["t"]) if out["t"] is not None else None,
        "b": [[bars[t][0], bars[t][1], bars[t][2], bars[t][3], round(bars[t][4])] for t in ts],
        "a": [sig(m30[i]) for i in keep], "s": [sig(m120[i]) for i in keep], "v": [None if va[i] is None else round(va[i]) for i in keep],
    }
    if not missing:
        del payload["ts"]
    rec.update(entry_ms=t0, entry=sig(E2, 8), stop=sig(S2, 8) if S2 is not None else None, target=sig(T2, 8) if T2 is not None else None,
               side=side, tf=tf, r=out["r"], exit_price=out.get("price"), candles=len(ts))
    return rec, payload


def main():
    key = sys.argv[1]
    only = set(int(x) for x in sys.argv[2:])
    metas = {}
    for f in sorted(glob.glob(os.path.join(BUILD, key, "meta", "*.json"))):
        for m in json.load(open(f, encoding="utf-8")):
            metas[int(m["n"])] = m
    answers = {t["n"]: t for t in json.load(open(os.path.join(BUILD, key, "key.json"), encoding="utf-8"))}
    apath = os.path.join(BUILD, key, "aligned.json")
    aligned = {r["n"]: r for r in json.load(open(apath, encoding="utf-8"))} if os.path.exists(apath) else {}
    os.makedirs(os.path.join(ROOT, "data", key), exist_ok=True)
    for n in sorted(metas):
        if only and n not in only:
            continue
        try:
            rec, payload = align(metas[n], key)
        except Exception as e:                     # one bad trade must not stop the rest
            rec, payload = {"n": n, "flags": [f"FATAL: {type(e).__name__}: {e}"]}, None
        aligned[n] = rec
        out = os.path.join(ROOT, "data", key, f"{n:03d}.js")
        if payload:
            open(out, "w", encoding="utf-8").write("zctTrade(" + json.dumps(payload, separators=(",", ":")) + ");\n")
        elif os.path.exists(out):
            os.remove(out)
        print(f"{key} #{n:<3} {rec.get('symbol', '?'):<16} fit={rec.get('fit')} shift={rec.get('entry_shift_min')} {rec.get('outcome', '')} {'; '.join(rec['flags'])}")
    json.dump([aligned[n] for n in sorted(aligned)], open(apath, "w", encoding="utf-8"), indent=1)

    # the list the page loads: one entry per usable trade, with the answer key
    decided = (json.load(open(DECISIONS, encoding="utf-8")) if os.path.exists(DECISIONS) else {}).get(key, {})
    trades = []
    for n in sorted(aligned):
        r, a, m = aligned[n], answers[n], metas.get(n, {})
        if "entry_ms" not in r:
            continue
        extras = sorted(os.path.basename(p) for p in glob.glob(os.path.join(BUILD, key, "extras", f"{n:03d}-*.png")))
        trades.append({
            "n": n, "coin": re.sub(r"(USDT|USDC|USD)$", "", r["symbol"]), "quote": re.search(r"(USDT|USDC|USD)$", r["symbol"]).group(1),
            "exchange": r["exchange"].title(), "side": r["side"], "off": r["utc_offset"], "tf": r["tf"],
            "t": r["entry_ms"], "entry": r["entry"], "stop": r["stop"], "target": r["target"],
            "out": r["outcome"], "r": r["r"], "xp": r.get("exit_price"),
            "key": [x["mark"] for x in a["marks"]], "said": [x["extra"] for x in a["marks"]], "notes": a["notes"],
            "link": a["link"], "extras": len(extras), "flags": [f for f in r["flags"]],
            # held back from the quiz until someone has checked it against the screenshot
            "hold": (n in decided.get("hold", [])) or (n not in decided.get("release", []) and any(re.search(HOLD, f) for f in r["flags"])),
        })
    json_text = json.dumps({"kind": key, "trades": trades}, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(ROOT, "data", key + ".js"), "w", encoding="utf-8").write("zctSet(" + json_text + ");\n")
    fatal = [n for n in sorted(aligned) if any(f.startswith("FATAL") for f in aligned[n]["flags"])]
    flagged = [n for n in sorted(aligned) if aligned[n]["flags"] and n not in fatal]
    print(f"\n{key}: held back from the quiz: {[t['n'] for t in trades if t['hold']]}")
    print(f"{key}: {len(trades)} usable of {len(aligned)} read | clean {len(aligned) - len(fatal) - len(flagged)} | flagged {len(flagged)}: {flagged} | unusable {len(fatal)}: {fatal}")


if __name__ == "__main__":
    main()
