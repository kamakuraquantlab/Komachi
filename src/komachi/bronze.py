"""What bronze is on disk, for anything that needs to ask.

Komachi writes the bronze layer and is therefore the thing that knows what is
in it. Every other tool in the ecosystem can assume Komachi is installed --
Hase depends on it already -- so the answer to "what do I have" lives here
once rather than being re-derived from the directory names by each reader.

The alternative was each tool globbing the tree itself, which is what Hase
did. Two implementations of one question drift: a change to the layout, to
what counts as a complete day, or to the partition names has to be made in
both, and the day they disagree is the day a derivation silently skips a date
the downloader thinks it has.

Nothing here touches the API or the network. It reports what is on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .layout import BRONZE, local_inventory, parse_market
from .settings import data_root

DATA_TYPES = ("Trade", "OrderBook")


@dataclass(frozen=True)
class DatasetState:
    """One dataset of one market, as it stands on disk."""

    market: str
    data_type: str
    dates: list[str]

    @property
    def days(self) -> int:
        return len(self.dates)

    @property
    def first(self) -> str | None:
        return self.dates[0] if self.dates else None

    @property
    def last(self) -> str | None:
        return self.dates[-1] if self.dates else None

    @property
    def gaps(self) -> list[tuple[str, str]]:
        """Runs of missing dates inside the span, as (start, end) inclusive.

        Absent before the first date or after the last is not a gap: the span
        is what was fetched, and asking for more is a download, not a fault.
        """
        import datetime as dt

        if len(self.dates) < 2:
            return []
        have = {dt.date.fromisoformat(d) for d in self.dates}
        out, run = [], []
        day = dt.date.fromisoformat(self.dates[0])
        last = dt.date.fromisoformat(self.dates[-1])
        while day <= last:
            if day not in have:
                run.append(day)
            elif run:
                out.append((run[0].isoformat(), run[-1].isoformat()))
                run = []
            day += dt.timedelta(days=1)
        if run:
            out.append((run[0].isoformat(), run[-1].isoformat()))
        return out


def _root(root: Path | str | None = None) -> Path:
    """The data root, from the argument or from the settings file."""
    return Path(root).expanduser() if root else data_root()


def dates(market: str, data_type: str, root: Path | str | None = None) -> list[str]:
    """Every JST date of one dataset that is complete on disk, sorted.

    A date is present when its `data.parquet` exists. A directory without one
    is a partial fetch and is not reported as held.
    """
    if data_type not in DATA_TYPES:
        raise ValueError(f"Not a bronze dataset: {data_type!r}. One of {DATA_TYPES}.")
    exchange, symbol = parse_market(market)
    base = (_root(root) / BRONZE / f"dataset={data_type}"
            / f"exchange={exchange}" / f"symbol={symbol}")
    if not base.is_dir():
        return []
    return sorted(d.name.split("=", 1)[1] for d in base.glob("date=*")
                  if (d / "data.parquet").is_file())


def state(market: str, data_type: str, root: Path | str | None = None) -> DatasetState:
    """`dates`, with the span and the gaps worked out."""
    return DatasetState(market, data_type, dates(market, data_type, root))


def market_state(market: str, root: Path | str | None = None) -> dict[str, DatasetState]:
    """Both datasets of one market, keyed by dataset name."""
    return {t: state(market, t, root) for t in DATA_TYPES}


def markets(root: Path | str | None = None) -> list[str]:
    """Every market with at least one complete bronze file, sorted."""
    return sorted({m for m, _ in local_inventory(_root(root))})


def inventory(root: Path | str | None = None) -> dict[tuple[str, str], list[str]]:
    """Every (market, dataset) on disk and the dates it holds."""
    return local_inventory(_root(root))
