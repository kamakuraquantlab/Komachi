# Komachi

The **Kamakura Quant Lab** command line client. Downloads purchased historical
market data and lays it out so DuckDB can query it immediately.

```bash
pip install 'komachi[duckdb]'
komachi auth login --token hk_...
komachi download --market GMO:BTC_JPY --start 2026-01-01 --end 2026-01-28
komachi duckdb
duckdb ~/kql-data/kql.duckdb
```

```sql
SELECT exchange, symbol, count(*) FROM trade GROUP BY 1, 2;
```

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

| Command | Purpose |
|---|---|
| `komachi auth login --token TOKEN` | Verify a token and store it |
| `komachi status` | Grant, market-days used and remaining, expiry |
| `komachi markets` | Markets your token covers, plus referred sources |
| `komachi calendar --market MARKET` | Available and already-downloaded dates |
| `komachi manifest --market ... --start ... --end ...` | Temporary URLs; `--dry-run` to price it first |
| `komachi download --market ... --start ... --end ...` | Download a range, resumable and verified |
| `komachi refresh --file FILE_ID` | Re-sign one expired or failed file |
| `komachi binance-import --symbol ... --start ... --end ...` | Import Binance history from Binance Vision |
| `komachi local` | What is on disk already |
| `komachi duckdb` | Create or refresh a DuckDB database of views |
| `komachi sql` | Print the view SQL for your own session |
| `komachi stats --path PATH` | Rows and time range for one file |
| `komachi decode --path PATH` | Schema and first rows |

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
market-day, not two. `--dry-run` reports the cost without spending it, and
`download` asks before consuming anything.

## Tests

```bash
python -m pytest tests -q
```

No network and no credentials: HTTP is mocked and DuckDB runs on temporary
files.
