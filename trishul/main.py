"""Trend Trishul - runs every 15 minutes on GitHub Actions and decides what to send:
 - short card every 2 hours (India time, even hours)
 - full report with all points at 8 AM and 8 PM India time
 - instant alerts any time: Big Move Alarm turns on, a projection line breaks fast, big US news in 30 minutes
Usage: python -m trishul.main [auto|short|full|test]"""
import json, logging, os, sys, time
from datetime import datetime, timezone, timedelta

from . import cards, config, data, decide, inspector, options, telegram, tracker
from .engine import Market, gold_open
from .points import Ctx, compute, p_big_move_alarm, next_event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("trishul")
UTC = timezone.utc
IST = timezone(timedelta(minutes=config.IST_OFFSET_MIN))
STATE = os.path.join(config.STATE_DIR, "state.json")
LIVE = os.path.join(config.CACHE_DIR, "live.json")


def load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


def save(p, v):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(v, f, indent=1, default=str)


def next_update_text(now):
    t = now.astimezone(IST).replace(minute=0, second=0, microsecond=0)
    t += timedelta(hours=1)
    while t.hour % config.SHORT_EVERY_HOURS:
        t += timedelta(hours=1)
    kind = "full report" if t.hour in config.FULL_REPORT_HOURS_IST else "update"
    return f"Next {kind} {t.strftime('%I %p').lstrip('0')} IST"


def build(asset, now, live, news, full):
    mk = Market(asset, now)
    opt = data.safe(f"options_{asset}", lambda: data.cached(
        f"opt_analysis_{asset}", 30 if asset == "btc" else 60, lambda: options.analyse(asset, mk.price)))
    ctx = Ctx(asset, mk, opt, news, live)
    return mk, ctx


def run(mode="auto"):
    now = datetime.now(UTC)
    ist = now.astimezone(IST)
    state, live = load(STATE), load(LIVE)
    sent = state.setdefault("sent", {})
    news = data.news_calendar() or []
    slot = ist.strftime("%Y-%m-%d %H")
    full_hour = ist.hour in config.FULL_REPORT_HOURS_IST
    short_hour = ist.hour % config.SHORT_EVERY_HOURS == 0 and not full_hour
    test = mode == "test"

    # ---------------- instant news alert (one message for both markets)
    nx = next_event(news, now)
    if nx:
        mins = (nx[0] - now).total_seconds() / 60
        key = f"{nx[1]}|{nx[0].isoformat()}"
        if 0 < mins <= config.NEWS_WARN_MIN and key not in state.get("news_sent", []):
            when = nx[0].astimezone(IST).strftime("%I:%M %p").lstrip("0")
            img = cards.alert_card(f"BIG US NEWS IN {int(mins)} MIN", [
                f"{nx[1]} at {when} India time.",
                "Gold and Bitcoin can jump either way in the first minutes.",
                "Wait until it is out. Don't place tight stops right now."], cards.AMBER, now)
            if telegram.send_photo(img, f"Big US news in {int(mins)} min: {nx[1]}"):
                state.setdefault("news_sent", []).append(key)
                state["news_sent"] = state["news_sent"][-30:]

    for asset in ("gold", "btc"):
        name = config.ASSETS[asset]["name"]
        if asset == "gold" and not gold_open(now) and not test:
            log.info("gold market closed - skipping gold")
            continue
        want_full = test or mode == "full" or (mode == "auto" and full_hour and sent.get(f"{asset}_full") != slot)
        want_short = test or mode == "short" or (mode == "auto" and short_hour and sent.get(f"{asset}_short") != slot)
        try:
            mk, ctx = build(asset, now, live, news, want_full)
        except Exception as e:  # noqa
            log.exception("could not build %s: %s", asset, e)
            continue
        if asset == "btc":
            hl = data.hyperliquid_btc()
            if hl:
                h = live.setdefault("oi_hist", [])
                h.append([now.timestamp(), hl["oi"], mk.price])
                live["oi_hist"] = [x for x in h if now.timestamp() - x[0] < 3 * 86400]

        # ---------------- instant alerts (checked every run)
        alarm = p_big_move_alarm(ctx).finish()
        was_on = state.setdefault("alarm_on", {}).get(asset, False)
        if alarm.extra.get("on") and not was_on and not test:
            img = cards.alert_card(f"{name}: BIG MOVE ALARM ON",
                                   [f"{len(alarm.extra['signs'])} of 5 warning signs: " + "; ".join(alarm.extra["signs"]) + ".",
                                    "A big move is likely soon. The direction is NOT known.",
                                    "Keep stops ready, trade small, don't fight a fast break."], cards.RED, now)
            telegram.send_photo(img, f"{name}: Big Move Alarm ON")
        state["alarm_on"][asset] = bool(alarm.extra.get("on"))

        lc = mk.last_closed
        side = "up" if lc.close > mk.upper else "down" if lc.close < mk.lower else None
        if side and mk.speed and mk.speed > 1.5 and not test:
            k = f"{asset}|{mk.today}|{side}"
            if k not in state.get("breaks", []):
                line = mk.upper if side == "up" else mk.lower
                img = cards.alert_card(f"{name}: FAST BREAK {'UP' if side == 'up' else 'DOWN'}", [
                    f"Price {cards._money(float(lc.close), asset)} broke the {'top' if side == 'up' else 'bottom'} "
                    f"projection line {cards._money(line, asset)} fast ({mk.speed:.1f}x normal speed).",
                    "This happens only 2-3 times a month. It is a big day.",
                    f"Don't {'sell' if side == 'up' else 'buy'} against it. Wait for the move to settle."],
                    cards.GREEN if side == "up" else cards.RED, now)
                if telegram.send_photo(img, f"{name}: projection line broken {side}"):
                    state.setdefault("breaks", []).append(k)
                    state["breaks"] = state["breaks"][-40:]

        if not (want_full or want_short):
            continue

        # ---------------- scheduled cards
        data.FAILED.clear()
        pts = compute(ctx, full=want_full)
        fam = decide.family_votes(pts)
        ver = decide.verdict(pts, fam)
        note = inspector.inspect(asset, pts, fam, ver, data.FAILED, full=want_full)
        summ = data.safe("track_score", lambda: tracker.score(asset, mk.h1), {}) or {}
        foot = f"Data: {mk.source}  -  {next_update_text(now)}  -  Not financial advice"
        cap = f"{name} {cards._money(mk.price, asset)} - {ver['word'].title()} {ver['pct']}% - {ver['advice']}"
        ok = True
        if want_short and (test or not want_full):
            img = cards.short_card(asset, name, mk, pts, fam, ver, note, now, foot, "TEST" if test else "")
            ok = telegram.send_photo(img, cap)
            if ok and not test:
                sent[f"{asset}_short"] = slot
        if want_full:
            pages = cards.full_report(asset, name, mk, pts, fam, ver, note, now, foot, lambda pid: tracker.label(summ, pid))
            ok = telegram.send_album(pages, "FULL REPORT - " + cap)
            if ok and not test:
                sent[f"{asset}_full"] = slot
        if not test:
            tracker.record(asset, pts, ver, mk.price, now)
        log.info("%s %s sent=%s verdict=%s %s%%", asset, "full" if want_full else "short", ok, ver["word"], ver["pct"])

    save(STATE, state)
    save(LIVE, live)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TRISHUL_MODE", "auto") or "auto")
