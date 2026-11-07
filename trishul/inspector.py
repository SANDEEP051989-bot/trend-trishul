"""AI Inspector: Gemini reads the results and writes 1-2 plain-English lines.
It points out conflicts and missing data. If Gemini is not reachable, a simple rule-based note is used,
and the card says why (so you know what to fix)."""
import json, logging, re
from . import config, data

log = logging.getLogger("trishul.inspector")
BASE = "https://generativelanguage.googleapis.com/v1beta"


def _rule_note(asset, points, fam, ver, failed, why=""):
    ups = [f for f, v in fam.items() if v["word"] == "Up"]
    dns = [f for f, v in fam.items() if v["word"] == "Down"]
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
    if why:
        warn = (warn + " " if warn else "") + f"(Simple mode: {why})"
    return {"line": line, "warning": warn}


def _models():
    """Gemini models this key can use, best first (newest 'flash' models)."""
    names = [m.strip() for m in config.GEMINI_MODELS if m.strip()]
    try:
        r = data.S.get(f"{BASE}/models", headers={"x-goog-api-key": config.GEMINI_API_KEY},
                       params={"pageSize": 200}, timeout=20)
        if r.ok:
            found = []
            for m in r.json().get("models", []):
                n = m.get("name", "").replace("models/", "")
                if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n \
                        and not any(x in n for x in ("image", "tts", "audio", "live", "thinking", "exp")):
                    found.append(n)
            def ver(n):
                v = re.findall(r"(\d+(?:\.\d+)?)", n)
                return (float(v[0]) if v else 0, "lite" not in n, "preview" not in n)
            found.sort(key=ver, reverse=True)
            names = found[:4] + [n for n in names if n not in found]
        else:
            log.warning("gemini list models failed %s %s", r.status_code, r.text[:200])
    except Exception as e:  # noqa
        log.warning("gemini list models error %s", e)
    return names


def inspect(asset, points, fam, ver, failed, full=False):
    if not config.GEMINI_API_KEY:
        return _rule_note(asset, points, fam, ver, failed, "add the GEMINI_API_KEY secret for AI notes")
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
    last_err = "Gemini not reachable"
    for model in _models():
        try:
            r = data.S.post(f"{BASE}/models/{model}:generateContent",
                            headers={"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"},
                            json={"contents": [{"parts": [{"text": prompt}]}],
                                  "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}},
                            timeout=60)
            if not r.ok:
                last_err = {400: "Gemini key not valid", 403: "Gemini key not allowed", 404: "Gemini model not found",
                            429: "Gemini daily limit reached"}.get(r.status_code, f"Gemini error {r.status_code}")
                log.warning("gemini %s failed %s %s", model, r.status_code, r.text[:300])
                if r.status_code in (400, 403):
                    break
                continue
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            txt = re.sub(r"^```(json)?|```$", "", txt.strip()).strip()
            out = json.loads(txt)
            log.info("gemini ok with %s", model)
            return {"line": str(out.get("line", ""))[:400], "warning": str(out.get("warning", ""))[:200]}
        except (ValueError, KeyError, IndexError) as e:
            last_err = "Gemini reply could not be read"
            log.warning("gemini %s bad reply: %s", model, e)
        except Exception as e:  # noqa - network problems
            last_err = "Gemini not reachable"
            log.warning("gemini %s error: %s", model, e)
    return _rule_note(asset, points, fam, ver, failed, last_err)
