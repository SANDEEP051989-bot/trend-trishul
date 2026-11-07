"""AI Inspector: Gemini reads the results and writes 1-2 plain-English lines.
It points out conflicts and missing data. If Gemini is not reachable, a simple rule-based note is used."""
import json, logging, re
from . import config, data

log = logging.getLogger("trishul.inspector")


def _rule_note(asset, points, fam, ver, failed):
    ups = [f for f, v in fam.items() if v["word"] == "Up"]
    dns = [f for f, v in fam.items() if v["word"] == "Down"]
    line = ""
    if ver["side"] == 1 and dns:
        line = f"Leaning up, but {', '.join(dns)} point down - buy only on dips."
    elif ver["side"] == -1 and ups:
        line = f"Leaning down, but {', '.join(ups)} point up - don't sell lows."
    elif ver["side"] == 0:
        line = "Signals are split - patience is the trade right now."
    else:
        line = "Most families agree - follow the bias, keep stops."
    miss = sum(p.vote is None for p in points)
    warn = f"{miss} points had no data this time." if miss >= 5 else ""
    return {"line": line, "warning": warn}


def inspect(asset, points, fam, ver, failed, full=False):
    if not config.GEMINI_API_KEY:
        return _rule_note(asset, points, fam, ver, failed)
    top = [{"name": p.name, "says": p.text, "vote": p.vote, "tone": p.tone} for p in points if p.top or p.tone in ("warn", "alarm")]
    payload = {
        "asset": "Gold" if asset == "gold" else "Bitcoin",
        "verdict": ver["word"], "percent": ver["pct"], "advice": ver["advice"],
        "family_votes": {k: v["word"] for k, v in fam.items()},
        "key_points": top[:24],
        "points_with_no_data": [p.name for p in points if p.vote is None],
        "failed_sources": sorted(set(failed))[:15],
    }
    prompt = (
        "You are the AI Inspector of a trading report for a trader who is NOT highly educated. "
        "Read the JSON results. Write in very simple, plain English (short words, no jargon, no abbreviations). "
        f"Return ONLY JSON: {{\"line\": \"{'2-3' if full else '1-2'} short sentences: what matters most now and any conflict "
        "between the families (e.g. trend up but dollar strong)\", \"warning\": \"one short sentence about missing or "
        "odd data, or empty string\"}. Never promise profit. Never invent numbers that are not in the JSON.\n\n"
        + json.dumps(payload, default=str))
    for model in config.GEMINI_MODELS:
        try:
            r = data.S.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model.strip()}:generateContent",
                            headers={"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"},
                            json={"contents": [{"parts": [{"text": prompt}]}],
                                  "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}},
                            timeout=45)
            r.raise_for_status()
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            txt = re.sub(r"^```(json)?|```$", "", txt.strip()).strip()
            out = json.loads(txt)
            return {"line": str(out.get("line", ""))[:400], "warning": str(out.get("warning", ""))[:200]}
        except Exception as e:  # noqa
            log.warning("gemini %s failed: %s", model, e)
    return _rule_note(asset, points, fam, ver, failed)
