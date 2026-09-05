"""Import GMO's published trade history.

`doc/03` section 4.5 refers buyers to a venue's own free archive rather than
reselling it. GMO publishes daily trade files at a stable URL, so the same
treatment Binance Vision gets applies here: the buyer downloads from GMO, and
this converts it into the layout their purchased data already uses.

    https://api.coin.z.com/data/trades/BTC_JPY/2025/07/20250701_BTC_JPY.csv.gz

    symbol,side,size,price,timestamp
    BTC_JPY,BUY,0.0010,15499938.000,2025-06-30 21:00:19.862

Two things about that file matter. Timestamps are UTC and carry no zone
marker, and the day starts at 21:00 UTC, which is GMO's 06:00 JST trading-day
rollover rather than a calendar day. The file above is named for 1 July and
begins in the evening of 30 June. Rows are therefore re-cut onto JST days by
`importer.run_range`; see `jst` for why that is not optional.

Only trades are published. Order book history is not, which is what a buyer is
actually paying for on the delivered GMO markets.
"""

import csv
import datetime as dt
import gzip
import io

import httpx

from .importer import ImportError_

BASE_URL = "https://api.coin.z.com/data/trades"

# The Trade schema encodes the aggressor side as 0=BUY, 1=SELL.
SIDE_BUY = 0
SIDE_SELL = 1

_COL_SIDE = 1
_COL_SIZE = 2
_COL_PRICE = 3
_COL_TIME = 4


def archive_url(symbol: str, file_date: str) -> str:
    """GMO files are keyed by symbol and date, nested by year and month."""
    day = dt.date.fromisoformat(file_date)
    return (
        f"{BASE_URL}/{symbol}/{day:%Y}/{day:%m}/{day:%Y%m%d}_{symbol}.csv.gz"
    )


def parse_trades_csv(raw: bytes) -> list[dict]:
    """Convert GMO trade rows into Trade records with UTC epoch timestamps."""
    rows: list[dict] = []
    reader = csv.reader(io.StringIO(raw.decode("utf-8")))
    for line in reader:
        if len(line) <= _COL_TIME or line[_COL_SIDE] not in ("BUY", "SELL"):
            continue  # the header, or a malformed line
        rows.append(
            {
                "ts": _parse_timestamp(line[_COL_TIME]),
                "side": SIDE_BUY if line[_COL_SIDE] == "BUY" else SIDE_SELL,
                "price": float(line[_COL_PRICE]),
                "size": float(line[_COL_SIZE]),
            }
        )
    return rows


def _parse_timestamp(text: str) -> float:
    """`2025-06-30 21:00:19.862` is UTC, though the file does not say so.

    Read as naive and stamped UTC rather than parsed with a zone, because
    letting the local machine's zone decide would shift every row by the
    operator's offset and produce a file that looks plausible and is wrong.
    """
    stamp = dt.datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S.%f")
    return stamp.replace(tzinfo=dt.timezone.utc).timestamp()


def fetch_day(symbol: str, file_date: str, client: httpx.Client) -> list[dict] | None:
    """One source archive, or None when GMO has not published it."""
    response = client.get(archive_url(symbol, file_date))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    try:
        raw = gzip.decompress(response.content)
    except OSError:
        raise ImportError_(
            f"GMO's archive for {symbol} on {file_date} is not valid gzip."
        ) from None
    return parse_trades_csv(raw)


def import_range(
    symbol: str,
    start_date: str,
    end_date: str,
    dest,
    *,
    client: httpx.Client | None = None,
    force: bool = False,
):
    """Import a range of JST days from GMO's archive."""
    from .importer import run_range

    owns = client is None
    client = client or httpx.Client(timeout=120.0, follow_redirects=True)
    try:
        return run_range(
            lambda d: fetch_day(symbol, d, client),
            f"GMO:{symbol.upper()}", start_date, end_date, dest, force=force,
        )
    finally:
        if owns:
            client.close()
