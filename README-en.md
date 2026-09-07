# Komachi

*[日本語版はこちら](README.md) — the Japanese README is the primary one.*

The **Kamakura Quant Lab** command line client. Fetches historical market data and lays it out so DuckDB can query it immediately.

```bash
pip install 'komachi[duckdb]'
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

```bash
pip install 'komachi[duckdb]'
komachi token set --token hk_...
```

First run asks where data should go and records the answer in `.env` in the
current directory. The token is kept separately, at `~/.komachi/config.json`,
mode 0600.

### 1.2  Check the balance and the expiry

```bash
komachi token status
```

```text
Product        starter-4w
Valid until    2026-10-05T14:54:23+00:00
Allowance      28 market-days  (4 market-weeks)
Remaining      28 market-days  (4 market-weeks)
Markets        BITBANK:BTC_SPOT, ... COINCHECK:XRP_SPOT
```

There are two expiries and they mean different things.

| | Length | Starts |
|---|---|---|
| The token | Shown as `Valid until` | When the token was issued |
| A market-day you unlocked | 7 days | When you unlocked it |

The **token expiry** is the deadline for spending the balance. Anything unspent
when it passes is gone.

The **download window** is counted per market-day. Once you have unlocked one
you can fetch it as often as you like for seven days at no further cost, so
deleting a file inside the window costs nothing to recover. After seven days
the files stop being served, and fetching that date again costs another
market-day.

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
