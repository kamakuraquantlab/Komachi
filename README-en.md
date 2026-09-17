# Komachi

*[日本語版はこちら](README.md) — the Japanese README is the primary one.*

The **Kamakura Quant Lab** command line client. Fetches historical market data and lays it out so DuckDB can query it immediately.

```bash
pip install 'kamakuraquantlab-komachi[duckdb]'
komachi token set --token hk_...
komachi download --market GMO:BTC_JPY --start 2026-01-01
komachi duckdb
duckdb ~/kql-data/kql.duckdb
```

```sql
SELECT exchange, symbol, count(*) FROM trade GROUP BY 1, 2;
```

## Two ways to get the data

What the data is, what is published and how good each day is:
[kamakuraquantlab.jp/data](https://kamakuraquantlab.jp/data/).

**A browser** — [tsurugaoka](https://kamakuraquantlab.jp/tsurugaoka/)

Fine for looking at a few days. One file at a time, wherever your browser puts
things.

**The command line** — Komachi, this repository

A client for the Yukinoshita API (`yukinoshita.kamakuraquantlab.jp`). What it
adds over the browser:

| | |
|---|---|
| Balance and coverage | Which markets you can reach, and each day's size and quality, before you spend on it |
| Bulk fetching | A whole range in one command. Re-run to resume; every file is checked against its checksum |
| The warehouse layout | Hive-partitioned, so DuckDB reads a market-year with no import step |
| Free sources | Binance Vision and GMO's own archives, re-cut onto JST days so they line up with what you were sent |
| Local inspection | What is on disk, trades and quotes, DuckDB views |

Yukinoshita decides what you are entitled to and signs a URL against object
storage. Files come from storage directly, so no file byte passes through the
API.

## 1  Quick start

Spending a 28 market-day allowance, end to end. Every output below is what the
command actually prints.

### 1.1  Store the token

Issue one at
[kamakuraquantlab.jp/tsurugaoka/](https://kamakuraquantlab.jp/tsurugaoka/):
sign in with the order number and email you already have, and press *Show my
token*. It is shown once, and you can issue another whenever you need one —
doing so stops the previous one working.

```bash
pip install 'kamakuraquantlab-komachi[duckdb]'
komachi token set --token hk_...
```

First run asks where data should go and records the answer in `.env` in the
current directory. The token is kept separately, at `~/.komachi/config.json`,
mode 0600.

### 1.2  Check the balance and the deadlines

```bash
komachi token status
```

```text
Product        starter-4w
Token status   active
Access         active
First used     2026-09-11T05:54:23+00:00
Access until   2026-09-25T05:54:23+00:00
Allowance      28 market-days  (4 market-weeks)
Remaining      28 market-days  (4 market-weeks)
Markets        BITBANK:BTC_SPOT, ... COINCHECK:XRP_SPOT

Active until 2026-09-25. Until then you can unlock market-days and re-download
anything already unlocked as often as you like, at no further cost.
```

There are two deadlines, and they apply one after the other.

| | Length | Starts | Once it passes |
|---|---|---|---|
| First sign-in | 1 month | When the token was issued | The access window never starts |
| Access | 14 days | **The first time you use it** | Nothing further is unlocked or served |

You have to **sign in once** before the first deadline. That first sign-in is
what issues your token and starts the access window. Signing in after the
deadline does not start one.

**Access** is counted from that first use rather than from the order, so being
slow to start does not cost you days you paid for.

Inside the access window you can fetch anything you have unlocked as often as
you like. Deleting a file, or a download that fails, costs nothing to recover,
and there is no cap on how many times a file may be re-signed; each request
mints a fresh link that lives an hour. `komachi download` unlocks any day in
range that you do not already own as it fetches it, so there is no separate
unlock step.

After it, no new market-days are unlocked and no new download links are issued,
even if you have balance left. `komachi download` says so and stops before
fetching anything, and you can still sign in to the website to see your usage
and the date it ended. Market-days already spent stay spent and nothing is
refunded, so take what you unlock while the window is open.

In practice you will already be inside the access window by the time you get
here, because any successful call starts it — including the one `komachi token
set` makes to check your token. So `komachi token status` shows the date and
how many days are left on it.

Both the date and the count come from the service. This tool prints what the
API returns and works out no deadline of its own: the subtraction needs a
clock, and yours is not the one the deadline is kept on. It is also why an old
copy of this tool can still tell you the truth about today's policy.

### 1.3  See what is published

Costs nothing.

```bash
komachi markets
komachi catalog --market COINCHECK:BTC_SPOT --days 3
```

```text
date         datasets                     rows      size    gap  note
2026-09-01   OrderBook,Trade           264,447    24.8MB     8m
2026-09-02   OrderBook,Trade           274,792    26.7MB     1m
2026-09-03   OrderBook,Trade           280,067    27.9MB     9m
```

`gap` is minutes with no record in the JST day, so you can judge a day before
spending on it.

### 1.4  Download

```bash
komachi download --market COINCHECK:BTC_SPOT --start 2025-07-01 --days 28
```

It shows the range, file count, size and cost before fetching anything.
Re-running after an interruption skips what is already on disk and never spends
a market-day twice.

### 1.5  Add the free sources

The same period from Binance and GMO, from their own archives. Costs nothing.

```bash
komachi binance-import --symbol BTC_USDT --start 2025-07-01 --end 2025-07-28
komachi gmo-import     --symbol BTC_JPY  --start 2025-07-01 --end 2025-07-28
```

Both are re-cut onto JST days on the way in, so they line up with what you
bought.

### 1.6  See what landed

```bash
komachi local
```

```text
market                   dataset     days  range
COINCHECK:BTC_SPOT       OrderBook     28  2025-07-01 .. 2025-07-28
COINCHECK:BTC_SPOT       Trade         28  2025-07-01 .. 2025-07-28
BINANCE:BTC_USDT         Trade         28  2025-07-01 .. 2025-07-28
GMO:BTC_JPY              Trade         28  2025-07-01 .. 2025-07-28
```

### 1.7  Look at it

```bash
komachi trades --market COINCHECK:BTC_SPOT --date 2025-07-01 --rows 3
komachi book   --market COINCHECK:BTC_SPOT --date 2025-07-01 --rows 3
```

```text
time (JST)    side             price            size
00:00:00.000  buy    15,456,978.0000      0.03000000

time (JST)            best bid        best ask      spread
00:00:00.000   15,456,905.0000 15,456,978.0000     73.0000
```

### 1.8  Query it

```bash
komachi duckdb
duckdb ~/kql-data/kql.duckdb
```

```sql
SELECT date, count(*) AS trades, avg(price) AS vwap
FROM trade
WHERE exchange = 'COINCHECK' AND symbol = 'BTC_SPOT'
GROUP BY date ORDER BY date;
```

Plots and derived datasets are not Komachi's job. Hase is the analysis toolkit,
publishing later.

## 2  Where files go

`$ROOT_PATH`, else `$KQL_ROOT_PATH`, else `~/kql-data`. Inside it, the same
Hive-partitioned tree the data was produced in:

```
$ROOT_PATH/bronze/dataset=Trade/exchange=GMO/symbol=BTC_JPY/date=2026-01-15/data.parquet
```

The layout is matched rather than invented, for two reasons. DuckDB, PyArrow,
Spark and Athena all recover `dataset`, `exchange`, `symbol` and `date` as real
columns from the path, so a whole market-year is one `read_parquet` with a glob
and no manifest to track. And example notebooks written against the warehouse
run unchanged against your copy.

The `bronze/` layer is kept even though you only receive bronze, so derived
silver and gold datasets you compute locally do not collide with delivered
files.

## 3  Commands

### 3.1  Remote

Anything that talks to the API or to a free source.

| Command | Does | Spends |
|---|---|---|
| `komachi token set --token TOKEN` | Verify and store a token | no |
| `komachi token status` | Granted, used, balance, expiry | no |
| `komachi markets` | Markets the token covers, and referred sources | no |
| `komachi calendar --market MARKET` | Published dates, and which you own | no |
| `komachi catalog --market MARKET` | Per-day coverage and quality | no |
| `komachi download --market MARKET --start DATE [--days N]` | Fetch a range, resumable | **yes** |
| `komachi binance-import --symbol SYMBOL --start DATE --end DATE` | Import from Binance Vision | no |
| `komachi gmo-import --symbol SYMBOL --start DATE --end DATE` | Import from GMO's archive | no |

Only `download` spends anything, and it prices the range and asks before it does. A market-day is one market on
one date, and the order book and trades for that date are one, not two.

### 3.2  Local

Reads what is already on disk. No network, no cost.

| Command | Does |
|---|---|
| `komachi local` | What is on disk |
| `komachi trades --market MARKET --date DATE` | Print trades for a market-day |
| `komachi book --market MARKET --date DATE` | Print best bid, ask and spread |
| `komachi stats --path PATH` | Rows and time range for one file |
| `komachi decode --path PATH` | Schema and first rows |
| `komachi duckdb` | Create or refresh the DuckDB views |
| `komachi sql` | Print the view SQL |

## 4  Binance and GMO

Kamakura Quant Lab does not sell Binance data, because Binance publishes the
same history free through Binance Vision. `komachi binance-import` downloads it
from Binance directly, on your machine, and converts it into the same schema
and layout as the delivered data. One DuckDB view then spans both, which is
what makes cross-exchange work possible without any ETL.

`komachi gmo-import` does the same for GMO's own trade archive.

Neither publishes L2 order book depth, so both importers produce `Trade` only.
Depth for the JP venues is the part that is not available anywhere else.

Both archives are cut on their own day boundary — Binance at 00:00 UTC, GMO at
its 06:00 JST trading-day rollover — and both are re-cut onto JST days on the
way in. Without that a cross-market join would compare windows nine hours
apart, silently.

## 5  What a download costs

Access is counted in **market-days**: one market on one date, covering every
data type published for it. Trade and OrderBook for one market/date are one
market-day, not two.

`download` needs a market and a start date. By default it takes as many days
as your remaining allowance covers; `--days N` asks for fewer. Before anything
is fetched it shows what the run will do:

```
Market      COINCHECK:BTC_SPOT
Dates       2025-07-01 .. 2025-07-07   (7 days, JST)
Files       14 to download, 207.7MB
Cost        7 of 21 remaining market-day(s)
```

Everything in that summary comes from the catalogue, so it is known without
issuing a URL or spending anything.

Komachi does not second-guess your entitlement. Whether the allowance covers a
request is the service's decision, made per file; a client-side opinion could
only be a duplicate that is sometimes wrong. What Komachi does guarantee is
that it never spends more than it needs to.

## 6  Interrupted downloads resume

Re-run the same command. Files already complete are recognised from their size
and checksum and dropped from the plan before any URL is requested, so a resumed
run costs no allowance at all. That check is the one thing this side has to get
right.

URLs are issued one at a time, immediately before the file they unlock. A
pre-signed URL lives an hour, which is ample for one file and not for a
hundred days of them.

## 7  What Komachi does not do

1. Reach an exchange API. It talks to the Yukinoshita API, Binance Vision and
   GMO's published archive, and to object storage for the bytes.
2. Derive anything. Silver and gold belong to Hase, the analysis toolkit.
3. Hold a credential for anything but the Kamakura Quant Lab API.

## 8  Tests

```bash
python -m pytest tests -q
```

No network and no credentials: HTTP is mocked and DuckDB runs on temporary
files.

## 9  Licence

Apache License 2.0. See [LICENSE.md](LICENSE.md), which also says why Apache
rather than MIT.
