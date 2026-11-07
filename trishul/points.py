"""The Final 50 points (plus extra points for the full report), each in plain words.
Every point gives: a vote (+1 up, -1 down, 0 no side, None no data), a colour tone and one simple line."""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import math
import numpy as np
import pandas as pd

from . import data
from .engine import ema, rsi, rma, swings, true_range

UTC = timezone.utc
IST = timezone(timedelta(minutes=330))
FAMILIES = ["Range", "Timing", "Levels", "Trend", "Options", "Big Money", "Outside"]


@dataclass
class Point:
    id: str
    num: str
    name: str
    family: str
    top: bool
    vote: float = None
    text: str = "no data right now"
    tone: str = None          # up / down / neutral / warn / alarm / nodata
    directional: bool = True  # False = context only, never pushes the verdict
    extra: dict = field(default_factory=dict)

    def finish(self):
        if self.tone is None:
            if self.vote is None:
                self.tone = "nodata"
            elif self.vote > 0.05:
                self.tone = "up"
            elif self.vote < -0.05:
                self.tone = "down"
            else:
                self.tone = "neutral"
        return self


def money(x, asset):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"${x:,.0f}" if asset == "btc" or abs(x) >= 100 else f"${x:,.1f}"


def pct(x, d=1):
    return f"{x:+.{d}f}%"


def ist(t):
    return t.astimezone(IST).strftime("%I:%M %p").lstrip("0")


def sign_vote(x, th):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return 1.0 if x > th else (-1.0 if x < -th else 0.0)


def chg(series, n):
    s = series.dropna() if series is not None else None
    if s is None or len(s) <= n:
        return None
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) * 100


class Ctx:
    def __init__(self, asset, mk, opt, news, state):
        self.asset, self.mk, self.opt, self.news, self.state = asset, mk, opt, news or [], state
        self.g = asset == "gold"
        self.p = mk.price

    def M(self, x):
        return money(x, self.asset)


# ====================================================================== the points
def p_big_move_alarm(c):
    pt = Point("big_move_alarm", "1", "Big Move Alarm", "Options", True, directional=False)
    o = c.opt or {}
    signs = []
    if o.get("iv_3d_change") is not None and o["iv_3d_change"] > 8 and abs(c.mk.day_change_pct) < c.mk.adr_pct * 0.6:
        signs.append("option prices rising while price is quiet")
    if o.get("iv_rank") is not None and o["iv_rank"] < 20:
        signs.append("option prices very cheap (quiet spells end sharply)")
    if o.get("term_ratio") is not None and o["term_ratio"] > 1.05:
        signs.append("short-term fear higher than long-term")
    if o.get("gamma_flip") and c.p < o["gamma_flip"] and o.get("gex", 0) < 0:
        signs.append("price below the switch price (fast market)")
    nxt = next_news(c)
    if nxt and (nxt[0] - c.mk.now).total_seconds() < 12 * 3600:
        signs.append(f"big news soon ({nxt[1]})")
    pt.extra = {"signs": signs, "on": len(signs) >= 3}
    if not o:
        pt.vote, pt.tone = 0.0, "nodata"
        pt.text = "Option data missing - alarm can only use news" + (f": {signs[0]}" if signs else "")
        pt.extra["on"] = False
        return pt
    pt.vote = 0.0
    if len(signs) >= 3:
        pt.tone = "alarm"
        pt.text = f"ON - {len(signs)} of 5 signs: " + "; ".join(signs) + ". Direction not known."
    else:
        pt.tone = "neutral"
        pt.text = f"OFF - calm ({len(signs)} of 5 signs)" + (": " + "; ".join(signs) if signs else "")
    return pt


def p_range_used(c):
    m = c.mk
    pt = Point("range_used", "2", "Range Used Today", "Range", True, vote=0.0, directional=False)
    u = m.used_pct
    word = "mostly used up" if u >= 130 else "normal move done" if u >= 100 else "still has room" if u >= 40 else "just started"
    pt.text = f"{u:.0f}% of a normal day's move is done ({word}). Normal day = {c.M(m.adr_usd)} ({m.adr_pct:.2f}%)."
    pt.tone = "warn" if u >= 100 else "neutral"
    pt.extra = {"used": u}
    return pt


def p_projection(c):
    m = c.mk
    pt = Point("projection_lines", "3", "Projection Lines", "Range", True, vote=0.0, directional=False)
    dt, db = m.upper - c.p, c.p - m.lower
    pt.text = f"Top line {c.M(m.upper)} ({c.M(dt)} away), bottom line {c.M(m.lower)} ({c.M(db)} away). Price stays inside on ~9 of 10 days."
    near = min(abs(dt), abs(db)) < 0.25 * m.atr_d
    if c.p > m.upper:
        pt.text = f"Price is ABOVE the top line {c.M(m.upper)} - a big day. Don't sell against it."
        pt.tone = "warn"
    elif c.p < m.lower:
        pt.text = f"Price is BELOW the bottom line {c.M(m.lower)} - a big day. Don't buy against it."
        pt.tone = "warn"
    elif near:
        pt.tone = "warn"
        pt.text += " Price is close to a line - don't chase toward it."
    pt.extra = {"upper": m.upper, "lower": m.lower}
    return pt


def p_market_mood(c):
    d = c.mk.days
    pt = Point("market_mood", "4", "Market Mood", "Range", True, vote=0.0, directional=False)
    s = d.rng_pct.rolling(20).median().dropna()
    if len(s) < 60:
        pt.vote = None
        return pt
    pr = float((s.tail(252) < s.iloc[-1]).mean() * 100)
    r5 = d.rng_pct.tail(5).median() / d.rng_pct.tail(20).median()
    mood = "Hot" if pr >= 80 else ("Quiet" if pr <= 20 else "Normal")
    trend = "moves getting bigger" if r5 > 1.3 else ("moves getting smaller" if r5 < 0.7 else "steady")
    pt.text = f"{mood} - daily moves bigger than {pr:.0f}% of the last year; {trend}."
    pt.tone = "warn" if mood == "Hot" else "neutral"
    pt.extra = {"mood": mood}
    return pt


def p_move_speed(c):
    m = c.mk
    pt = Point("move_speed", "5", "Move Speed", "Trend", True)
    s = m.speed
    if s is None or math.isnan(s):
        return pt
    last4 = m.m15.iloc[-5:-1]
    direc = float(last4.close.iloc[-1] - last4.open.iloc[0]) if len(last4) else 0
    word = "News-level fast" if s > 2.5 else "Heating up" if s > 1.5 else "Slow" if s < 0.7 else "Normal"
    pt.extra = {"word": word}
    if s > 1.5:
        pt.vote = 1.0 if direc > 0 else -1.0
        pt.text = f"{word} - last 15 min moved {s:.1f}x the normal for this time, pushing {'up' if direc > 0 else 'down'}."
    else:
        pt.vote = 0.0
        pt.text = f"{word} - {s:.1f}x the normal move for this time of day."
    return pt


def p_strong_levels(c):
    m = c.mk
    pt = Point("strong_levels", "6", "Strong Levels", "Levels", True)
    zs = [z for z in m.zones() if z["grade"] != "Weak"]
    above = [z for z in zs if z["price"] > c.p]
    below = [z for z in zs if z["price"] <= c.p]
    a = min(above, key=lambda z: z["price"]) if above else None
    b = max(below, key=lambda z: z["price"]) if below else None
    parts = []
    if a:
        parts.append(f"wall above {c.M(a['price'])} ({a['grade']}: {', '.join(a['names'][:3])})")
    if b:
        parts.append(f"floor below {c.M(b['price'])} ({b['grade']}: {', '.join(b['names'][:3])})")
    pt.text = ("; ".join(parts) + ".") if parts else "No strong level near price."
    near = 0.15 * m.atr_d
    pt.vote = 0.0
    if b and c.p - b["price"] < near and (not a or a["price"] - c.p > near):
        pt.vote = 0.5
        pt.text = "Sitting just above a floor - " + pt.text
    elif a and a["price"] - c.p < near and (not b or c.p - b["price"] > near):
        pt.vote = -0.5
        pt.text = "Pressing into a wall - " + pt.text
    pt.extra = {"above": a, "below": b}
    return pt


def p_option_walls(c):
    o = c.opt or {}
    pt = Point("option_walls", "7", "Option Walls + Put-Call Ratio", "Options", True)
    if not o:
        return pt
    r = o.get("pcr_oi")
    cw, pw = o.get("call_wall"), o.get("put_wall")
    side = "more fall bets" if r and r > 1 else "more rise bets"
    pt.vote = 0.0 if r is None else (1.0 if r < 0.7 else -1.0 if r > 1.3 else 0.0)
    pt.text = (f"Ceiling {c.M(cw)} (biggest rise bets), floor {c.M(pw)} (biggest fall bets). "
               f"Put-call ratio {r:.2f} = {side}." if r else f"Ceiling {c.M(cw)}, floor {c.M(pw)}.")
    pt.extra = {"ceiling": cw, "floor": pw, "pcr": r}
    return pt


def p_calm_fast(c):
    o = c.opt or {}
    pt = Point("calm_fast", "8", "Calm or Fast Market", "Options", True, directional=False)
    if not o or o.get("gex") is None:
        return pt
    pt.vote = 0.0
    f = o.get("gamma_flip")
    if o["gex"] >= 0:
        pt.text = "Calm - option dealers slow moves down (buy dips, sell rips)." + (f" Switch price {c.M(f)}." if f else "")
        pt.tone = "neutral"
        pt.extra = {"word": "Calm"}
    else:
        pt.text = "Fast - option dealers' hedging can speed moves up." + (f" Back to calm above {c.M(f)}." if f else "")
        pt.tone = "warn"
        pt.extra = {"word": "Fast"}
    return pt


def _cmf(df, n=10):
    rng = (df.high - df.low).replace(0, np.nan)
    mfm = ((df.close - df.low) - (df.high - df.close)) / rng
    return float((mfm * df.volume).tail(n).sum() / df.volume.tail(n).sum())


def _yf_ohlc(t, period="6mo"):
    j = data.cached(f"yfo_{t}_{period}", 180, lambda: data._df_to_json(data.yf_hist(t, "1d", period)))
    return data._json_to_df(j)


def p_money_in_out(c):
    pt = Point("money_in_out", "9", "Money In or Out", "Big Money", True)
    if c.g:
        oz = data.gld_holdings()
        if oz and len(oz) > 6:
            ch = (oz[-1] / oz[-6] - 1) * 100
            pt.vote = sign_vote(ch, 0.3)
            pt.text = f"Gold fund (GLD) holdings {pct(ch, 2)} in 5 days - money {'coming in' if ch > 0 else 'going out'}."
            return pt
        df = _yf_ohlc("GLD")
        if df is not None and len(df) > 20:
            v = _cmf(df)
            pt.vote = sign_vote(v, 0.08)
            pt.text = f"Gold fund buying pressure {v:+.2f} (estimated from GLD trading) - money {'coming in' if v > 0 else 'going out'}."
        return pt
    fl = data.btc_etf_flows()
    if fl and len(fl) >= 3:
        s3 = sum(x[1] for x in fl[-3:])
        pt.vote = sign_vote(s3, 100)
        pt.text = f"US Bitcoin funds: {'+' if s3 >= 0 else '-'}${abs(s3):,.0f}M in the last 3 days - money {'coming in' if s3 > 0 else 'going out'}."
        return pt
    df = _yf_ohlc("IBIT")
    if df is not None and len(df) > 20:
        v = _cmf(df)
        pt.vote = sign_vote(v, 0.08)
        pt.text = f"Bitcoin fund buying pressure {v:+.2f} (estimated from IBIT trading) - money {'coming in' if v > 0 else 'going out'}."
    return pt


def _cot_rows(c):
    if c.g:
        return data.cot("088691", "72hh-3qpy"), ("m_money_positions_long", "m_money_positions_short"), "Big funds (hedge funds)"
    return data.cot("133741", "gpe5-46if"), ("asset_mgr_positions_long", "asset_mgr_positions_short"), "Big money managers"


def pt_ch_word(ch, ago):
    return 1 if ch > 0.03 * abs(ago or 1) else (-1 if ch < -0.03 * abs(ago or 1) else 0)


def p_big_players(c):
    pt = Point("big_players", "10", "Big Players Report (COT)", "Big Money", True)
    rows, (lk, sk), who = _cot_rows(c)
    if not rows:
        return pt
    def find(r, key):
        for k, v in r.items():
            if k.startswith(key):
                return float(v)
        return None
    net = [(r.get("report_date_as_yyyy_mm_dd", "")[:10], find(r, lk), find(r, sk)) for r in rows]
    net = [(d, l - s) for d, l, s in net if l is not None and s is not None]
    if len(net) < 4:
        return pt
    now_, ago = net[0][1], net[2][1]
    hist = [x[1] for x in net[:156]]
    pr = sum(h < now_ for h in hist) / len(hist) * 100
    ch = now_ - ago
    pt.vote = 1.0 if ch > 0.03 * abs(ago or 1) else (-1.0 if ch < -0.03 * abs(ago or 1) else 0.0)
    pt.text = (f"{who} are net {'buyers' if now_ > 0 else 'sellers'} ({now_:,.0f} contracts), "
               f"{'adding' if pt_ch_word(ch, ago) > 0 else 'cutting' if pt_ch_word(ch, ago) < 0 else 'about flat'} over 2 weeks; position higher than {pr:.0f}% of 3 years (report {net[0][0]}).")
    if pr > 90:
        pt.text += " Very crowded."
    return pt


def p_dollar(c):
    pt = Point("dollar", "11", "Dollar Pressure", "Outside", True)
    s = data.yf_close("DX-Y.NYB")
    ch = chg(s, 5)
    if ch is None:
        return pt
    pt.vote = -sign_vote(ch, 0.3)
    pt.text = f"Dollar index {pct(ch, 2)} in 5 days - {'strong dollar, pressure on ' if ch > 0 else 'weak dollar, helps '}{'gold' if c.g else 'Bitcoin'}."
    return pt


def p_rates(c):
    pt = Point("rates", "12", "Interest Rates", "Outside", True)
    ry, y2 = data.fred("DFII10"), data.fred("DGS2")
    votes, txt = [], []
    if ry is not None and len(ry) > 12:
        d = (ry.iloc[-1] - ry.iloc[-11]) * 100
        votes.append(-sign_vote(d, 8))
        txt.append(f"Real yield {ry.iloc[-1]:.2f}% ({d:+.0f} bp in 2 weeks)")
    if y2 is not None and len(y2) > 12:
        d = (y2.iloc[-1] - y2.iloc[-11]) * 100
        votes.append(-sign_vote(d, 8))
        txt.append(f"2-year yield {d:+.0f} bp" + (" (market expects more hikes)" if d > 8 else " (market expects cuts)" if d < -8 else ""))
    if not votes:
        return pt
    pt.vote = float(np.mean(votes))
    pt.text = ("Rates rising - a headwind. " if pt.vote < 0 else "Rates falling - a tailwind. " if pt.vote > 0 else "Rates steady. ") + "; ".join(txt) + "."
    return pt


def next_event(news, now):
    best = None
    for r in news or []:
        try:
            t = datetime.fromisoformat(r["date"]).astimezone(UTC)
        except Exception:
            continue
        if t > now - timedelta(minutes=5) and (best is None or t < best[0]):
            best = (t, r.get("title", "US news"))
    return best


def next_news(c):
    return next_event(c.news, c.mk.now)


def p_news(c):
    pt = Point("news_alert", "13", "News Alert", "Timing", True, vote=0.0, directional=False)
    nx = next_news(c)
    if not c.news:
        pt.vote = None
        return pt
    if not nx:
        pt.text = "No more big US news this week."
        return pt
    mins = (nx[0] - c.mk.now).total_seconds() / 60
    when = nx[0].astimezone(IST).strftime("%a %I:%M %p").replace(" 0", " ")
    left = f"{int(mins // 60)}h {int(mins % 60)}m" if mins >= 60 else f"{int(mins)} min"
    pt.text = f"Next big US news: {nx[1]} - {when} India time (in {left})."
    if mins <= 120:
        pt.tone = "warn" if mins > 30 else "alarm"
        pt.text += " Expect fast moves - be careful."
    pt.extra = {"mins": mins, "title": nx[1]}
    return pt


def p_crowd(c):
    pt = Point("crowd", "14", "Crowd Positions", "Big Money", True)
    hl = data.hyperliquid_btc()
    if not hl:
        return pt
    f8 = hl["funding_1h"] * 8 * 100
    hist = c.state.get("oi_hist", [])
    oi_ch = None
    old = [x for x in hist if c.mk.now.timestamp() - x[0] >= 20 * 3600]
    if old:
        oi_ch = (hl["oi"] / old[-1][1] - 1) * 100
    v = -1.0 if f8 > 0.06 else -0.5 if f8 > 0.03 else 1.0 if f8 < -0.02 else 0.5 if f8 < 0 else 0.0
    pt.vote = v
    crowd = "buyers crowded (they pay to hold)" if f8 > 0.03 else "sellers crowded" if f8 < 0 else "balanced"
    pt.text = f"Funding {f8:+.3f}% per 8h - {crowd}." + (f" Open bets {pct(oi_ch)} in 24h." if oi_ch is not None else "")
    return pt


def p_stop_pools(c):
    m = c.mk
    pt = Point("stop_pools", "15", "Stop Pools", "Levels", True, vote=0.0, directional=False)
    cands = [(float(m.prev.high), "yesterday's high"), (float(m.prev.low), "yesterday's low")]
    if m.prev_week is not None:
        cands += [(float(m.prev_week.high), "last week's high"), (float(m.prev_week.low), "last week's low")]
    asia = m.session_box(0, 7)
    if asia and asia["done"]:
        cands += [(asia["high"], "Asia high"), (asia["low"], "Asia low")]
    hs, ls = swings(m.h1.tail(120))
    tol = c.p * 0.0006
    for arr, nm in ((hs, "equal highs"), (ls, "equal lows")):
        for i in range(1, len(arr)):
            if abs(arr[i][1] - arr[i - 1][1]) <= tol:
                cands.append(((arr[i][1] + arr[i - 1][1]) / 2, nm))
    above = [x for x in cands if x[0] > m.t_high]
    below = [x for x in cands if x[0] < m.t_low]
    a = min(above) if above else None
    b = max(below) if below else None
    parts = []
    if a:
        parts.append(f"above {c.M(a[0])} ({a[1]}, {c.M(a[0] - c.p)} away)")
    if b:
        parts.append(f"below {c.M(b[0])} ({b[1]}, {c.M(c.p - b[0])} away)")
    pt.text = ("Stops likely " + " and ".join(parts) + ". Price is often pulled to these.") if parts else "No untouched stop pool nearby."
    return pt


# ---------------------------------------------------------------------- 16 - 35
def p_day_pace(c):
    pt = Point("day_pace", "16", "Day Pace", "Timing", False, vote=0.0, directional=False)
    p = c.mk.pace
    if p is None or math.isnan(p):
        pt.vote = None
        return pt
    w = "Fast" if p > 1.2 else "Slow" if p < 0.8 else "Normal"
    pt.text = f"{w} - today is at {p:.1f}x the normal pace for this time of day."
    return pt


def p_busy_hours(c):
    pt = Point("busy_hours", "17", "Busy Hours", "Timing", False, vote=0.0, directional=False)
    hs = c.mk.hour_share
    h = c.mk.slot_now // 4
    if not hs:
        pt.vote = None
        return pt
    v = hs.get(h, 1.0)
    w = "Busy hour" if v >= 1.3 else "Quiet hour" if v <= 0.7 else "Normal hour"
    best = max(hs, key=hs.get)
    pt.text = f"{w} ({v:.1f}x a normal hour). Busiest hour is usually around " + _slot_hour_ist(c, best) + " India time."
    pt.extra = {"word": w.split()[0]}
    return pt


def _slot_hour_ist(c, h):
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York") if c.g else UTC
    base = datetime.now(tz).replace(hour=int(h), minute=0, second=0, microsecond=0)
    return base.astimezone(IST).strftime("%I %p").lstrip("0")


def p_weekday(c):
    pt = Point("weekday", "18", "Weekday Rhythm", "Timing", False, vote=0.0, directional=False)
    d = c.mk.days.tail(500).copy()
    if len(d) < 60:
        pt.vote = None
        return pt
    d["wd"] = [x.weekday() for x in d.index]
    wdn = pd.Timestamp(c.mk.today).weekday()
    f = d[d.wd == wdn].rng_pct.median() / d.rng_pct.median()
    name = pd.Timestamp(c.mk.today).day_name()
    pt.text = f"{name}s usually move {f:.1f}x a normal day."
    return pt


def p_stop_size(c):
    pt = Point("stop_size", "19", "Stop Size Helper", "Range", False, vote=0.0, directional=False)
    s1 = 1.5 * c.mk.atr_h
    pt.text = f"Suggested stop about {c.M(s1)} on a 1-hour trade (1.5x the normal hourly move); half that on 15-min trades."
    return pt


def p_dont_chase(c):
    m = c.mk
    pt = Point("dont_chase", "20", "Don't Chase Warning", "Range", False, vote=0.0, directional=False)
    rng = m.t_high - m.t_low
    pos = (c.p - m.t_low) / rng if rng > 0 else 0.5
    if m.used_pct >= 100 and pos >= 0.85:
        pt.tone, pt.text = "warn", "Most of today's move is done and price is near today's high - don't chase buys."
    elif m.used_pct >= 100 and pos <= 0.15:
        pt.tone, pt.text = "warn", "Most of today's move is done and price is near today's low - don't chase sells."
    else:
        pt.text = "No chase warning right now."
    pt.extra = {"active": pt.tone == "warn"}
    return pt


def p_asia_box(c):
    pt = Point("asia_box", "21", "Asia Box", "Levels", False)
    b = c.mk.session_box(0, 7)
    if not b or not b["done"]:
        pt.vote, pt.text = 0.0, "Asia box still forming (Asia hours 5:30 AM - 12:30 PM India time)."
        return pt
    pt.vote = 1.0 if c.p > b["high"] else -1.0 if c.p < b["low"] else 0.0
    where = "above" if pt.vote > 0 else "below" if pt.vote < 0 else "inside"
    pt.text = f"Price is {where} the Asia box ({c.M(b['low'])} - {c.M(b['high'])})."
    return pt


def p_first_hour(c):
    from zoneinfo import ZoneInfo
    pt = Point("first_hour", "22", "First Hour Range", "Levels", False)
    ny = c.mk.session_box(9, 10, ZoneInfo("America/New_York")) if not c.g else c.mk.session_box(8, 9, ZoneInfo("America/New_York"))
    ld = c.mk.session_box(8, 9, ZoneInfo("Europe/London"))
    b, name = (ny, "New York") if ny and ny["done"] else (ld, "London") if ld and ld["done"] else (None, "")
    if not b:
        pt.vote, pt.text = 0.0, "First-hour box not ready yet (London opens 1:30 PM India time in winter)."
        return pt
    pt.vote = 1.0 if c.p > b["high"] else -1.0 if c.p < b["low"] else 0.0
    where = "above" if pt.vote > 0 else "below" if pt.vote < 0 else "inside"
    pt.text = f"Price is {where} the {name} first-hour box ({c.M(b['low'])} - {c.M(b['high'])})."
    return pt


def p_yesterday(c):
    m = c.mk
    pt = Point("yesterday", "23", "Yesterday's Levels", "Levels", False)
    h, l, cl = float(m.prev.high), float(m.prev.low), float(m.prev.close)
    pt.vote = 1.0 if c.p > h else -1.0 if c.p < l else (0.3 if c.p > cl else -0.3)
    pt.text = f"Yesterday: high {c.M(h)}, low {c.M(l)}, close {c.M(cl)}. Price is " + (
        "above yesterday's high." if c.p > h else "below yesterday's low." if c.p < l else
        f"inside, {'above' if c.p > cl else 'below'} the close.")
    return pt


def p_last_week(c):
    m = c.mk
    pt = Point("last_week", "24", "Last Week's Levels", "Levels", False)
    w = m.prev_week
    if w is None:
        return pt
    h, l, cl = float(w.high), float(w.low), float(w.close)
    pt.vote = 1.0 if c.p > h else -1.0 if c.p < l else (0.3 if c.p > cl else -0.3)
    pt.text = f"Last week: high {c.M(h)}, low {c.M(l)}, close {c.M(cl)}. Price is " + (
        "above last week's high." if c.p > h else "below last week's low." if c.p < l else
        f"inside, {'above' if c.p > cl else 'below'} last week's close.")
    return pt


def p_round(c):
    pt = Point("round_numbers", "25", "Round Numbers", "Levels", False, vote=0.0, directional=False)
    st = c.mk.cfg["round_big"]
    up = math.ceil(c.p / st) * st
    dn = math.floor(c.p / st) * st
    pt.text = f"Big round prices: {c.M(up)} above ({c.M(up - c.p)} away), {c.M(dn)} below ({c.M(c.p - dn)} away)."
    return pt


def p_vwap(c):
    pt = Point("vwap", "26", "Average Price Line (VWAP)", "Trend", False)
    v = c.mk.vwap
    pt.vote = 1.0 if c.p > v * 1.0005 else -1.0 if c.p < v * 0.9995 else 0.0
    pt.text = f"Today's average price {c.M(v)}. Price is {'above - buyers lead' if pt.vote > 0 else 'below - sellers lead' if pt.vote < 0 else 'right on it'}."
    return pt


def p_busy_zones(c):
    pt = Point("busy_zones", "27", "Busy Price Zones", "Levels", False)
    pr = c.mk.profile
    if not pr:
        return pt
    pt.vote = 1.0 if c.p > pr["vah"] else -1.0 if c.p < pr["val"] else 0.0
    pt.text = (f"Yesterday's busiest price {c.M(pr['poc'])}, busy zone {c.M(pr['val'])} - {c.M(pr['vah'])}. Price is "
               + ("above the zone." if pt.vote > 0 else "below the zone." if pt.vote < 0 else "inside the zone."))
    return pt


def p_trend_ladder(c):
    pt = Point("trend_ladder", "28", "Trend Ladder", "Trend", False)
    hs, ls = swings(c.mk.h1.tail(150))
    if len(hs) < 2 or len(ls) < 2:
        return pt
    hh, hl = hs[-1][1] > hs[-2][1], ls[-1][1] > ls[-2][1]
    if hh and hl:
        pt.vote, pt.text = 1.0, "Higher highs and higher lows on the 1-hour chart - uptrend."
    elif not hh and not hl:
        pt.vote, pt.text = -1.0, "Lower highs and lower lows on the 1-hour chart - downtrend."
    else:
        pt.vote, pt.text = 0.0, "Mixed highs and lows on the 1-hour chart - no clear trend."
    return pt


def p_tf_agree(c):
    pt = Point("tf_agree", "29", "Timeframes Agree", "Trend", False)
    m = c.mk
    h4 = m.h1.close.resample("4h").last().dropna()
    res = {}
    for nm, s in (("15 min", m.m15.close), ("1 hour", m.h1.close), ("4 hour", h4)):
        if len(s) > 60:
            res[nm] = 1 if s.iloc[-1] > ema(s, 50).iloc[-1] else -1
    if len(res) < 3:
        return pt
    tot = sum(res.values())
    pt.vote = 1.0 if tot == 3 else -1.0 if tot == -3 else 0.0
    pt.text = ("All three (15 min, 1 hour, 4 hour) point UP." if tot == 3 else
               "All three (15 min, 1 hour, 4 hour) point DOWN." if tot == -3 else
               "Timeframes disagree: " + ", ".join(f"{k} {'up' if v > 0 else 'down'}" for k, v in res.items()) + ".")
    return pt


def p_clean(c):
    pt = Point("clean_choppy", "30", "Clean or Choppy", "Trend", False)
    s = c.mk.h1.close.tail(21)
    if len(s) < 21:
        return pt
    er = abs(s.iloc[-1] - s.iloc[0]) / s.diff().abs().sum()
    if er > 0.35:
        pt.vote = 1.0 if s.iloc[-1] > s.iloc[0] else -1.0
        pt.text = f"Clean move {'up' if pt.vote > 0 else 'down'} over the last 20 hours (score {er:.2f})."
    else:
        pt.vote, pt.text = 0.0, f"Choppy - price jumping around (score {er:.2f}). Trends are less reliable now."
    return pt


def p_stretch(c):
    pt = Point("stretch", "31", "Stretch Meter", "Trend", False)
    m = c.mk
    z = (c.p - m.ema50_h) / m.atr_h if m.atr_h else 0
    pt.vote = -0.5 if z > 3 else 0.5 if z < -3 else 0.0
    pt.text = f"Price is {abs(z):.1f} normal hourly moves {'above' if z > 0 else 'below'} its 50-hour average" + (
        " - stretched, a pullback is common." if abs(z) > 3 else ".")
    if abs(z) > 3:
        pt.tone = "warn"
    return pt


def p_push_weaker(c):
    pt = Point("push_weaker", "32", "Push Getting Weaker", "Trend", False)
    h = c.mk.h1.tail(80).copy()
    if len(h) < 40:
        return pt
    h["rsi"] = rsi(h.close)
    last = h.tail(3)
    win = h.iloc[-23:-3]
    pt.vote, pt.text = 0.0, "No weakness sign in the latest push."
    if last.high.max() >= h.high.tail(20).max() and last.rsi.max() < win.rsi.max() - 3:
        pt.vote, pt.text = -1.0, "New high but with less force than the last high - the push up is getting weaker."
    elif last.low.min() <= h.low.tail(20).min() and last.rsi.min() > win.rsi.min() + 3:
        pt.vote, pt.text = 1.0, "New low but with less force than the last low - the push down is getting weaker."
    return pt


def p_tight_day(c):
    pt = Point("tight_day", "33", "Tight Day", "Range", False, vote=0.0, directional=False)
    d = c.mk.days.tail(8)
    rng = d.high - d.low
    nr7 = rng.iloc[-1] <= rng.tail(7).min()
    inside = d.high.iloc[-1] <= d.high.iloc[-2] and d.low.iloc[-1] >= d.low.iloc[-2]
    if nr7 or inside:
        pt.tone = "warn"
        pt.text = "Yesterday was " + ("the smallest day of the last 7" if nr7 else "inside the day before") + " - energy may be building for a bigger move."
    else:
        pt.text = "Yesterday was a normal-size day."
    return pt


def p_open_lines(c):
    m = c.mk
    pt = Point("open_lines", "34", "Open Price Lines", "Trend", False)
    lines = {"today's open": m.t_open, "week open": m.week_open, "month open": m.month_open}
    s = sum(1 if c.p > v else -1 for v in lines.values())
    pt.vote = 1.0 if s == 3 else -1.0 if s == -3 else s / 3
    pt.text = "Price is " + ", ".join(f"{'above' if c.p > v else 'below'} {k} {c.M(v)}" for k, v in lines.items()) + "."
    return pt


def p_buyers_sellers(c):
    pt = Point("buyers_sellers", "35", "Buyers vs Sellers", "Trend", False)
    b = c.mk.m15.tail(33).iloc[:-1]
    if b.volume.fillna(0).sum() <= 0:
        return pt
    rng = (b.high - b.low).replace(0, np.nan)
    delta = (b.volume * (b.close - b.open) / rng).sum()
    r = float(delta / b.volume.sum())
    pt.vote = sign_vote(r, 0.08)
    pt.text = f"Last 8 hours: {'buyers' if r > 0 else 'sellers'} hit harder (score {r:+.2f})."
    return pt


# ---------------------------------------------------------------------- 36 - 50
def p_pcr_vol(c):
    o = c.opt or {}
    pt = Point("pcr_today", "36", "Put-Call Ratio (today's trading)", "Options", False)
    r = o.get("pcr_vol")
    if r is None:
        return pt
    pt.vote = 1.0 if r < 0.6 else -1.0 if r > 1.4 else 0.0
    pt.text = f"Today: {r:.2f} fall bets for each rise bet - " + ("more rise bets." if r < 1 else "more fall bets.")
    if r > 2:
        pt.text += " Very fearful - bounces often start here."
    return pt


def p_max_pain(c):
    o = c.opt or {}
    pt = Point("max_pain", "37", "Max Pain and Expiry", "Options", False)
    mp = o.get("max_pain")
    if not mp:
        return pt
    e = datetime.fromisoformat(o["max_pain_exp"])
    days = (e - c.mk.now).total_seconds() / 86400
    when = e.astimezone(IST).strftime("%a %d %b, %I:%M %p")
    pt.vote = 0.0
    if days <= 3:
        pt.vote = 0.5 if c.p < mp else -0.5
    pt.text = f"Big expiry {when} India time. Max pain {c.M(mp)} - near expiry price often drifts toward it."
    return pt


def p_expected_move(c):
    o = c.opt or {}
    pt = Point("expected_move", "38", "Expected Move", "Options", False, vote=0.0, directional=False)
    d, w = o.get("exp_move_day"), o.get("exp_move_week")
    if not d:
        pt.vote = None
        return pt
    pt.text = f"Options expect about +/-{c.M(d)} by tomorrow and +/-{c.M(w)} this week ({c.M(c.p - w)} to {c.M(c.p + w)})."
    return pt


def p_near_fear(c):
    o = c.opt or {}
    pt = Point("near_fear", "39", "Near-Term Fear", "Options", False, vote=0.0, directional=False)
    r = o.get("term_ratio")
    if r is None:
        pt.vote = None
        return pt
    if r > 1.05:
        pt.tone, pt.text = "warn", f"Short-term options cost more than long-term ({r:.2f}x) - big players fear something soon."
    else:
        pt.text = f"Short-term options are normal ({r:.2f}x long-term) - no near-term fear."
    return pt


def p_big_trades(c):
    o = c.opt or {}
    pt = Point("big_option_trades", "40", "Big Option Trades", "Options", False)
    n = o.get("big_trades_n")
    if n is None:
        return pt
    s = o.get("big_trades_score", 0)
    if n == 0:
        pt.vote, pt.text = 0.0, "No very large option bets in the last day."
        return pt
    pt.vote = 0.5 if s > 0 else -0.5 if s < 0 else 0.0
    pt.text = f"{n} very large option bets in the last day, leaning {'up (calls bought / puts sold)' if s > 0 else 'down (puts bought / calls sold)'}."
    return pt


def p_open_gaps(c):
    m = c.mk
    pt = Point("open_gaps", "41", "Open Gaps", "Levels", False)
    gaps = []
    # weekend gap: this week's first price vs last Friday close
    if c.g:
        d = m.m15
        wk = d[d.index >= d.index[-1] - pd.Timedelta(days=7)]
        jumps = wk.index.to_series().diff() > pd.Timedelta(hours=24)
        if jumps.any():
            i = wk.index.get_loc(jumps[jumps].index[-1])
            fri, sun = float(wk.close.iloc[i - 1]), float(wk.open.iloc[i])
            after = wk.iloc[i:]
            filled = after.low.min() <= fri <= after.high.max()
            if abs(sun / fri - 1) > 0.001 and not filled:
                gaps.append((fri, "weekend gap"))
    else:
        cme = data.safe("cme_btc", lambda: data.yf_hist("BTC=F", "1h", "10d"))
        if cme is not None and len(cme) > 10:
            jumps = cme.index.to_series().diff() > pd.Timedelta(hours=30)
            if jumps.any():
                i = cme.index.get_loc(jumps[jumps].index[-1])
                fri = float(cme.close.iloc[i - 1])
                after = m.m15[m.m15.index >= cme.index[i]]
                if len(after) and not (after.low.min() <= fri <= after.high.max()):
                    gaps.append((fri, "CME futures weekend gap"))
    # 1-hour imbalance gaps not yet filled
    h = m.h1.tail(120)
    thr = 0.25 * m.atr_h
    for i in range(2, len(h) - 1):
        a, cc = h.iloc[i - 2], h.iloc[i]
        later = h.iloc[i + 1:]
        if cc.low - a.high > thr and not (later.low.min() <= a.high):
            gaps.append(((a.high + cc.low) / 2, "1-hour price gap"))
        if a.low - cc.high > thr and not (later.high.max() >= a.low):
            gaps.append(((a.low + cc.high) / 2, "1-hour price gap"))
    if not gaps:
        pt.vote, pt.text = 0.0, "No open price gaps nearby."
        return pt
    g = min(gaps, key=lambda x: abs(x[0] - c.p))
    pt.vote = 0.5 if g[0] > c.p else -0.5
    pt.text = f"Unfilled {g[1]} at {c.M(g[0])} ({'above' if g[0] > c.p else 'below'}, {c.M(abs(g[0] - c.p))} away) - price often comes back to fill it."
    return pt


def p_silver(c):
    pt = Point("silver_check", "42", "Silver Check", "Outside", False)
    s = data.yf_close("SI=F")
    sc = chg(s, 5)
    gc = chg(c.mk.days.close, 5)
    if sc is None or gc is None:
        return pt
    same = (sc > 0) == (gc > 0)
    pt.vote = (1.0 if sc > 0 else -1.0) if same and abs(sc) > 0.5 else 0.0
    pt.text = f"Silver {pct(sc)} vs gold {pct(gc)} in 5 days - " + ("silver confirms gold." if same else "silver does NOT confirm - be careful.")
    if not same:
        pt.tone = "warn"
    return pt


def p_gold_fear(c):
    pt = Point("gold_fear", "43", "Gold Fear Meter (GVZ)", "Options", False, vote=0.0, directional=False)
    g = data.yf_close("^GVZ")
    if g is None or len(g) < 60:
        pt.vote = None
        return pt
    pr = float((g.tail(252) < g.iloc[-1]).mean() * 100)
    pt.text = f"Gold fear meter {g.iloc[-1]:.1f} - higher than {pr:.0f}% of the last year ({'big moves expected' if pr > 75 else 'calm expected' if pr < 25 else 'normal'})."
    if pr > 75:
        pt.tone = "warn"
    return pt


def _manual(c, key, pid, num, name):
    import json, os
    pt = Point(pid, num, name, "Big Money", False)
    p = os.path.join(os.path.dirname(os.path.dirname(__file__)), "manual_inputs.json")
    try:
        with open(p) as f:
            v = json.load(f)[key]
    except Exception:
        return pt
    pt.vote = float(v.get("vote", 0)) * 0.5
    age = (c.mk.now.date() - datetime.strptime(v["updated"], "%Y-%m-%d").date()).days
    pt.text = v["text"] + (f" (info from {v['updated']}; update monthly in manual_inputs.json)" if age > 45 else f" (as of {v['updated']})")
    return pt


def p_central_banks(c):
    return _manual(c, "central_bank_buying", "central_banks", "44", "Central Bank Buying")


def p_china(c):
    return _manual(c, "china_demand", "china_demand", "45", "China Demand")


def p_us_buyers(c):
    pt = Point("us_buyers", "46", "US Buyers (Coinbase Premium)", "Big Money", False)
    other = data.binance_btc_price()
    name = "world price"
    if not other:
        hl = data.hyperliquid_btc()
        other = hl and hl["oracle"]
        name = "world average price"
    if not other:
        return pt
    prem = (c.p / other - 1) * 100
    pt.vote = sign_vote(prem, 0.05)
    pt.text = f"Coinbase price is {pct(prem, 3)} vs the {name} - US buyers are " + ("keen." if prem > 0.05 else "selling." if prem < -0.05 else "neutral.")
    return pt


def p_forced(c):
    pt = Point("forced_closings", "47", "Forced Closings", "Big Money", False)
    hl = data.hyperliquid_btc()
    hist = c.state.get("oi_hist", [])
    old = [x for x in hist if c.mk.now.timestamp() - x[0] >= 4 * 3600]
    if not hl or not old:
        pt.vote, pt.text = (0.0, "Still collecting data (needs a few hours of history).") if hl else (None, "no data right now")
        return pt
    oi_ch = (hl["oi"] / old[-1][1] - 1) * 100
    p_ch = (c.p / old[-1][2] - 1) * 100 if old[-1][2] else 0
    pt.vote = 0.0
    if oi_ch < -4 and abs(p_ch) > 1.5:
        pt.vote = 0.5 if p_ch < 0 else -0.5
        pt.text = (f"Big wave of forced closings: open bets {pct(oi_ch)} while price {pct(p_ch)} in 4h - "
                   + ("buyers were flushed out, selling may be done." if p_ch < 0 else "sellers were squeezed, the jump may fade."))
    else:
        pt.text = f"No big forced-closing wave (open bets {pct(oi_ch)}, price {pct(p_ch)} in 4h)."
    return pt


def p_whales(c):
    pt = Point("whales", "48", "Whales and Exchanges", "Big Money", False)
    fin, fout = data.coinmetrics("FlowInExNtv", 10), data.coinmetrics("FlowOutExNtv", 10)
    if not fin or not fout:
        pt.text = "Exchange flow data not available for free right now."
        return pt
    net = sum(x[1] for x in fin[-7:]) - sum(x[1] for x in fout[-7:])
    pt.vote = sign_vote(-net, 5000)
    pt.text = f"Last 7 days: {abs(net):,.0f} BTC net {'INTO exchanges (getting ready to sell)' if net > 0 else 'OUT of exchanges (holders keeping coins)'}."
    return pt


def p_stocks(c):
    pt = Point("stock_mood", "49", "Stock Market Mood", "Outside", False)
    vix, qqq = data.yf_close("^VIX"), data.yf_close("QQQ")
    if vix is None or qqq is None or len(qqq) < 25:
        return pt
    up = qqq.iloc[-1] > ema(qqq, 20).iloc[-1]
    v = float(vix.iloc[-1])
    risk_on = up and v < 20
    risk_off = (not up) and v > 22
    if c.g:
        pt.vote = 0.5 if risk_off else 0.0
    else:
        pt.vote = 1.0 if risk_on else -1.0 if risk_off else 0.0
    pt.text = f"Stock fear (VIX) {v:.1f}, tech stocks {'rising' if up else 'falling'} - " + (
        "risk-on mood." if risk_on else "risk-off mood (fear)." if risk_off else "mixed mood.")
    return pt


def p_liquidity(c):
    pt = Point("world_money", "50", "World Money Supply", "Outside", False)
    wal, tga, rrp = data.fred("WALCL"), data.fred("WTREGEN"), data.fred("RRPONTSYD")
    if wal is None or tga is None or rrp is None:
        return pt
    df = pd.concat([wal / 1000, tga, rrp], axis=1).ffill().dropna()
    df.columns = ["wal", "tga", "rrp"]
    net = (df.wal - df.tga - df.rrp)
    net = net[net.index >= net.index[-1] - pd.Timedelta(days=400)]
    old = net[net.index <= net.index[-1] - pd.Timedelta(days=91)]
    if not len(old):
        return pt
    ch = (net.iloc[-1] / old.iloc[-1] - 1) * 100
    pt.vote = sign_vote(ch, 1.0)
    pt.text = f"US money in the system (Fed balance sheet minus parked cash) {pct(ch)} in 3 months - " + (
        "more money flowing, usually helps in the months ahead." if ch > 0 else "money being drained, a slow headwind.")
    return pt


# ---------------------------------------------------------------------- extras (full report only)
def e_gs_ratio(c):
    pt = Point("gs_ratio", "E", "Gold-Silver Ratio", "Outside", False)
    s = data.yf_close("SI=F")
    if s is None:
        return pt
    gld = c.mk.days.close
    r = (gld / s.reindex(gld.index, method="nearest")).dropna()
    if len(r) < 60:
        return pt
    m50 = r.tail(50).mean()
    pt.vote = 0.5 if r.iloc[-1] < m50 * 0.98 else -0.5 if r.iloc[-1] > m50 * 1.02 else 0.0
    pt.text = f"Ratio {r.iloc[-1]:.1f} vs 50-day average {m50:.1f} - " + ("silver leading (metals strong)." if pt.vote > 0 else "silver lagging." if pt.vote < 0 else "normal.")
    return pt


def e_miners(c):
    pt = Point("miners", "E", "Gold Miners Check", "Outside", False)
    gdx, gld = data.yf_close("GDX"), data.yf_close("GLD")
    if gdx is None or gld is None:
        return pt
    r = (gdx / gld).dropna()
    ch = chg(r, 10)
    pt.vote = sign_vote(ch, 2)
    pt.text = f"Miners vs gold {pct(ch)} in 2 weeks - " + ("miners leading up." if pt.vote > 0 else "miners lagging (warning)." if pt.vote < 0 else "in step.")
    return pt


def e_inflation(c):
    pt = Point("inflation_exp", "E", "Inflation Expectations", "Outside", False)
    s = data.fred("T10YIE")
    if s is None or len(s) < 25:
        return pt
    d = (s.iloc[-1] - s.iloc[-21]) * 100
    pt.vote = sign_vote(d, 10) * 0.5
    pt.text = f"Market expects {s.iloc[-1]:.2f}% inflation ({d:+.0f} bp in a month) - " + ("rising, supports gold." if d > 10 else "falling." if d < -10 else "steady.")
    return pt


def e_bonds(c):
    pt = Point("bond_stress", "E", "Bond Market Stress", "Outside", False, vote=0.0, directional=False)
    s = data.yf_close("^MOVE")
    if s is None or len(s) < 60:
        pt.vote = None
        return pt
    pr = float((s.tail(252) < s.iloc[-1]).mean() * 100)
    pt.text = f"Bond fear meter {s.iloc[-1]:.0f} - higher than {pr:.0f}% of the last year."
    if pr > 80:
        pt.tone = "warn"
        pt.text += " Bond stress can shake gold and Bitcoin."
    return pt


def e_gold_btc(c):
    pt = Point("gold_btc_link", "E", "Gold-Bitcoin Link", "Outside", False, vote=0.0, directional=False)
    a = data.yf_close("GC=F")
    b = data.yf_close("BTC-USD")
    if a is None or b is None:
        pt.vote = None
        return pt
    df = pd.concat([a.pct_change(), b.pct_change()], axis=1).dropna().tail(30)
    r = df.corr().iloc[0, 1]
    pt.text = f"Over 30 days gold and Bitcoin moved {'together' if r > 0.3 else 'opposite' if r < -0.3 else 'on their own'} (link {r:+.2f})."
    return pt


def e_tech(c):
    pt = Point("tech_link", "E", "Tech Stocks Link", "Outside", False, vote=0.0, directional=False)
    q = data.yf_close("QQQ")
    if q is None:
        pt.vote = None
        return pt
    b = c.mk.days.close
    b.index = pd.to_datetime(b.index)
    q.index = q.index.tz_localize(None).normalize() if q.index.tz is not None else q.index
    df = pd.concat([b.pct_change(), q.pct_change()], axis=1).dropna().tail(30)
    if len(df) < 15:
        pt.vote = None
        return pt
    r = df.corr().iloc[0, 1]
    pt.text = f"Bitcoin is moving {'with' if r > 0.3 else 'against' if r < -0.3 else 'apart from'} tech stocks (30-day link {r:+.2f})."
    return pt


def e_dominance(c):
    pt = Point("btc_dominance", "E", "Bitcoin Share of Crypto", "Big Money", False, vote=0.0, directional=False)
    d = data.btc_dominance()
    if d is None:
        pt.vote = None
        return pt
    hist = c.state.setdefault("dom_hist", [])
    today = str(c.mk.now.date())
    if not hist or hist[-1][0] != today:
        hist.append([today, d])
        del hist[:-60]
    old = [x for x in hist if x[0] <= str((c.mk.now - timedelta(days=7)).date())]
    extra = f" ({d - old[-1][1]:+.1f} in a week)" if old else ""
    pt.text = f"Bitcoin is {d:.1f}% of all crypto{extra}."
    return pt


def e_stables(c):
    pt = Point("stablecoins", "E", "Stablecoin Money", "Big Money", False)
    s = data.stablecoins()
    if not s or len(s) < 31:
        return pt
    ch = (s[-1][1] / s[-31][1] - 1) * 100
    pt.vote = sign_vote(ch, 1) * 0.5
    pt.text = f"Stablecoin supply {pct(ch)} in 30 days (${s[-1][1] / 1e9:,.0f}B) - " + ("new money coming into crypto." if ch > 1 else "money leaving crypto." if ch < -1 else "flat.")
    return pt


def e_fng(c):
    pt = Point("fear_greed", "E", "Fear and Greed", "Big Money", False)
    f = data.fear_greed()
    if not f:
        return pt
    v = f[0]
    pt.vote = 0.5 if v < 20 else -0.5 if v > 80 else 0.0
    word = "extreme fear" if v < 20 else "fear" if v < 45 else "greed" if v > 55 else "neutral"
    word = "extreme greed" if v > 80 else word
    pt.text = f"Crypto mood {v}/100 = {word}." + (" Extreme fear often comes near bottoms." if v < 20 else " Extreme greed often comes near tops." if v > 80 else "")
    return pt


def e_mvrv(c):
    pt = Point("mvrv", "E", "Bitcoin Profit Meter (MVRV)", "Big Money", False)
    s = data.coinmetrics("CapMVRVCur", 5)
    if not s:
        return pt
    v = s[-1][1]
    pt.vote = -0.5 if v > 3.2 else 0.5 if v < 1 else 0.0
    pt.text = f"Holders' average profit meter {v:.2f} - " + ("very high profits, top risk." if v > 3.2 else "holders at a loss, bottom zone." if v < 1 else "normal.")
    return pt


def e_eth(c):
    pt = Point("eth_lead", "E", "Ethereum Lead", "Outside", False)
    e = data.yf_close("ETH-USD")
    b = data.yf_close("BTC-USD")
    ce, cb = chg(e, 3), chg(b, 3)
    if ce is None or cb is None:
        return pt
    d = ce - cb
    pt.vote = sign_vote(d, 2) * 0.5
    pt.text = f"Ethereum {pct(ce)} vs Bitcoin {pct(cb)} in 3 days - " + ("risk appetite rising." if d > 2 else "risk appetite falling." if d < -2 else "in step.")
    return pt


def e_season(c):
    pt = Point("season", "E", "Season Pattern", "Timing", False)
    t = "GC=F" if c.g else "BTC-USD"
    s = data.yf_close(t, period="max", interval="1mo")
    if s is None or len(s) < 48:
        return pt
    r = s.pct_change().dropna()
    mon = c.mk.now.month
    rm = r[r.index.month == mon]
    if len(rm) < 4:
        return pt
    avg, upr = rm.mean() * 100, (rm > 0).mean() * 100
    pt.vote = (0.5 if avg > 1 and upr >= 60 else -0.5 if avg < -1 and upr <= 40 else 0.0)
    pt.text = f"In past years this month averaged {pct(avg)}, up {upr:.0f}% of the time ({len(rm)} years)."
    return pt


def e_weekly(c):
    pt = Point("weekly_trend", "E", "Weekly Trend", "Trend", False)
    cl = c.mk.days.close
    if len(cl) < 110:
        return pt
    w = cl.resample("W").last().dropna()
    ma = w.tail(20).mean()
    pt.vote = 1.0 if c.p > ma else -1.0
    pt.text = f"Price is {'above' if c.p > ma else 'below'} its 20-week average {c.M(ma)} - big trend {'up' if c.p > ma else 'down'}."
    return pt


def e_hash(c):
    pt = Point("hash_ribbon", "E", "Miner Health (Hash Rate)", "Big Money", False)
    h = data.hashrate()
    if not h or len(h) < 70:
        return pt
    s = pd.Series([x[1] for x in h])
    m30, m60 = s.rolling(30).mean(), s.rolling(60).mean()
    stress = m30.iloc[-1] < m60.iloc[-1]
    recover = stress is False and m30.iloc[-8] < m60.iloc[-8]
    pt.vote = 0.5 if recover else (-0.3 if stress else 0.0)
    pt.text = ("Miners recovering after stress - often a good sign." if recover else
               "Miners under stress (hash rate falling) - some may sell coins." if stress else "Miners healthy.")
    return pt


FINAL_50 = [p_big_move_alarm, p_range_used, p_projection, p_market_mood, p_move_speed, p_strong_levels,
            p_option_walls, p_calm_fast, p_money_in_out, p_big_players, p_dollar, p_rates, p_news, p_crowd,
            p_stop_pools, p_day_pace, p_busy_hours, p_weekday, p_stop_size, p_dont_chase, p_asia_box,
            p_first_hour, p_yesterday, p_last_week, p_round, p_vwap, p_busy_zones, p_trend_ladder, p_tf_agree,
            p_clean, p_stretch, p_push_weaker, p_tight_day, p_open_lines, p_buyers_sellers, p_pcr_vol,
            p_max_pain, p_expected_move, p_near_fear, p_big_trades, p_open_gaps, p_silver, p_gold_fear,
            p_central_banks, p_china, p_us_buyers, p_forced, p_whales, p_stocks, p_liquidity]
GOLD_ONLY = {"silver_check", "gold_fear", "central_banks", "china_demand", "gs_ratio", "miners", "inflation_exp"}
BTC_ONLY = {"crowd", "us_buyers", "forced_closings", "whales", "tech_link", "btc_dominance", "stablecoins",
            "fear_greed", "mvrv", "eth_lead", "hash_ribbon"}
EXTRAS = [e_gs_ratio, e_miners, e_inflation, e_bonds, e_gold_btc, e_tech, e_dominance, e_stables, e_fng,
          e_mvrv, e_eth, e_season, e_weekly, e_hash]
_IDS = {"p_crowd": "crowd", "p_silver": "silver_check", "p_gold_fear": "gold_fear", "p_central_banks": "central_banks",
        "p_china": "china_demand", "p_us_buyers": "us_buyers", "p_forced": "forced_closings", "p_whales": "whales",
        "e_gs_ratio": "gs_ratio", "e_miners": "miners", "e_inflation": "inflation_exp", "e_tech": "tech_link",
        "e_dominance": "btc_dominance", "e_stables": "stablecoins", "e_fng": "fear_greed", "e_mvrv": "mvrv",
        "e_eth": "eth_lead", "e_hash": "hash_ribbon"}


def _applies(fn, asset):
    pid = _IDS.get(fn.__name__)
    if pid in GOLD_ONLY:
        return asset == "gold"
    if pid in BTC_ONLY:
        return asset == "btc"
    return True


def _broken(f):
    """A point whose code hit an error still shows up (grey, 'no data') with its proper name."""
    import inspect, re
    try:
        m = re.search(r'Point\("([^"]+)", "([^"]+)", "([^"]+)", "([^"]+)", (True|False)', inspect.getsource(f))
        return Point(m[1], m[2], m[3], m[4], m[5] == "True")
    except Exception:
        return Point(f.__name__, "?", f.__name__[2:].replace("_", " ").title(), "Outside", False)


def compute(ctx, full=True):
    fns = [f for f in FINAL_50 if _applies(f, ctx.asset)]
    if full:
        fns += [f for f in EXTRAS if _applies(f, ctx.asset)]
    out = []
    for f in fns:
        try:
            pt = f(ctx)
        except Exception as e:  # noqa - one broken point must never stop the report
            import logging
            logging.getLogger("trishul").warning("point %s failed: %s", f.__name__, e)
            pt = _broken(f)
        out.append(pt.finish())
    return out
