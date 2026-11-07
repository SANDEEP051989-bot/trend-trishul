"""Builds the market picture (days, lines, levels, time-of-day stats) from price bars."""
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

from . import config, data

UTC = timezone.utc
NY = "America/New_York"


def rma(x, n):
    x = pd.Series(x, dtype=float)
    return x.ewm(alpha=1 / n, adjust=False).mean()


def ema(x, n):
    return pd.Series(x, dtype=float).ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up = rma(d.clip(lower=0), n)
    dn = rma(-d.clip(upper=0), n)
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def true_range(df):
    pc = df.close.shift(1)
    return pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)


def day_key(idx, asset):
    """Trading-day label for each timestamp. Gold day ends 17:00 New York; Bitcoin day = UTC date."""
    if asset == "gold":
        ny = idx.tz_convert(NY).tz_localize(None)
        return (ny + pd.Timedelta(hours=7)).normalize()
    return idx.tz_convert(UTC).tz_localize(None).normalize()


def slot_key(idx, asset):
    """15-minute slot of the day (0..95). Gold uses New York clock so summer/winter time does not shift it."""
    t = idx.tz_convert(NY) if asset == "gold" else idx.tz_convert(UTC)
    return t.hour * 4 + t.minute // 15


def gold_open(now=None):
    """Gold (COMEX) trades Sun 18:00 to Fri 17:00 New York, with a 17:00-18:00 break each day."""
    from zoneinfo import ZoneInfo
    now = now or datetime.now(UTC)
    ny = now.astimezone(ZoneInfo(NY))
    wd, h = ny.weekday(), ny.hour
    if wd == 5:
        return False
    if wd == 6 and h < 18:
        return False
    if wd == 4 and h >= 17:
        return False
    return True


def volume_profile(df, rows=60, va=0.70):
    if df is None or len(df) < 4:
        return None
    lo, hi = df.low.min(), df.high.max()
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, rows + 1)
    vol = np.zeros(rows)
    v = df.volume.fillna(0).values
    if v.sum() <= 0:
        v = np.ones(len(df))
    for (l, h), vv in zip(df[["low", "high"]].values, v):
        a = max(0, np.searchsorted(edges, l, side="right") - 1)
        b = min(rows - 1, np.searchsorted(edges, h, side="left") - 1)
        b = max(a, b)
        vol[a:b + 1] += vv / (b - a + 1)
    poc = int(vol.argmax())
    lo_i = hi_i = poc
    tot, need = vol[poc], vol.sum() * va
    while tot < need and (lo_i > 0 or hi_i < rows - 1):
        up = vol[hi_i + 1] if hi_i < rows - 1 else -1
        dn = vol[lo_i - 1] if lo_i > 0 else -1
        if up >= dn:
            hi_i += 1
            tot += vol[hi_i]
        else:
            lo_i -= 1
            tot += vol[lo_i]
    mid = (edges[:-1] + edges[1:]) / 2
    return {"poc": float(mid[poc]), "vah": float(edges[hi_i + 1]), "val": float(edges[lo_i])}


def swings(df, left=3, right=3):
    hs, ls = [], []
    h, l = df.high.values, df.low.values
    for i in range(left, len(df) - right):
        if h[i] == h[i - left:i + right + 1].max():
            hs.append((df.index[i], h[i], i))
        if l[i] == l[i - left:i + right + 1].min():
            ls.append((df.index[i], l[i], i))
    return hs, ls


class Market:
    """Everything one asset's points need, computed once per run."""

    def __init__(self, asset, now=None, px=None):
        self.asset = asset
        self.cfg = config.ASSETS[asset]
        self.now = now or datetime.now(UTC)
        px = px or data.prices(asset)
        self.source = px.get("source", "")
        self.m15, self.h1, self.d1 = px["m15"].copy(), px["h1"].copy(), px["d1"].copy()
        self.price = float(self.m15.close.iloc[-1])
        self.last_bar_time = self.m15.index[-1]
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        a = self.asset
        m = self.m15
        m["day"] = day_key(m.index, a)
        m["slot"] = slot_key(m.index, a)
        self.today = m["day"].iloc[-1]
        t = m[m.day == self.today]
        self.t_bars = t
        self.t_open, self.t_high, self.t_low = float(t.open.iloc[0]), float(t.high.max()), float(t.low.min())

        # completed daily bars
        d = self.d1.copy()
        dk = day_key(d.index, a) if a == "btc" else d.index.tz_convert(UTC).tz_localize(None).normalize()
        d["day"] = dk
        d = d[d.day < self.today].groupby("day").agg(open=("open", "first"), high=("high", "max"),
                                                     low=("low", "min"), close=("close", "last"))
        self.days = d
        d["tr"] = true_range(d)
        d["atr"] = rma(d.tr, 14)
        d["rng_pct"] = (d.high - d.low) / d.close.shift(1) * 100
        self.prev = d.iloc[-1]
        self.atr_d = float(d.atr.iloc[-1])
        self.adr_pct = float(d.rng_pct.tail(20).median())
        self.adr_usd = self.adr_pct / 100 * float(self.prev.close)
        self.used_pct = (self.t_high - self.t_low) / self.adr_usd * 100 if self.adr_usd else np.nan
        mult = self.cfg["proj_mult"]
        self.upper = float(self.prev.close + mult * self.atr_d)
        self.lower = float(self.prev.close - mult * self.atr_d)
        self.day_change_pct = (self.price / float(self.prev.close) - 1) * 100

        # weeks / months from completed days
        w = d.copy()
        w["wk"] = [x.to_period("W-SUN") for x in w.index]
        cur_wk = pd.Timestamp(self.today).to_period("W-SUN")
        wk = w.groupby("wk").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
        prev_w = wk[wk.index < cur_wk]
        self.prev_week = prev_w.iloc[-1] if len(prev_w) else None
        this_w = w[w.wk == cur_wk]
        self.week_open = float(this_w.open.iloc[0]) if len(this_w) else self.t_open
        month = w[(w.index.month == pd.Timestamp(self.today).month) & (w.index.year == pd.Timestamp(self.today).year)]
        self.month_open = float(month.open.iloc[0]) if len(month) else self.t_open
        wkhi = pd.concat([this_w.high, pd.Series([self.t_high])]).max() if len(this_w) else self.t_high
        wklo = pd.concat([this_w.low, pd.Series([self.t_low])]).min() if len(this_w) else self.t_low
        self.week_high, self.week_low = float(wkhi), float(wklo)

        # hourly helpers
        h = self.h1
        h["tr"] = true_range(h)
        self.atr_h = float(rma(h.tr, 14).iloc[-1])
        self.ema50_h = float(ema(h.close, 50).iloc[-1])

        # time-of-day statistics from 15m bars (last ~30 sessions)
        m["tr"] = true_range(m)
        past = m[m.day < self.today]
        self.slot_med = past.groupby("slot").tr.median()
        last = m.iloc[-2] if len(m) > 2 else m.iloc[-1]          # last CLOSED 15m bar
        self.last_closed = last
        med = self.slot_med.get(int(last.slot), np.nan)
        self.speed = float(last.tr / med) if med and med > 0 else np.nan
        self.slot_now = int(m.slot.iloc[-1])
        self.hour_share = self._hour_share(past)
        self.pace = self._pace(past)

        # previous day's busy price zones + today's VWAP
        pdays = sorted(past.day.unique())
        self.profile = volume_profile(past[past.day == pdays[-1]]) if pdays else None
        tv = t.volume.fillna(0)
        w_ = tv if tv.sum() > 0 else pd.Series(1.0, index=t.index)
        hlc3 = (t.high + t.low + t.close) / 3
        self.vwap = float((hlc3 * w_).sum() / w_.sum())

    def _hour_share(self, past):
        """Median 15m range of each hour vs the day's average hour."""
        if not len(past):
            return {}
        hr = (past.slot // 4)
        per = past.groupby(hr).tr.median()
        return (per / per.mean()).to_dict()

    def _pace(self, past):
        """Today's range so far vs the share of a normal day usually done by this time."""
        shares = []
        for dk, g in past.groupby("day"):
            if len(g) < 40:
                continue
            final = g.high.max() - g.low.min()
            sofar = g[g.slot <= self.slot_now]
            if final > 0 and len(sofar):
                shares.append((sofar.high.max() - sofar.low.min()) / final)
        if len(shares) < 5 or not self.adr_usd:
            return np.nan
        exp = float(np.median(shares))
        act = (self.t_high - self.t_low) / self.adr_usd
        return act / exp if exp > 0 else np.nan

    # ------------------------------------------------------------------
    def session_box(self, start_h, end_h, tz=UTC):
        t = self.t_bars
        lt = t.index.tz_convert(tz)
        b = t[(lt.hour >= start_h) & (lt.hour < end_h)]
        done = self.now.astimezone(lt.tz).hour >= end_h if len(lt) else False
        if not len(b):
            return None
        return {"high": float(b.high.max()), "low": float(b.low.min()), "done": bool(done)}

    def levels(self):
        """All key levels with their method family (for Strong Levels / Zone Atlas)."""
        p = self.prev
        piv = (p.high + p.low + p.close) / 3
        L = [(float(p.high), "Yesterday's high", "yday"), (float(p.low), "Yesterday's low", "yday"),
             (float(p.close), "Yesterday's close", "yday"), (float(piv), "Pivot", "pivot"),
             (float(2 * piv - p.low), "Pivot R1", "pivot"), (float(2 * piv - p.high), "Pivot S1", "pivot"),
             (self.vwap, "Average price line", "vwap")]
        if self.profile:
            L += [(self.profile["poc"], "Busiest price", "profile"), (self.profile["vah"], "Busy zone top", "profile"),
                  (self.profile["val"], "Busy zone bottom", "profile")]
        if self.prev_week is not None:
            L += [(float(self.prev_week.high), "Last week's high", "week"), (float(self.prev_week.low), "Last week's low", "week")]
        step = self.cfg["round_small"]
        base = round(self.price / step) * step
        for k in range(-6, 7):
            L.append((base + k * step, f"Round number {base + k * step:,.0f}", "round"))
        return L

    def zones(self):
        tol = self.price * self.cfg["tol_pct"] / 100
        L = sorted(self.levels())
        zones, cur = [], []
        for lv in L:
            if cur and lv[0] - cur[-1][0] > tol:
                zones.append(cur)
                cur = []
            cur.append(lv)
        if cur:
            zones.append(cur)
        out = []
        for z in zones:
            fams = {x[2] for x in z}
            grade = "Strong" if len(fams) >= 3 else ("Medium" if len(fams) == 2 else "Weak")
            out.append({"price": float(np.mean([x[0] for x in z])), "grade": grade, "n": len(fams),
                        "names": [x[1] for x in z]})
        return out
