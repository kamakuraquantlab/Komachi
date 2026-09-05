"""Import Binance Vision archives into the Kamakura Quant Lab schema.

`doc/03` section 4.5: Kamakura Quant Lab sells no Binance data. Binance publishes the same
history free, so the buyer downloads it themselves and this module converts it
into the layout their Kamakura Quant Lab data already uses:

    <dest>/dataset=Trade/exchange=BINANCE/symbol=BTC_USDT/date=2026-01-15/data.parquet

Everything happens on the buyer's machine, against Binance's servers, at the
buyer's request. Nothing is proxied through or cached by Kamakura Quant Lab, which is the
boundary section 4.5.3 draws.

Scope note: Binance Vision's spot daily archives publish trades, aggTrades and
klines. They do not publish L2 order book depth for spot, so `OrderBook` cannot
be produced from this source. That asymmetry is worth stating plainly to buyers
rather than letting them discover it: Kamakura Quant Lab's JP order book depth has no free
Binance counterpart.
"""

import csv
import io
import zipfile
from pathlib import Path

import httpx

from .importer import DayResult, ImportError_, run_range
from .jst import date_range  # re-exported: the CLI and tests use it from here
from .layout import data_path

BASE_URL = "https://data.binance.vision/data/spot/daily/trades"
CHECKSUM_SUFFIX = ".CHECKSUM"

# Binance Vision trades CSV, positional (the archives carry no header row):
# trade_id, price, qty, quote_qty, time, is_buyer_maker, is_best_match
_COL_PRICE = 1
_COL_QTY = 2
_COL_TIME = 4
_COL_IS_BUYER_MAKER = 5

# Kamakura Quant Lab's Trade schema encodes the aggressor side as 0=BUY, 1=SELL.
SIDE_BUY = 0
SIDE_SELL = 1


def to_binance_symbol(symbol: str) -> str:
    """Kamakura Quant Lab's `BTC_USDT` is Binance Vision's `BTCUSDT`."""
    return symbol.replace("_", "").upper()


def archive_url(symbol: str, file_date: str) -> str:
    binance_symbol = to_binance_symbol(symbol)
    return f"{BASE_URL}/{binance_symbol}/{binance_symbol}-trades-{file_date}.zip"


def _normalise_timestamp(raw: str) -> float:
    """Binance switched trade timestamps from milliseconds to microseconds.

    Rather than pin a cutover date, infer from magnitude: a microsecond stamp
    for any plausible date has 16 digits, a millisecond stamp 13.
    """
    value = int(raw)
    if value > 1_000_000_000_000_000:
        return value / 1_000_000
    return value / 1_000


def parse_trades_csv(raw: bytes) -> list[dict]:
    """Convert Binance Vision trade rows into Kamakura Quant Lab Trade records."""
    rows: list[dict] = []
    reader = csv.reader(io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    for line in reader:
        if not line or len(line) <= _COL_IS_BUYER_MAKER:
            continue
        if not line[_COL_PRICE].replace(".", "", 1).isdigit():
            continue  # a header row, if a future archive gains one
        is_buyer_maker = line[_COL_IS_BUYER_MAKER].strip().lower() == "true"
        rows.append(
            {
                "ts": _normalise_timestamp(line[_COL_TIME]),
                # The maker is the resting order, so when the buyer is the
                # maker the aggressor was the seller.
                "side": SIDE_SELL if is_buyer_maker else SIDE_BUY,
                "price": float(line[_COL_PRICE]),
                "size": float(line[_COL_QTY]),
            }
        )
    return rows


def fetch_day(symbol: str, file_date: str, client: httpx.Client) -> list[dict] | None:
    """One source archive, or None when Binance Vision has not published it."""
    response = client.get(archive_url(symbol, file_date))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    try:
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        names = archive.namelist()
        if not names:
            raise ImportError_(f"Empty archive for {symbol} on {file_date}.")
        return parse_trades_csv(archive.read(names[0]))
    except zipfile.BadZipFile:
        raise ImportError_(
            f"Downloaded file for {file_date} is not a valid zip archive."
        ) from None


def output_path(dest: Path, symbol: str, file_date: str) -> Path:
    """Imported Binance lands in the same tree as purchased data.

    That is the whole point of the importer: one root, one schema, one
    partition layout, so a DuckDB view spans both without a join or a copy.
    """
    return data_path(dest, f"BINANCE:{symbol.upper()}", "Trade", file_date)


def import_range(
    symbol: str,
    start_date: str,
    end_date: str,
    dest: Path,
    *,
    client: httpx.Client | None = None,
    force: bool = False,
) -> list[DayResult]:
    """Import a range of JST days from Binance Vision."""
    owns = client is None
    client = client or httpx.Client(timeout=120.0, follow_redirects=True)
    try:
        return run_range(
            lambda d: fetch_day(symbol, d, client),
            f"BINANCE:{symbol.upper()}", start_date, end_date, dest, force=force,
        )
    finally:
        if owns:
            client.close()
