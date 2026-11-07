"""Trend Trishul settings. Everything is set already - you do not need to change anything here."""
import os

IST_OFFSET_MIN = 330                 # India time = UTC + 5:30
FULL_REPORT_HOURS_IST = (8, 20)      # 8 AM and 8 PM India time: full report with all points
SHORT_EVERY_HOURS = 2                # short card every 2 hours (even hours, India time)
NEWS_WARN_MIN = 30                   # instant alert this many minutes before big US news

ASSETS = {
    "gold": {
        "name": "GOLD",
        "round_small": 50.0,         # round numbers for gold
        "round_big": 100.0,
        "tol_pct": 0.08,             # levels within 0.08% count as one zone
        "proj_mult": 1.3,            # projection lines = yesterday's close +/- 1.3 x daily ATR
    },
    "btc": {
        "name": "BITCOIN",
        "round_small": 1000.0,
        "round_big": 5000.0,
        "tol_pct": 0.15,
        "proj_mult": 1.3,
    },
}

# Secrets (set in GitHub -> Settings -> Secrets). Never write them in code.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELS = [m for m in os.environ.get("GEMINI_MODEL", "gemini-2.5-flash,gemini-2.0-flash").split(",") if m]
TWELVEDATA_API_KEY = os.environ.get("TWELVEDATA_API_KEY", "")   # optional: real XAUUSD spot price

STATE_DIR = os.environ.get("TRISHUL_STATE_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "state"))
CACHE_DIR = os.path.join(STATE_DIR, "cache")
HTTP_TIMEOUT = 20
USER_AGENT = "TrendTrishul/1.0 (personal market report bot)"
