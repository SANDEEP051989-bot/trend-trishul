"""Track record: every point's vote is saved with the price; 24 hours later we check if it was right.
After some weeks this shows which points really help (shown in the full report)."""
import json, os
from datetime import timedelta
import pandas as pd
from . import config

HORIZON_H = 24
PENDING = os.path.join(config.STATE_DIR, "track_pending.json")
SUMMARY = os.path.join(config.STATE_DIR, "track_summary.json")


def _load(p, default):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return default


def _save(p, v):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(v, f, indent=0)


def record(asset, points, ver, price, now):
    pend = _load(PENDING, [])
    votes = {p.id: p.vote for p in points if p.directional and p.vote not in (None, 0, 0.0)}
    votes["verdict"] = ver["side"] if ver["side"] else None
    votes = {k: v for k, v in votes.items() if v}
    pend.append({"t": now.timestamp(), "a": asset, "p": price, "v": votes})
    _save(PENDING, pend[-2000:])


def score(asset, h1):
    """Check pending votes older than 24h against the 1-hour closes."""
    pend = _load(PENDING, [])
    summ = _load(SUMMARY, {})
    keep = []
    closes = h1.close
    for r in pend:
        if r["a"] != asset:
            keep.append(r)
            continue
        target = pd.Timestamp(r["t"], unit="s", tz="UTC") + timedelta(hours=HORIZON_H)
        if target > closes.index[-1]:
            keep.append(r)
            continue
        after = closes[closes.index >= target]
        if not len(after):
            keep.append(r)
            continue
        move = float(after.iloc[0]) - r["p"]
        s = summ.setdefault(asset, {})
        for pid, v in r["v"].items():
            x = s.setdefault(pid, [0, 0])
            x[0] += 1
            x[1] += 1 if (move > 0) == (v > 0) and move != 0 else 0
    _save(PENDING, keep)
    _save(SUMMARY, summ)
    return summ.get(asset, {})


def label(summ, pid, min_n=10):
    x = summ.get(pid)
    if not x or x[0] < min_n:
        return ""
    return f"right {x[1] / x[0] * 100:.0f}% of {x[0]}"
