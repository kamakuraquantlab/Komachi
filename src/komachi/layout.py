"""Where downloaded files live on disk, and how DuckDB reads them.

Files land in the Hive-partitioned tree the Kamakura warehouse uses, so a
buyer's directory is laid out exactly like the one the data was produced in:

    $ROOT_PATH/bronze/dataset=Trade/exchange=GMO/symbol=BTC_JPY/date=2026-01-15/data.parquet

Two consequences follow, and both are the point of matching rather than
inventing a layout:

  * DuckDB, PyArrow, Spark and Athena all recover `dataset`, `exchange`,
    `symbol` and `date` as real columns from the path, so a whole market-year
    is one `read_parquet` with a glob and no manifest to track.
  * Example notebooks written against the warehouse run unchanged against a
    buyer's copy, because the paths are identical.

The `bronze/` layer is kept even though a buyer receives only bronze. It leaves
room for derived silver and gold datasets computed locally without colliding
with delivered files, which is how the warehouse itself is organised.
"""

import os
import re
from pathlib import Path

BRONZE = "bronze"
DATA_TYPES = ("Trade", "OrderBook")
DEFAULT_ROOT = "~/kql-data"

_MARKET_RE = re.compile(r"^[A-Z0-9]+:[A-Z0-9_]+$")


class InvalidMarketError(ValueError):
    pass


def parse_market(market: str) -> tuple[str, str]:
    """Split "GMO:BTC_JPY" into ("GMO", "BTC_JPY")."""
    if not _MARKET_RE.match(market or ""):
        raise InvalidMarketError(f"Market must look like EXCHANGE:SYMBOL, got {market!r}")
    exchange, symbol = market.split(":", 1)
    return exchange, symbol


def root_path(override: str | None = None) -> Path:
    """$ROOT_PATH, KQL_ROOT_PATH, or the default, in that order."""
    raw = override or os.environ.get("ROOT_PATH") or os.environ.get("KQL_ROOT_PATH") or DEFAULT_ROOT
    return Path(raw).expanduser()


def data_path(root: Path, market: str, data_type: str, file_date: str) -> Path:
    exchange, symbol = parse_market(market)
    return (
        root
        / BRONZE
        / f"dataset={data_type}"
        / f"exchange={exchange}"
        / f"symbol={symbol}"
        / f"date={file_date}"
        / "data.parquet"
    )


def dataset_glob(root: Path, data_type: str, market: str | None = None) -> str:
    """A glob DuckDB can read for one dataset, optionally one market."""
    if market:
        exchange, symbol = parse_market(market)
    else:
        exchange = symbol = "*"
    return str(root / BRONZE / f"dataset={data_type}" / f"exchange={exchange}" / f"symbol={symbol}" / "date=*" / "data.parquet")


def single_view_sql(root: Path, data_type: str) -> str:
    """SQL for one dataset's view.

    `hive_partitioning` turns the path segments into columns, and
    `union_by_name` keeps the read working when a market is added later.
    """
    return (
        f"CREATE OR REPLACE VIEW {data_type.lower()} AS\n"
        f"SELECT * FROM read_parquet(\n"
        f"    '{dataset_glob(root, data_type)}',\n"
        f"    hive_partitioning = true,\n"
        f"    union_by_name = true\n"
        f")"
    )


def view_sql(root: Path) -> str:
    """SQL creating one view per dataset over everything downloaded."""
    return "\n\n".join(f"{single_view_sql(root, d)};" for d in DATA_TYPES)


def local_inventory(root: Path) -> dict[tuple[str, str], list[str]]:
    """What is already on disk, as {(market, data_type): [dates]}."""
    found: dict[tuple[str, str], list[str]] = {}
    base = root / BRONZE
    if not base.is_dir():
        return found
    for data_type in DATA_TYPES:
        ds = base / f"dataset={data_type}"
        if not ds.is_dir():
            continue
        for ex in sorted(ds.glob("exchange=*")):
            for sym in sorted(ex.glob("symbol=*")):
                market = f"{ex.name.split('=', 1)[1]}:{sym.name.split('=', 1)[1]}"
                dates = sorted(
                    d.name.split("=", 1)[1] for d in sym.glob("date=*") if (d / "data.parquet").exists()
                )
                if dates:
                    found[(market, data_type)] = dates
    return found
