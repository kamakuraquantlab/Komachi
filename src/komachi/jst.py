"""Asia/Tokyo days, and re-cutting foreign sources onto them.

Every partition in the Kamakura warehouse is a JST day: `date=2026-01-15`
holds 2026-01-15 00:00 to 23:59 Asia/Tokyo, which is 2026-01-14 15:00 to
2026-01-15 14:59 UTC. Timestamps inside the files are UTC epoch seconds.

Imported sources do not use that boundary, and none of them use the same one:

    Binance Vision    00:00 UTC       9 hours behind the JST day
    GMO archives      21:00 UTC       the 06:00 JST trading-day rollover

So an import cannot simply rename a source file into a `date=` directory. A
Binance archive for 2026-01-15 spans two JST days, and so does a GMO one. A
buyer joining `date=2026-01-15` across an imported and a purchased market
would be comparing windows nine hours apart, silently, which is precisely the
ETL-free promise the importers exist to make.

Rows are therefore re-cut here. Both source boundaries fall inside the JST day
that shares their date, so building JST day D needs source days D-1 and D, and
a day is written only when both are present.
"""

import datetime as dt
from zoneinfo import ZoneInfo

TOKYO = ZoneInfo("Asia/Tokyo")
SECONDS_PER_DAY = 86400


def day_bounds(file_date: str) -> tuple[float, float]:
    """UTC epoch seconds spanning one JST day, start inclusive, end exclusive."""
    day = dt.date.fromisoformat(file_date)
    start = dt.datetime(day.year, day.month, day.day, tzinfo=TOKYO)
    return start.timestamp(), start.timestamp() + SECONDS_PER_DAY


def day_of(ts: float) -> str:
    """The JST date a UTC epoch timestamp belongs to."""
    return dt.datetime.fromtimestamp(ts, TOKYO).strftime("%Y-%m-%d")


def source_days_for(file_date: str) -> list[str]:
    """Source archives needed to cover one JST day.

    Both supported sources start their day at a UTC hour that falls inside the
    JST day of the same date, so the JST day needs that archive and the one
    before it.
    """
    day = dt.date.fromisoformat(file_date)
    return [(day - dt.timedelta(days=1)).isoformat(), file_date]


def date_range(start_date: str, end_date: str) -> list[str]:
    start = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)
    if end < start:
        raise ValueError(f"End date {end_date} is before start date {start_date}.")
    return [(start + dt.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def bucket_by_day(rows: list[dict]) -> dict[str, list[dict]]:
    """Group rows by the JST day their timestamp falls in, each day sorted."""
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(day_of(row["ts"]), []).append(row)
    for day in out.values():
        day.sort(key=lambda r: r["ts"])
    return out
