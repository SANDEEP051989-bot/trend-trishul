"""Option chain analysis: walls, put-call ratio, max pain, gamma (calm/fast market), expected move,
near-term fear, big trades, and the inputs of the Big Move Alarm.
Bitcoin uses Deribit (free, live). Gold uses GLD fund options from Yahoo, scaled to gold price."""
import math, re
from datetime import datetime, timezone, timedelta
import numpy as np

from . import data

UTC = timezone.utc
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def _npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_gamma(S, K, T, iv):
    if S <= 0 or K <= 0 or T <= 0 or iv <= 0:
        return 0.0
    d1 = (math.log(S / K) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    return _npdf(d1) / (S * iv * math.sqrt(T))


def _chain_btc():
    rows = data.deribit_options()
    if not rows:
        return None
    out = []
    now = datetime.now(UTC)
    for r in rows:
        m = re.match(r"BTC-(\d{1,2})([A-Z]{3})(\d{2})-(\d+)-([CP])", r["instrument_name"] or "")
        if not m:
            continue
        exp = datetime(2000 + int(m[3]), MONTHS[m[2]], int(m[1]), 8, tzinfo=UTC)
        T = (exp - now).total_seconds() / (365 * 86400)
        if T <= 0:
            continue
        out.append({"exp": exp, "T": T, "k": float(m[4]), "t": m[5], "oi": float(r["open_interest"] or 0),
                    "vol": float(r["volume"] or 0), "iv": float(r["mark_iv"] or 0) / 100,
                    "S": float(r["underlying_price"] or 0)})
    return out


def _chain_gold(gold_price):
    rows = data.gld_options()
    gld = data.yf_close("GLD", period="5d", interval="1d")
    if not rows or gld is None or not len(gld):
        return None
    ratio = gold_price / float(gld.iloc[-1])          # how many dollars of gold per $1 of GLD
    now = datetime.now(UTC)
    out = []
    for r in rows:
        exp = datetime.strptime(r["exp"], "%Y-%m-%d").replace(hour=20, tzinfo=UTC)
        T = (exp - now).total_seconds() / (365 * 86400)
        if T <= 0 or r["iv"] <= 0.01:
            continue
        # GLD option = 100 shares; express open interest in "gold dollars" by scaling strike to gold price
        out.append({"exp": exp, "T": T, "k": r["k"] * ratio, "t": r["t"], "oi": r["oi"], "vol": r["vol"],
                    "iv": r["iv"], "S": gold_price})
    return out


def analyse(asset, price):
    ch = _chain_btc() if asset == "btc" else _chain_gold(price)
    if not ch:
        return None
    S = price
    near = [r for r in ch if r["T"] * 365 <= 45]
    if not near:
        return None
    res = {}
    # ---- walls & put-call ratio (open interest within +-15% of price)
    band = [r for r in near if 0.85 * S <= r["k"] <= 1.15 * S]
    calls = {}
    puts = {}
    for r in band:
        (calls if r["t"] == "C" else puts).setdefault(r["k"], 0.0)
        if r["t"] == "C":
            calls[r["k"]] += r["oi"]
        else:
            puts[r["k"]] += r["oi"]
    above = {k: v for k, v in calls.items() if k >= S}
    below = {k: v for k, v in puts.items() if k <= S}
    res["call_wall"] = max(above, key=above.get) if above else None
    res["put_wall"] = max(below, key=below.get) if below else None
    coi, poi = sum(calls.values()), sum(puts.values())
    res["pcr_oi"] = poi / coi if coi else None
    cv = sum(r["vol"] for r in band if r["t"] == "C")
    pv = sum(r["vol"] for r in band if r["t"] == "P")
    res["pcr_vol"] = pv / cv if cv else None

    # ---- max pain for the biggest expiry in the next 10 days
    exps = {}
    for r in near:
        exps.setdefault(r["exp"], 0.0)
        exps[r["exp"]] += r["oi"]
    soon = {e: v for e, v in exps.items() if (e - datetime.now(UTC)).days <= 10}
    if soon:
        e = max(soon, key=soon.get)
        rows = [r for r in near if r["exp"] == e]
        strikes = sorted({r["k"] for r in rows})
        def pain(x):
            return sum(r["oi"] * (max(0, x - r["k"]) if r["t"] == "C" else max(0, r["k"] - x)) for r in rows)
        res["max_pain"] = min(strikes, key=pain) if strikes else None
        res["max_pain_exp"] = e.isoformat()
        res["max_pain_oi_share"] = soon[e] / sum(exps.values())

    # ---- gamma: net dealer gamma now and the switch (flip) price
    def net_gex(spot):
        g = 0.0
        for r in near:
            gm = bs_gamma(spot, r["k"], r["T"], r["iv"]) * r["oi"] * spot * spot * 0.01
            g += gm if r["t"] == "C" else -gm
        return g
    res["gex"] = net_gex(S)
    grid = np.linspace(0.9 * S, 1.1 * S, 41)
    vals = [net_gex(x) for x in grid]
    flip = None
    for i in range(1, len(grid)):
        if vals[i - 1] == 0 or np.sign(vals[i - 1]) != np.sign(vals[i]):
            x0, x1, y0, y1 = grid[i - 1], grid[i], vals[i - 1], vals[i]
            cand = x0 - y0 * (x1 - x0) / (y1 - y0) if y1 != y0 else x0
            if flip is None or abs(cand - S) < abs(flip - S):
                flip = cand
    res["gamma_flip"] = flip

    # ---- ATM IV near vs far -> expected move and near-term fear
    def atm_iv(lo_d, hi_d):
        rows = [r for r in ch if lo_d <= r["T"] * 365 <= hi_d and r["iv"] > 0]
        if not rows:
            return None, None
        e = min({r["exp"] for r in rows})
        rows = [r for r in rows if r["exp"] == e]
        k = min(rows, key=lambda r: abs(r["k"] - S))["k"]
        ivs = [r["iv"] for r in rows if r["k"] == k]
        return float(np.mean(ivs)), (e - datetime.now(UTC)).total_seconds() / 86400
    iv_n, d_n = atm_iv(1.5, 14)
    iv_f, d_f = atm_iv(25, 70)
    res["iv_near"], res["iv_far"] = iv_n, iv_f
    if iv_n:
        res["exp_move_day"] = S * iv_n * math.sqrt(1 / 365)
        res["exp_move_week"] = S * iv_n * math.sqrt(7 / 365)
    res["term_ratio"] = iv_n / iv_f if iv_n and iv_f else None

    # ---- big new option trades
    if asset == "btc":
        big = data.deribit_big_trades() or []
        score = 0.0
        n = 0
        for t in big:
            kind = t["instrument_name"][-1]
            s = 1 if t["direction"] == "buy" else -1
            score += (s if kind == "C" else -s) * float(t["amount"])
            n += 1
        res["big_trades_n"], res["big_trades_score"] = n, score
    else:
        hot = [r for r in near if r["vol"] >= 2000 and r["vol"] > 2 * max(r["oi"], 1)]
        score = sum((1 if r["t"] == "C" else -1) * r["vol"] for r in hot)
        res["big_trades_n"], res["big_trades_score"] = len(hot), score

    # ---- implied volatility history (for IV rank and "rising while price quiet")
    if asset == "btc":
        h = data.deribit_dvol() or []
        hist = [v for _, v in h]
    else:
        g = data.yf_close("^GVZ", period="2y")
        hist = [] if g is None else g.dropna().tolist()[-260:]
    if len(hist) > 30:
        lo, hi = min(hist[-252:]), max(hist[-252:])
        res["iv_rank"] = (hist[-1] - lo) / (hi - lo) * 100 if hi > lo else None
        res["iv_now"] = hist[-1]
        res["iv_3d_change"] = (hist[-1] / hist[-4] - 1) * 100 if hist[-4] else None
    return res
