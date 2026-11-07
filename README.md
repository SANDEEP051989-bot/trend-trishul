# Trend Trishul - Gold & Bitcoin Radar

Sends picture cards to your Telegram:

| What | When (India time) |
|---|---|
| Short card (verdict, today's map, big money, family votes, AI Inspector) | every 2 hours: 10 AM, 12, 2, 4, 6 PM, 10 PM, 12, 2, 4, 6 AM |
| Full report (all points, top 15 first) | 8 AM and 8 PM |
| Instant alert | any time: Big Move Alarm turns ON, a projection line breaks fast, big US news in 30 minutes |

Gold cards stop when the gold market is closed (weekend). Bitcoin runs every day.
It checks every 15 minutes, but only sends a message on the times above or for a real alert.

---

## Setup - 6 small steps

### Step 1 - Make a new Telegram bot
1. In Telegram, open **@BotFather**.
2. Send `/newbot`. Name: `Trend Trishul`. Username: anything ending in `bot` (for example `trend_trishul_ankit_bot`).
3. BotFather gives you a **token** (looks like `123456:ABC-xyz`). Copy it.
4. Open your new bot and press **Start** (send it "hi").

**Chat ID:** use the same chat ID you used for your 12-agent bot. It is your own Telegram ID, so it works for any bot.

### Step 2 - Gemini key
Use the same Gemini key as your 12-agent system. If you need a new one, get it from aistudio.google.com, then "Get API key".

### Step 3 - Make a new PUBLIC GitHub repository
1. On GitHub, click **+** (top right), then **New repository**.
2. Name: `trend-trishul`. Choose **Public**. Click **Create repository**.
3. Click **uploading an existing file**.
4. Unzip `trend-trishul.zip` on your computer. Drag everything inside the folder onto the page, then click **Commit changes**.

> If the `.github` folder did not upload (it can be hidden on some computers), do this instead:
> **Add file**, then **Create new file**. As the name, type `.github/workflows/trishul.yml`.
> Paste in the text of that file from the zip, then click **Commit changes**.

### Step 4 - Add the 3 secrets
In the repository, go to **Settings**, then **Secrets and variables**, then **Actions**, then **New repository secret**. Add each one:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from Step 1 |
| `TELEGRAM_CHAT_ID` | your chat ID |
| `GEMINI_API_KEY` | your Gemini key |

Optional: `TWELVEDATA_API_KEY` (free at twelvedata.com). With it, gold uses the real XAUUSD spot price. Without it, gold uses COMEX gold futures, which are usually $10-40 above spot.

### Step 5 - Allow it to save its track record
Go to **Settings**, then **Actions**, then **General**. Under **Workflow permissions**, choose **Read and write permissions**, then click **Save**.

### Step 6 - Test it
Go to the **Actions** tab, then **Trend Trishul**, then **Run workflow** (keep mode = `test`), then **Run workflow**.
In 2-4 minutes you get a short card and a full report for Gold and Bitcoin.
After that it runs by itself. There is nothing else to do.

---

## How it decides
- Points are grouped into 7 families: Range, Timing, Levels, Trend, Options, Big Money, Outside.
- Each family votes Up, Down or Neutral ("Careful" = warnings only).
- The verdict comes from the families, and each family counts equally. So 10 similar points cannot drown out the rest.
- Context points (range used, projection lines, busy hours, news) do not push the verdict up or down. They only change the advice line (for example, "don't chase").
- The AI Inspector (Gemini) writes the plain-English note. It points out conflicts and missing data.
- **Track record:** every point's vote is checked 24 hours later. Once a point has 10 or more votes, the full report shows "right 58% of 40" next to it. After a few weeks, remove the points that keep being wrong.

## Where the data comes from (all free)
| Data | Source |
|---|---|
| Gold price | Yahoo COMEX futures (or Twelve Data spot) |
| Bitcoin price | Coinbase |
| Options | Bitcoin: Deribit (live). Gold: GLD fund options on Yahoo, scaled to the gold price |
| Big players report | CFTC (weekly, Friday) |
| Rates, inflation, money supply | FRED |
| News times | ForexFactory calendar |
| Bitcoin crowd | Hyperliquid funding and open bets |
| Bitcoin ETF flows | farside.co.uk |
| Gold fund holdings | SPDR GLD |
| Other | alternative.me fear & greed, DefiLlama stablecoins, CoinGecko share, CoinMetrics, blockchain.com hash rate |

If a source is down, that point turns dark ("no data") and the AI Inspector says so. The rest of the report still comes.

**Two points are updated by hand (optional):** Central Bank Buying and China Demand have no free daily data. Edit `manual_inputs.json` once a month: `vote` 1 = helps gold, 0 = neutral, -1 = hurts gold, plus a short text and the date.

## Honest notes
- This is an advisor, not a buy/sell machine. In the backtest, the projection lines alone lost money as reversal signals. Here they are used only as "don't chase" and "big day" warnings.
- GitHub sometimes runs a few minutes late, so a card can arrive at 10:07 instead of 10:00.
- Not financial advice.
