"""Family voting -> final verdict, percentage and one-line advice."""
import numpy as np
from .points import FAMILIES


def family_votes(points):
    fam = {}
    for f in FAMILIES:
        ps = [p for p in points if p.family == f]
        dirs = [p.vote for p in ps if p.directional and p.vote is not None]
        warns = [p for p in ps if p.tone in ("warn", "alarm")]
        if dirs:
            v = float(np.mean(dirs))
            word = "Up" if v > 0.15 else "Down" if v < -0.15 else "Neutral"
        else:
            v, word = None, "Careful" if warns else "Neutral"
        if word == "Neutral" and warns and f in ("Range", "Timing"):
            word = "Careful"
        fam[f] = {"score": v, "word": word, "n": len(ps), "with_data": sum(p.vote is not None for p in ps)}
    return fam


def verdict(points, fam):
    scores = [x["score"] for x in fam.values() if x["score"] is not None]
    s = float(np.mean(scores)) if scores else 0.0
    pctv = int(round(50 + 50 * min(1.0, abs(s))))
    if s > 0.12:
        word, side = "LEANING UP", 1
    elif s < -0.12:
        word, side = "LEANING DOWN", -1
    else:
        word, side = "NO CLEAR SIDE", 0
    P = {p.id: p for p in points}
    alarm = P.get("big_move_alarm")
    news = P.get("news_alert")
    chase = P.get("dont_chase")
    proj = P.get("projection_lines")
    if alarm and alarm.extra.get("on"):
        advice = "Big move likely soon - keep stops ready and trade small."
    elif news and news.extra.get("mins") is not None and news.extra["mins"] <= 120:
        advice = f"Big news ({news.extra['title']}) is close - wait until it is out."
    elif proj and proj.tone == "warn" and ("ABOVE" in proj.text or "BELOW" in proj.text):
        advice = "A big day: price broke a projection line - don't trade against the move."
    elif side == 1 and chase and chase.extra.get("active"):
        advice = "Up bias, but most of today's move is done - wait for a dip."
    elif side == -1 and chase and chase.extra.get("active"):
        advice = "Down bias, but most of today's move is done - wait for a bounce."
    elif side == 1:
        advice = "Buyers in control - buy dips, don't chase."
    elif side == -1:
        advice = "Sellers in control - sell bounces, don't chase."
    else:
        advice = "No clear side - wait for a better setup."
    agree = sum(1 for x in fam.values() if x["score"] is not None and np.sign(x["score"]) == side and side != 0)
    return {"score": s, "pct": pctv, "word": word, "side": side, "advice": advice,
            "families_agree": agree, "families_voting": len(scores)}
