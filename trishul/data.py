"""All data fetching. Every fetch is wrapped so one broken source never stops the report.
A failed source returns None and the point shows "no data" (grey)."""
import io, json, os, re, time, math, logging
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
import requests

from . import config

log = logging.getLogger("trishul.data")
UTC = timezone.utc
S = requests.Session()
S.headers.update({"User-Agent": config.USER_AGENT})
FAILED = []          # names of sources that failed this run (shown to the AI Inspector)


# ---------------------------------------------------------------- cache
def _cache_path(key):
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    return os.path.join(config.CACHE_DIR, re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json")


def cached(key, ttl_min, fn):
    """Return a JSON-able result from cache if younger than ttl_min, else call fn().
    If fn fails, an older cached value (up to 7 days) is used and marked stale."""
    p = _cache_path(key)
    old = None
    if os.path.exists(p):
        try:
            with open(p) as f:
                old = json.load(f)
            if time.time() - old["t"] < ttl_min * 60:
                return old["v"]
        except Exception:
            old = None
    try:
        v = fn()
    except Exception as e:  # noqa
        log.warning("source %s failed: %s", key, e)
        v = None
    if v is not None:
        with open(p, "w") as f:
            json.dump({"t": time.time(), "v": v}, f)
        return v
    FAILED.append(key)
    if old and time.time() - old["t"] < 7 * 86400:
        return old["v"]
    return None


def get_json(url, **kw):
    r = S.get(url, timeout=config.HTTP_TIMEOUT, **kw)
    r.raise_for_status()
    return r.json()


def safe(name, fn, default=None):
    try:
        return fn()
    except Exception as e:  # noqa
        log.warning("source %s failed: %s", name, e)
        FAILED.append(name)
        return default


def _df_to_json(df):
    d = df.copy()
    d.index = [int(t.timestamp()) for t in d.index]
    return {"i": d.index.tolist(), "c": list(d.columns), "v": d.values.tolist()}


def _json_to_df(j):
    if not j:
        return None
    df = pd.DataFrame(j["v"], columns=j["c"], index=pd.to_datetime(j["i"], unit="s", utc=True))
    return df


# ---------------------------------------------------------------- prices
def _norm(df):
    df = df.rename(columns=str.lower)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].dropna(subset=["close"])
    if df.index.tz is None:
        df.index = df.index.tz_localize(UTC)
    else:
        df.index = df.index.tz_convert(UTC)
    if "volume" not in df.columns:
        df["volume"] = np.nan
    return df.sort_index()


def yf_hist(ticker, interval, period):
    import yfinance as yf
    last = None
    for attempt in range(3):
        try:
            df = yf.download(ticker, interval=interval, period=period, progress=False, auto_adjust=False, threads=False)
            if df is not None and len(df):
                return _norm(df)
        except Exception as e:  # noqa
            last = e
        time.sleep(2 + attempt * 3)
    raise RuntimeError(f"yahoo {ticker} {interval}: {last}")


def yf_close(ticker, period="2y", interval="1d"):
    """Daily closes as a pandas Series, cached 3 hours."""
    j = cached(f"yfc_{ticker}_{interval}_{period}", 180, lambda: _df_to_json(yf_hist(ticker, interval, period)[["close"]]))
    df = _json_to_df(j)
    return None if df is None else df["close"]


def coinbase(product, gran, bars):
    out = []
    end = datetime.now(UTC)
    while len(out) < bars:
        start = end - timedelta(seconds=gran * 300)
        u = (f"https://api.exchange.coinbase.com/products/{product}/candles?granularity={gran}"
             f"&start={start.isoformat()}&end={end.isoformat()}")
        rows = get_json(u)
        if not rows:
            break
        out += rows
        end = start
        time.sleep(0.25)
    df = pd.DataFrame(out, columns=["t", "low", "high", "open", "close", "volume"]).drop_duplicates("t")
    df.index = pd.to_datetime(df.t, unit="s", utc=True)
    return df[["open", "high", "low", "close", "volume"]].astype(float).sort_index().tail(bars)


def twelvedata(symbol, interval, size):
    u = (f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize={size}"
         f"&timezone=UTC&apikey={config.TWELVEDATA_API_KEY}")
    j = get_json(u)
    if j.get("status") != "ok":
        raise RuntimeError(j.get("message"))
    df = pd.DataFrame(j["values"])
    df.index = pd.to_datetime(df.datetime, utc=True)
    df = df[["open", "high", "low", "close"]].astype(float)
    df["volume"] = np.nan
    return df.sort_index()


def prices(asset):
    """Returns dict with m15, h1, d1 bars (UTC index) and a 'source' label."""
    if asset == "btc":
        try:
            return {"m15": coinbase("BTC-USD", 900, 2000), "h1": coinbase("BTC-USD", 3600, 1500),
                    "d1": coinbase("BTC-USD", 86400, 800), "source": "Coinbase BTC-USD"}
        except Exception as e:  # noqa
            log.warning("coinbase failed %s, using Yahoo", e)
            FAILED.append("coinbase")
            return {"m15": yf_hist("BTC-USD", "15m", "30d"), "h1": yf_hist("BTC-USD", "1h", "120d"),
                    "d1": yf_hist("BTC-USD", "1d", "3y"), "source": "Yahoo BTC-USD"}
    # gold
    fut = {"m15": yf_hist("GC=F", "15m", "30d"), "h1": yf_hist("GC=F", "1h", "120d"),
           "d1": yf_hist("GC=F", "1d", "3y"), "source": "COMEX gold futures (GC=F)"}
    if config.TWELVEDATA_API_KEY:
        try:
            spot = {"m15": twelvedata("XAU/USD", "15min", 2000), "h1": twelvedata("XAU/USD", "1h", 2900),
                    "d1": twelvedata("XAU/USD", "1day", 800), "source": "XAU/USD spot (Twelve Data)"}
            # spot has no volume: borrow futures volume (same hours) for volume-based points
            for k in ("m15", "h1"):
                spot[k]["volume"] = fut[k]["volume"].reindex(spot[k].index)
            spot["fut_h1"] = fut["h1"]
            return spot
        except Exception as e:  # noqa
            log.warning("twelvedata failed %s", e)
            FAILED.append("twelvedata")
    return fut


# ---------------------------------------------------------------- macro / outside
def fred(series_id):
    def f():
        r = S.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ["date", "v"]
        df = df[df.v.astype(str) != "."]
        df["v"] = df.v.astype(float)
        df = df.tail(800)
        return {"d": df.date.tolist(), "v": df.v.tolist()}
    j = cached(f"fred_{series_id}", 360, f)
    if not j:
        return None
    return pd.Series(j["v"], index=pd.to_datetime(j["d"]))


def cot(code, dataset):
    """CFTC Commitments of Traders, weekly. dataset: '72hh-3qpy' (disaggregated) or 'gpe5-46if' (financial)."""
    def f():
        u = (f"https://publicreporting.cftc.gov/resource/{dataset}.json?cftc_contract_market_code={code}"
             f"&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=160")
        return get_json(u)
    return cached(f"cot_{code}", 720, f)


def news_calendar():
    def f():
        rows = get_json("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
        keep = [r for r in rows if r.get("country") == "USD" and r.get("impact") == "High"]
        return keep
    return cached("ff_calendar", 240, f)


# ---------------------------------------------------------------- crypto extras
def hyperliquid_btc():
    def f():
        r = S.post("https://api.hyperliquid.xyz/info", json={"type": "metaAndAssetCtxs"}, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        meta, ctxs = r.json()
        for a, c in zip(meta["universe"], ctxs):
            if a["name"] == "BTC":
                return {"funding_1h": float(c["funding"]), "oi": float(c["openInterest"]),
                        "mark": float(c["markPx"]), "oracle": float(c["oraclePx"])}
        return None
    return cached("hyperliquid_btc", 10, f)


def binance_btc_price():
    def f():
        for u in ("https://data-api.binance.vision/api/v3/ticker/price?symbol=BTCUSDT",
                  "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"):
            try:
                return float(get_json(u)["price"])
            except Exception:
                continue
        return None
    return cached("binance_btc_px", 10, f)


def fear_greed():
    return cached("fng", 180, lambda: [int(x["value"]) for x in get_json("https://api.alternative.me/fng/?limit=8")["data"]])


def stablecoins():
    def f():
        rows = get_json("https://stablecoins.llama.fi/stablecoincharts/all")[-60:]
        return [[int(r["date"]), float(r["totalCirculatingUSD"]["peggedUSD"])] for r in rows]
    return cached("stablecoins", 360, f)


def btc_dominance():
    return cached("btc_dom", 120, lambda: float(get_json("https://api.coingecko.com/api/v3/global")["data"]["market_cap_percentage"]["btc"]))


def coinmetrics(metric, days=60):
    def f():
        u = (f"https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics={metric}"
             f"&frequency=1d&page_size={days}&paging_from=end")
        rows = get_json(u)["data"]
        return [[r["time"][:10], float(r[metric])] for r in rows if r.get(metric) not in (None, "")]
    return cached(f"cm_{metric}", 360, f)


def hashrate():
    def f():
        j = get_json("https://api.blockchain.info/charts/hash-rate?timespan=200days&format=json&sampled=false")
        return [[int(v["x"]), float(v["y"])] for v in j["values"]]
    return cached("hashrate", 720, f)


def btc_etf_flows():
    """Daily net flow (US$ millions) of US spot Bitcoin ETFs from farside.co.uk. None if blocked."""
    def f():
        r = S.get("https://farside.co.uk/bitcoin-etf-flow-all-data/", timeout=config.HTTP_TIMEOUT,
                  headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        out = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, flags=re.S):
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S)]
            if len(cells) > 3 and re.match(r"\d{1,2} \w{3} \d{4}", cells[0]):
                tot = cells[-1].replace(",", "").replace("(", "-").replace(")", "")
                try:
                    out.append([cells[0], float(tot)])
                except ValueError:
                    pass
        return out[-30:] if out else None
    return cached("btc_etf_flows", 240, f)


def gld_holdings():
    """Ounces held by the GLD gold fund (SPDR archive CSV). None if blocked."""
    def f():
        r = S.get("https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv",
                  timeout=config.HTTP_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), skipinitialspace=True)
        col = [c for c in df.columns if "Ounces" in c][0]
        df = df[[df.columns[0], col]].dropna().tail(40)
        vals = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce").dropna()
        return vals.tolist()
    return cached("gld_holdings", 360, f)


# ---------------------------------------------------------------- options
def deribit(path, **params):
    j = get_json("https://www.deribit.com/api/v2/public/" + path, params=params)
    return j["result"]


def deribit_options():
    return cached("deribit_book", 30, lambda: [
        {k: r.get(k) for k in ("instrument_name", "open_interest", "mark_iv", "underlying_price", "volume")}
        for r in deribit("get_book_summary_by_currency", currency="BTC", kind="option")])


def deribit_dvol():
    def f():
        end = int(time.time() * 1000)
        res = deribit("get_volatility_index_data", currency="BTC", start_timestamp=end - 400 * 86400000,
                      end_timestamp=end, resolution="1D")
        return [[r[0], r[4]] for r in res["data"]]
    return cached("deribit_dvol", 60, f)


def deribit_big_trades():
    def f():
        res = deribit("get_last_trades_by_currency", currency="BTC", kind="option", count=1000)
        cut = (time.time() - 86400) * 1000
        return [{k: t.get(k) for k in ("instrument_name", "amount", "direction", "price", "index_price", "timestamp")}
                for t in res["trades"] if t["timestamp"] >= cut and float(t["amount"]) >= 25]
    return cached("deribit_big", 30, f)


def gld_options():
    """GLD option chain from Yahoo (gold options proxy). List of rows."""
    def f():
        import yfinance as yf
        tk = yf.Ticker("GLD")
        rows = []
        today = datetime.now(UTC).date()
        for exp in tk.options[:8]:
            d = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
            if d < 0 or d > 70:
                continue
            ch = tk.option_chain(exp)
            for kind, tab in (("C", ch.calls), ("P", ch.puts)):
                for _, r in tab.iterrows():
                    rows.append({"exp": exp, "k": float(r.strike), "t": kind,
                                 "oi": float(np.nan_to_num(r.openInterest)), "vol": float(np.nan_to_num(r.volume)),
                                 "iv": float(np.nan_to_num(r.impliedVolatility))})
            time.sleep(0.5)
        return rows
    return cached("gld_options", 60, f)
