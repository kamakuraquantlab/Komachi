# Komachi

*[日本語版はこちら](README.md) — the Japanese README is the primary one.*

The **Kamakura Quant Lab** command line client. Downloads purchased historical
market data and lays it out so DuckDB can query it immediately.

```bash
pip install 'komachi[duckdb]'
komachi auth login --token hk_...
komachi download --market GMO:BTC_JPY --start 2026-01-01
komachi duckdb
duckdb ~/kql-data/kql.duckdb
```

```sql
SELECT exchange, symbol, count(*) FROM trade GROUP BY 1, 2;
```

## What it connects to

Komachi does nothing on its own. It talks to two things:

| | |
|---|---|
| [kamakuraquantlab.jp](https://kamakuraquantlab.jp) | What the data is, what is published, and browser downloads |
| `yukinoshita.kamakuraquantlab.jp` | The API: allowance, unlocking market-days, signing URLs |

Yukinoshita decides what you are entitled to and signs a URL against object
storage. Files come from storage directly, so no file byte passes through the
API.

[kamakuraquantlab.jp/tsurugaoka/](https://kamakuraquantlab.jp/tsurugaoka/) does
the same job in a browser, which is fine for a few files. Komachi is for the
rest: it resumes, verifies checksums, and writes the layout analysis wants.

## Quick start

### Which to use

| Days bought | Use |
|---|---|
| 1 to 7 market-days | The [browser](https://kamakuraquantlab.jp/tsurugaoka/) is enough |
| More | Komachi |

A browser saves one file at a time wherever it saves things. Komachi fetches a
range in one command and writes a Hive-partitioned tree, so DuckDB reads it
with no import step.

### Spending a 28 market-day allowance

**1. Sign in**

```bash
pip install 'komachi[duckdb]'
komachi auth login --token hk_...
```

First run asks where data should go and records the answer in `.env` in the
current directory. The token is kept separately, at `~/.komachi/config.json`,
mode 0600.

**2. See what you have**

```bash
komachi status
```

```text
Product        starter-4w
Allowance      28 market-days  (4 market-weeks)
Remaining      28 market-days  (4 market-weeks)
Markets        BITBANK:BTC_SPOT, ... COINCHECK:XRP_SPOT
```

**3. See what is published**

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

**4. Download**

```bash
komachi download --market COINCHECK:BTC_SPOT --start 2025-07-01 --days 28
```

It shows the range, file count, size and cost before fetching anything.
Re-running after an interruption skips what is already on disk and never spends
a market-day twice.

**5. Add the free sources**

The same period from Binance and GMO, from their own archives. Costs nothing.

```bash
komachi binance-import --symbol BTC_USDT --start 2025-07-01 --end 2025-07-28
komachi gmo-import     --symbol BTC_JPY  --start 2025-07-01 --end 2025-07-28
```

Both are re-cut onto JST days on the way in, so they line up with what you
bought.

**6. See what landed**

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

**7. Look at it**

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

**8. Query it**

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

## Where files go

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

## Commands

### Remote

Anything that talks to the API or to a free source.

| Command | Does | Spends |
|---|---|---|
| `komachi auth login --token TOKEN` | Verify and store a token | no |
| `komachi status` | Allowance, used, remaining, expiry | no |
| `komachi markets` | Markets the token covers, and referred sources | no |
| `komachi calendar --market MARKET` | Published dates, and which you own | no |
| `komachi catalog --market MARKET` | Per-day coverage and quality | no |
| `komachi download --market MARKET --start DATE [--days N]` | Fetch a range, resumable | **yes** |
| `komachi manifest --market MARKET --start DATE [--dry-run]` | Sign URLs, or price the request | yes, unless `--dry-run` |
| `komachi binance-import --symbol SYMBOL --start DATE --end DATE` | Import from Binance Vision | no |
| `komachi gmo-import --symbol SYMBOL --start DATE --end DATE` | Import from GMO's archive | no |

Only `download` and `manifest` spend anything. A market-day is one market on
one date, and the order book and trades for that date are one, not two.

### Local

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

## Binance

Kamakura Quant Lab does not sell Binance data, because Binance publishes the
same history free through Binance Vision. `komachi binance-import` downloads it
from Binance directly, on your machine, and converts it into the same schema
and layout as your purchased data. One DuckDB view then spans both, which is
what makes cross-exchange work possible without any ETL.

Binance Vision publishes spot trades but not L2 order book depth, so the
importer produces `Trade` only. Order book depth for the JP venues is the part
that is not available anywhere else.

## What a download costs

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

## Interrupted downloads resume

Re-run the same command. Files already complete are recognised from their size
and checksum and dropped from the plan before any URL is requested, so they
cost neither allowance nor part of the five-refresh budget. That check is the
one thing this side has to get right.

URLs are issued one at a time, immediately before the file they unlock. A
pre-signed URL lives an hour, which is ample for one file and not for a
hundred days of them.

## Tests

```bash
python -m pytest tests -q
```

No network and no credentials: HTTP is mocked and DuckDB runs on temporary
files.

## Licence

Apache License 2.0. See [LICENSE.md](LICENSE.md), which also says why Apache
rather than MIT.
