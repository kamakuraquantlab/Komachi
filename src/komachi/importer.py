"""Turning a foreign archive into JST-partitioned parquet.

Both importers do the same three things and differ only in how they fetch and
parse a day, so that shape lives here: fetch the source days a JST day needs,
re-cut the rows onto JST boundaries, write one file per whole day.

A day is written only when every source archive covering it was fetched. A JST
day built from one of its two sources would be half a day presented as a whole
one, which is the failure the publish gate exists to prevent upstream and is no
more acceptable here.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import jst
from .layout import data_path


class ImportError_(RuntimeError):
    """An import that failed for a reason worth showing the buyer verbatim."""


@dataclass
class DayResult:
    file_date: str
    path: Path
    rows: int
    skipped: bool = False


def run_range(
    fetch_day: Callable[[str], list[dict] | None],
    market: str,
    start_date: str,
    end_date: str,
    dest: Path,
    *,
    force: bool = False,
) -> list[DayResult]:
    """Import a range of JST days, fetching each source archive once.

    `fetch_day` takes a source date and returns parsed rows, or None when the
    archive does not exist. A missing archive is not an error by itself: it
    only means the JST days depending on it cannot be completed.
    """
    wanted = jst.date_range(start_date, end_date)

    todo = [d for d in wanted if force or not data_path(dest, market, "Trade", d).exists()]
    already = [d for d in wanted if d not in todo]
    if not todo:
        return [DayResult(d, data_path(dest, market, "Trade", d), 0, skipped=True) for d in already]

    # Each source archive covers two JST days, so fetching per JST day would
    # download everything twice.
    needed: list[str] = []
    for d in todo:
        for s in jst.source_days_for(d):
            if s not in needed:
                needed.append(s)

    rows: list[dict] = []
    fetched: set[str] = set()
    for source_date in sorted(needed):
        day_rows = fetch_day(source_date)
        if day_rows is None:
            continue
        fetched.add(source_date)
        rows.extend(day_rows)

    by_day = jst.bucket_by_day(rows)

    results = [DayResult(d, data_path(dest, market, "Trade", d), 0, skipped=True) for d in already]
    for file_date in todo:
        if not all(s in fetched for s in jst.source_days_for(file_date)):
            continue
        day_rows = by_day.get(file_date, [])
        if not day_rows:
            continue
        path = data_path(dest, market, "Trade", file_date)
        write_parquet(day_rows, path)
        results.append(DayResult(file_date, path, len(day_rows)))
    return sorted(results, key=lambda r: r.file_date)


def write_parquet(rows: list[dict], path: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise ImportError_(
            "pyarrow is required to write parquet. Install with: pip install 'komachi[data]'"
        ) from None

    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pydict(
        {
            "ts": [r["ts"] for r in rows],
            "side": [r["side"] for r in rows],
            "price": [r["price"] for r in rows],
            "size": [r["size"] for r in rows],
        }
    )
    pq.write_table(table, path, compression="snappy")
