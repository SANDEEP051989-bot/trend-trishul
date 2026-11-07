"""Picture cards for Telegram (dark background, gold/green/red, big plain words)."""
import os
from datetime import timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

IST = timezone(timedelta(minutes=330))
W = 1080
PAD = 40
BG = (13, 17, 23)
PANEL = (22, 27, 34)
LINE = (44, 51, 61)
GOLD = (232, 184, 74)
WHITE = (240, 243, 246)
SOFT = (176, 184, 194)
GREY = (120, 129, 140)
GREEN = (46, 204, 113)
RED = (235, 87, 87)
AMBER = (245, 166, 35)
BLUE = (88, 166, 255)
TONE = {"up": GREEN, "down": RED, "neutral": GREY, "warn": AMBER, "alarm": RED, "nodata": (70, 76, 86)}
WORD_COL = {"Up": GREEN, "Down": RED, "Neutral": GREY, "Careful": AMBER}


def _font_dir():
    try:
        import matplotlib
        return os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    except Exception:
        return "/usr/share/fonts/truetype/dejavu"


FD = _font_dir()
_cache = {}


def F(size, bold=False, italic=False):
    k = (size, bold, italic)
    if k not in _cache:
        name = "DejaVuSans" + ("-Bold" if bold else "") + ("Oblique" if italic and bold else "-Oblique" if italic else "") + ".ttf"
        try:
            _cache[k] = ImageFont.truetype(os.path.join(FD, name), size)
        except Exception:
            _cache[k] = ImageFont.load_default()
    return _cache[k]


class Canvas:
    def __init__(self, h=4000):
        self.im = Image.new("RGB", (W, h), BG)
        self.d = ImageDraw.Draw(self.im)
        self.y = 0

    def tw(self, text, font):
        return self.d.textlength(text, font=font)

    def wrap(self, text, font, width):
        words, lines, cur = str(text).split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if self.tw(t, font) <= width:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    def text(self, x, y, s, font, fill=WHITE, anchor="la"):
        self.d.text((x, y), s, font=font, fill=fill, anchor=anchor)

    def para(self, x, y, s, font, width, fill=WHITE, gap=8, max_lines=None):
        lines = self.wrap(s, font, width)
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            while self.tw(lines[-1] + " ...", font) > width and " " in lines[-1]:
                lines[-1] = lines[-1].rsplit(" ", 1)[0]
            lines[-1] += " ..."
        lh = font.size + gap
        for i, ln in enumerate(lines):
            self.text(x, y + i * lh, ln, font, fill)
        return len(lines) * lh

    def panel(self, y, h, fill=PANEL, outline=LINE, r=26):
        self.d.rounded_rectangle((PAD, y, W - PAD, y + h), radius=r, fill=fill, outline=outline, width=2)

    def dot(self, x, y, col, r=11):
        self.d.ellipse((x - r, y - r, x + r, y + r), fill=col)

    def pill(self, x, y, s, font, col, filled=True, padx=18, h=None):
        w = self.tw(s, font) + 2 * padx
        h = h or font.size + 18
        if filled:
            self.d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=col)
            self.text(x + padx, y + h / 2, s, font, BG, anchor="lm")
        else:
            self.d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, outline=col, width=3)
            self.text(x + padx, y + h / 2, s, font, col, anchor="lm")
        return w

    def bar(self, x, y, w, h, frac, col, back=(38, 44, 53)):
        self.d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=back)
        f = max(0.0, min(1.0, frac))
        if f > 0.01:
            self.d.rounded_rectangle((x, y, x + max(h, w * f), y + h), radius=h // 2, fill=col)

    def crop(self, bottom):
        return self.im.crop((0, 0, W, int(bottom)))


def _money(x, asset):
    if x is None:
        return "-"
    return f"${x:,.0f}" if asset == "btc" or abs(x) >= 100 else f"${x:,.1f}"


def _verdict_col(ver):
    return GREEN if ver["side"] == 1 else RED if ver["side"] == -1 else GOLD


# --------------------------------------------------------------------------- pieces
def header(c, asset, name, mk, now, label="", compact=False):
    y0 = c.y + PAD
    h = 200
    c.panel(y0, h)
    c.text(PAD + 32, y0 + 26, "TREND TRISHUL" + (f"  -  {label}" if label else ""), F(26, True), GOLD)
    c.text(PAD + 32, y0 + 66, name, F(66, True), WHITE)
    c.text(W - PAD - 32, y0 + 30, now.astimezone(IST).strftime("%d %b  %I:%M %p IST").replace(" 0", " "), F(26), SOFT, anchor="ra")
    c.text(W - PAD - 32, y0 + 68, _money(mk.price, asset), F(60, True), WHITE, anchor="ra")
    ch = mk.day_change_pct
    c.text(W - PAD - 32, y0 + h - 34, f"{'+' if ch >= 0 else ''}{ch:.2f}% today", F(28, True), GREEN if ch >= 0 else RED, anchor="rs")
    c.y = y0 + h


def verdict_box(c, ver):
    y0 = c.y + 24
    col = _verdict_col(ver)
    lines = c.wrap(ver["advice"], F(34), W - 2 * PAD - 64)
    h = 92 + 44 + 30 + len(lines) * 44 + 30
    c.panel(y0, h, outline=col)
    c.text(PAD + 32, y0 + 28, f"{ver['word']}  {ver['pct']}%", F(56, True), col)
    c.bar(PAD + 32, y0 + 108, W - 2 * PAD - 64, 22, ver["pct"] / 100 if ver["side"] else 0.5, col)
    c.para(PAD + 32, y0 + 158, ver["advice"], F(34), W - 2 * PAD - 64, WHITE, gap=10)
    c.y = y0 + h


def alarm_strip(c, alarm):
    y0 = c.y + 22
    on = bool(alarm and alarm.extra.get("on"))
    if on:
        c.d.rounded_rectangle((PAD, y0, W - PAD, y0 + 84), radius=26, fill=RED)
        c.text(PAD + 32, y0 + 42, "BIG MOVE ALARM: ON", F(36, True), WHITE, anchor="lm")
        c.text(W - PAD - 32, y0 + 42, f"{len(alarm.extra['signs'])} of 5 signs", F(28, True), WHITE, anchor="rm")
        c.y = y0 + 84
        sub = "; ".join(alarm.extra["signs"])
        hh = c.para(PAD + 32, c.y + 14, sub, F(26), W - 2 * PAD - 64, SOFT, gap=6, max_lines=3)
        c.y += hh + 14
    else:
        c.d.rounded_rectangle((PAD, y0, W - PAD, y0 + 74), radius=26, outline=LINE, width=2, fill=PANEL)
        c.text(PAD + 32, y0 + 37, "Big Move Alarm: OFF", F(32, True), SOFT, anchor="lm")
        c.text(W - PAD - 32, y0 + 37, "calm" if alarm and alarm.tone != "nodata" else "options data missing", F(26), GREY, anchor="rm")
        c.y = y0 + 74


def today_map(c, asset, mk, used_pt):
    y0 = c.y + 22
    h = 360
    c.panel(y0, h)
    c.text(PAD + 32, y0 + 24, "TODAY'S MAP", F(26, True), GOLD)
    x0, x1 = PAD + 70, W - PAD - 70
    yy = y0 + 150
    lo, hi = mk.lower, mk.upper
    span = hi - lo
    c.d.rounded_rectangle((x0, yy - 6, x1, yy + 6), radius=6, fill=(48, 56, 66))
    # today's range on the ruler
    def X(v):
        return x0 + (min(max(v, lo - 0.08 * span), hi + 0.08 * span) - lo) / span * (x1 - x0)
    c.d.rounded_rectangle((X(mk.t_low), yy - 6, X(mk.t_high), yy + 6), radius=6, fill=(90, 110, 140))
    c.d.line((x0, yy - 26, x0, yy + 26), fill=GREEN, width=5)
    c.d.line((x1, yy - 26, x1, yy + 26), fill=RED, width=5)
    px = X(mk.price)
    c.d.polygon([(px - 16, yy - 40), (px + 16, yy - 40), (px, yy - 12)], fill=WHITE)
    c.text(px, yy - 46, _money(mk.price, asset), F(28, True), WHITE, anchor="ms")
    c.text(x0, yy + 40, f"Bottom line {_money(lo, asset)}", F(26, True), GREEN, anchor="la")
    c.text(x0, yy + 76, f"{_money(mk.price - lo, asset)} below", F(24), SOFT, anchor="la")
    c.text(x1, yy + 40, f"Top line {_money(hi, asset)}", F(26, True), RED, anchor="ra")
    c.text(x1, yy + 76, f"{_money(hi - mk.price, asset)} above", F(24), SOFT, anchor="ra")
    # range used
    u = used_pt.extra.get("used", 0) if used_pt else 0
    by = y0 + h - 62
    c.text(PAD + 32, by + 12, "Range used", F(26, True), WHITE, anchor="lm")
    c.bar(PAD + 220, by, W - 2 * PAD - 220 - 150, 24, u / 150, AMBER if u >= 100 else BLUE)
    c.text(W - PAD - 32, by + 12, f"{u:.0f}%", F(30, True), AMBER if u >= 100 else WHITE, anchor="rm")
    c.y = y0 + h


def key_levels_panel(c, asset, kp, gp):
    """2 strongest resistances above, price, 2 strongest supports below, plus the nearest gap to fill."""
    if not kp or not kp.extra:
        return
    res, sup = kp.extra.get("res", []), kp.extra.get("sup", [])
    if not res and not sup:
        return
    y0 = c.y + 22
    inner = W - 2 * PAD - 64
    rows = [("RESISTANCE", z, RED) for z in sorted(res, key=lambda z: -z["price"])] + [None] + \
           [("SUPPORT", z, GREEN) for z in sup]
    gap_txt = ""
    if gp and gp.extra:
        g = [x for x in (gp.extra.get("above"), gp.extra.get("below")) if x]
        if g:
            gap_txt = "Gap to fill: " + ",  ".join(f"{_money(x[0], asset)} ({'above' if x is gp.extra.get('above') else 'below'})" for x in g)
    h = 70 + sum(96 if r else 46 for r in rows) + (50 if gap_txt else 0) + 10
    c.panel(y0, h)
    c.text(PAD + 32, y0 + 24, "KEY SUPPORT & RESISTANCE", F(26, True), GOLD)
    y = y0 + 70
    for r in rows:
        if r is None:
            c.d.line((PAD + 32, y + 22, W - PAD - 32, y + 22), fill=LINE, width=2)
            tw = c.tw("  PRICE NOW  ", F(22, True))
            c.d.rectangle((W / 2 - tw / 2, y + 8, W / 2 + tw / 2, y + 36), fill=PANEL)
            c.text(W / 2, y + 22, "PRICE NOW", F(22, True), SOFT, anchor="mm")
            y += 46
            continue
        kind, z, col = r
        c.d.rounded_rectangle((PAD + 32, y + 4, PAD + 40, y + 80), radius=4, fill=col)
        c.text(PAD + 60, y + 2, f"{kind}  {_money(z['price'], asset)}", F(30, True), col)
        c.text(W - PAD - 32, y + 6, z["grade"], F(24, True), WHITE if z["grade"] != "Medium" else SOFT, anchor="ra")
        c.para(PAD + 60, y + 44, ", ".join(z["names"][:4]), F(23), inner - 40, SOFT, gap=4, max_lines=1)
        y += 96
    if gap_txt:
        c.text(PAD + 32, y + 8, gap_txt, F(26, True), BLUE)
    c.y = y0 + h


def chips(c, items):
    y0 = c.y + 22
    n = len(items)
    gap = 16
    w = (W - 2 * PAD - gap * (n - 1)) / n
    for i, (k, v, col) in enumerate(items):
        x = PAD + i * (w + gap)
        c.d.rounded_rectangle((x, y0, x + w, y0 + 104), radius=22, fill=PANEL, outline=LINE, width=2)
        c.text(x + w / 2, y0 + 30, k, F(24), SOFT, anchor="mm")
        c.text(x + w / 2, y0 + 70, v, F(32, True), col, anchor="mm")
    c.y = y0 + 104


def rows_panel(c, title, pts, font=F(28), name_font=F(28, True), max_lines=2, track=None):
    y0 = c.y + 22
    inner = W - 2 * PAD - 64 - 40
    hh = 70
    blocks = []
    for p in pts:
        lines = c.wrap(p.text, font, inner)[:max_lines]
        bh = name_font.size + 10 + len(lines) * (font.size + 8) + 22
        blocks.append((p, bh))
        hh += bh
    c.panel(y0, hh)
    c.text(PAD + 32, y0 + 24, title, F(26, True), GOLD)
    y = y0 + 70
    for p, bh in blocks:
        c.dot(PAD + 44, y + name_font.size / 2 + 2, TONE.get(p.tone, GREY))
        c.text(PAD + 72, y, p.name, name_font, WHITE)
        if track:
            t = track(p.id)
            if t:
                c.text(W - PAD - 32, y + 2, t, F(22), GREY, anchor="ra")
        c.para(PAD + 72, y + name_font.size + 10, p.text, font, inner, SOFT, gap=8, max_lines=max_lines)
        y += bh
    c.y = y0 + hh


def family_grid(c, fam):
    y0 = c.y + 22
    names = list(fam.keys())
    cols = 4
    rows = (len(names) + cols - 1) // cols
    h = 70 + rows * 112
    c.panel(y0, h)
    c.text(PAD + 32, y0 + 24, "FAMILY VOTES", F(26, True), GOLD)
    cw = (W - 2 * PAD - 64) / cols
    for i, n in enumerate(names):
        r, k = divmod(i, cols)
        x = PAD + 32 + k * cw
        y = y0 + 72 + r * 112
        c.text(x, y, n, F(26), SOFT)
        word = fam[n]["word"]
        c.pill(x, y + 40, word, F(28, True), WORD_COL.get(word, GREY), filled=word != "Neutral")
    c.y = y0 + h


def inspector_box(c, note, full=False):
    y0 = c.y + 22
    inner = W - 2 * PAD - 64
    l1 = c.wrap(note.get("line", ""), F(32, italic=True), inner)
    l2 = c.wrap(note.get("warning", ""), F(26), inner) if note.get("warning") else []
    h = 74 + len(l1) * 42 + (len(l2) * 34 + 14 if l2 else 0) + 26
    c.panel(y0, h, outline=GOLD)
    c.text(PAD + 32, y0 + 24, "AI INSPECTOR", F(26, True), GOLD)
    y = y0 + 70
    for ln in l1:
        c.text(PAD + 32, y, ln, F(32, italic=True), WHITE)
        y += 42
    if l2:
        y += 14
        for ln in l2:
            c.text(PAD + 32, y, ln, F(26), AMBER)
            y += 34
    c.y = y0 + h


def footer(c, text):
    c.y += 26
    for ln in c.wrap(text, F(22), W - 2 * PAD):
        c.text(W / 2, c.y, ln, F(22), GREY, anchor="ma")
        c.y += 30
    c.y += PAD - 10


# --------------------------------------------------------------------------- whole cards
def short_card(asset, name, mk, points, fam, ver, note, now, footer_text, label=""):
    P = {p.id: p for p in points}
    c = Canvas()
    header(c, asset, name, mk, now, label)
    verdict_box(c, ver)
    alarm_strip(c, P.get("big_move_alarm"))
    today_map(c, asset, mk, P.get("range_used"))
    key_levels_panel(c, asset, P.get("key_levels"), P.get("open_gaps"))
    mood = P.get("market_mood")
    spd = P.get("move_speed")
    busy = P.get("busy_hours")
    mw = (mood.extra.get("mood") if mood and mood.extra else None) or "-"
    sw = (spd.extra.get("word") if spd and spd.extra else None) or "-"
    bw = (busy.extra.get("word") if busy and busy.extra else None) or "-"
    chips(c, [("Market mood", mw, AMBER if mw == "Hot" else BLUE if mw == "Quiet" else WHITE),
              ("Move speed", sw.split()[0] if sw != "-" else "-", AMBER if sw.startswith(("Heat", "News")) else WHITE),
              ("This hour", bw, AMBER if bw == "Busy" else WHITE)])
    money = [P[k] for k in ("money_in_out", "big_players", "option_walls", "crowd") if k in P]
    rows_panel(c, "BIG MONEY", money[:4], font=F(26), name_font=F(27, True), max_lines=2)
    family_grid(c, fam)
    shown = {"big_move_alarm", "key_levels", "open_gaps", "range_used", "projection_lines", "market_mood", "move_speed", "busy_hours",
             "money_in_out", "big_players", "option_walls", "crowd"}
    key = [p for p in points if p.top and p.id not in shown and p.tone in ("warn", "alarm", "up", "down")]
    key += [p for p in points if not p.top and p.tone in ("warn", "alarm")]
    if key:
        rows_panel(c, "WHAT MATTERS NOW", key[:4], font=F(26), name_font=F(27, True), max_lines=2)
    inspector_box(c, note)
    footer(c, footer_text)
    return c.crop(c.y)


def full_report(asset, name, mk, points, fam, ver, note, now, footer_text, track):
    pages = []
    c = Canvas()
    header(c, asset, name, mk, now, "FULL REPORT", compact=True)
    verdict_box(c, ver)
    family_grid(c, fam)
    inspector_box(c, note, full=True)
    top = [p for p in points if p.top]
    rows_panel(c, f"TOP {len(top)} - MOST IMPORTANT", top, font=F(26), name_font=F(28, True), max_lines=3, track=track)
    footer(c, "Page 1  -  " + footer_text)
    pages.append(c.crop(c.y))
    rest = [p for p in points if not p.top]
    chunk = 15
    for i in range(0, len(rest), chunk):
        c = Canvas()
        c.y = 0
        y0 = PAD
        c.panel(y0, 96)
        c.text(PAD + 32, y0 + 48, f"{name}  -  MORE POINTS ({i + 1 + len(top)}-{min(len(rest), i + chunk) + len(top)})", F(30, True), GOLD, anchor="lm")
        c.text(W - PAD - 32, y0 + 48, now.astimezone(IST).strftime("%d %b %I:%M %p").replace(" 0", " "), F(24), SOFT, anchor="rm")
        c.y = y0 + 96
        groups = {}
        for p in rest[i:i + chunk]:
            groups.setdefault(p.family, []).append(p)
        for fam_name, ps in groups.items():
            rows_panel(c, fam_name.upper(), ps, font=F(25), name_font=F(26, True), max_lines=3, track=track)
        footer(c, f"Page {len(pages) + 1}  -  green = up, red = down, grey = no side, amber = careful, dark = no data")
        pages.append(c.crop(c.y))
    return pages


def alert_card(title, lines, col=RED, now=None):
    c = Canvas(1400)
    y0 = PAD
    inner = W - 2 * PAD - 64
    body = sum(len(c.wrap(l, F(32), inner)) * 44 + 16 for l in lines)
    h = 150 + body + 20
    c.d.rounded_rectangle((PAD, y0, W - PAD, y0 + h), radius=28, fill=PANEL, outline=col, width=4)
    c.text(PAD + 32, y0 + 28, "TREND TRISHUL  -  INSTANT ALERT", F(26, True), GOLD)
    c.text(PAD + 32, y0 + 70, title, F(46, True), col)
    y = y0 + 150
    for l in lines:
        y += c.para(PAD + 32, y, l, F(32), inner, WHITE, gap=12) + 16
    c.y = y0 + h
    if now:
        footer(c, now.astimezone(IST).strftime("%d %b %I:%M %p IST").replace(" 0", " ") + "  -  Not financial advice")
    return c.crop(c.y)


def to_pdf(pages, path):
    """All report pages in ONE PDF file (easy to download and share)."""
    pages = [p.convert("RGB") for p in pages]
    pages[0].save(path, "PDF", save_all=True, append_images=pages[1:], resolution=130)
    return path
