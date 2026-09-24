"""Three sources, one fetch loop.

`download` and `import` differ in where the bytes come from and in nothing
else. Both work out which days a range covers, drop the ones already on disk,
fetch what is left one unit at a time, and say what happened as it happens.
That shape lives here so the CLI holds one loop rather than two that drift.

What a "unit" is differs by source and that is the only asymmetry worth
keeping. Kamakura Quant Lab sells datasets within a market-day, so a unit is
one file and a day may be two. A venue's own trade archive has one dataset, so
a unit is a day.

The importers used to read every source archive into memory, bucket the lot,
and write at the end. That is why an import printed nothing until it finished,
and why a long range grew without bound. Each JST day is built and written
before the next one starts now, with only the source archives that day needs
held: a fortnight of Binance no longer needs a fortnight of Binance in RAM.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from . import jst
from .download import already_have, download_file
from .importer import ImportError_, write_parquet
from .layout import data_path


@dataclass(frozen=True)
class Unit:
    """One thing to fetch, and what is known about it before fetching."""

    file_date: str
    data_type: str
    size_bytes: int = 0
    meta: dict = field(default_factory=dict, compare=False)

    @property
    def label(self) -> str:
        return f"{self.file_date} {self.data_type}"


@dataclass
class Outcome:
    unit: Unit
    path: Path | None = None
    bytes_written: int = 0
    rows: int = 0
    skipped: bool = False
    verified: bool = False
    unavailable: bool = False
    """The source has no such day. Not an error; the range simply reaches
    past what exists, or across a gap."""


class Downloader(ABC):
    """Where bytes come from, and what one unit of them is."""

    source: str = ""
    spends_allowance: bool = False
    unit_noun: str = "file"
    """What one unit is, for the sentence that counts them. A market-day is
    two files here and one day at a venue that publishes one dataset, so the
    count and the word have to come from the same place."""
    past_verb: str = "downloaded"
    """What happened to them. Files bought here are downloaded; a venue's
    archive is parsed and re-cut before anything lands, so it is written."""

    @abstractmethod
    def plan(self, market: str, dates: list[str]) -> list[Unit]:
        """Every unit those dates cover, whether or not it is already here."""

    @abstractmethod
    def have(self, market: str, unit: Unit, dest: Path) -> bool:
        """Whether this unit is already complete on disk."""

    @abstractmethod
    def fetch(self, market: str, unit: Unit, dest: Path, *, force: bool = False) -> Outcome:
        """Fetch one unit. Raises only on a fault, not on an absent day."""

    def close(self) -> None:
        """Release whatever the source holds. Safe to call twice."""


class YukinoshitaDownloader(Downloader):
    """The archive that was paid for.

    The only source that costs anything, and the only one whose plan is known
    in advance: the catalogue carries the size and the checksum of every file
    before a byte moves, which is what lets the cost and the total be stated
    before the buyer agrees to either.
    """

    source = "Kamakura Quant Lab"
    spends_allowance = True
    unit_noun = "file"
    past_verb = "downloaded"

    def __init__(self, client, http):
        self.client = client
        self.http = http

    def plan(self, market: str, dates: list[str]) -> list[Unit]:
        if not dates:
            return []
        entries = self.client.stats(market, start=dates[0], end=dates[-1])
        wanted = set(dates)
        return [
            Unit(e["file_date"], e["data_type"], e.get("size_bytes") or 0, e)
            for e in sorted(entries, key=lambda e: (e["file_date"], e["data_type"]))
            if e["file_date"] in wanted
        ]

    def have(self, market: str, unit: Unit, dest: Path) -> bool:
        return already_have(unit.meta, dest)

    def fetch(self, market: str, unit: Unit, dest: Path, *, force: bool = False) -> Outcome:
        # Signed at the moment of use. A URL minted up front for a long range
        # expires before its turn comes.
        entry = dict(unit.meta, url=self.client.download_link(
            market, unit.file_date, unit.data_type))
        result = download_file(entry, dest, client=self.http, force=force)
        return Outcome(unit, path=result.path, bytes_written=result.bytes_written,
                       verified=result.verified, skipped=result.skipped)


class TradeArchiveDownloader(Downloader):
    """A venue's own trade history, re-cut onto JST days.

    The two venues differ only in the URL and the CSV, so both subclasses
    provide `fetch_source_day` and nothing else.

    A JST day spans two of the venue's days, and consecutive JST days share
    one. Fetched archives are therefore kept until the day that still needs
    them has been written, and dropped immediately after: the cache holds two
    source days, not the range.
    """

    spends_allowance = False
    unit_noun = "day"
    past_verb = "written"

    def __init__(self, http):
        self.http = http
        self._cache: dict[str, list[dict] | None] = {}

    @abstractmethod
    def fetch_source_day(self, symbol: str, source_date: str) -> list[dict] | None:
        """The venue's own archive for one of its days, or None if absent."""

    def plan(self, market: str, dates: list[str]) -> list[Unit]:
        return [Unit(d, "Trade") for d in dates]

    def have(self, market: str, unit: Unit, dest: Path) -> bool:
        return data_path(dest, market, "Trade", unit.file_date).is_file()

    def _source(self, symbol: str, source_date: str) -> list[dict] | None:
        if source_date not in self._cache:
            self._cache[source_date] = self.fetch_source_day(symbol, source_date)
        return self._cache[source_date]

    def fetch(self, market: str, unit: Unit, dest: Path, *, force: bool = False) -> Outcome:
        symbol = market.split(":", 1)[1]
        needed = jst.source_days_for(unit.file_date)

        rows: list[dict] = []
        for source_date in needed:
            day = self._source(symbol, source_date)
            if day is None:
                # A day missing either of its sources is half a day, and half
                # a day presented as a whole one is the failure the publish
                # gate exists to prevent upstream. It is not written.
                self._prune(needed)
                return Outcome(unit, unavailable=True)
            rows.extend(day)

        self._prune(needed)
        day_rows = jst.bucket_by_day(rows).get(unit.file_date, [])
        if not day_rows:
            return Outcome(unit, unavailable=True)

        path = data_path(dest, market, "Trade", unit.file_date)
        write_parquet(day_rows, path)
        return Outcome(unit, path=path, rows=len(day_rows),
                       bytes_written=path.stat().st_size)

    def _prune(self, still_needed: list[str]) -> None:
        """Keep only what the next JST day could still ask for."""
        latest = max(still_needed)
        for source_date in [d for d in self._cache if d < latest]:
            del self._cache[source_date]

    def close(self) -> None:
        self._cache.clear()


class BinanceVisionDownloader(TradeArchiveDownloader):
    source = "Binance Vision"

    def fetch_source_day(self, symbol: str, source_date: str) -> list[dict] | None:
        from . import binance_vision

        return binance_vision.fetch_day(symbol, source_date, self.http)


class GmoTradesDownloader(TradeArchiveDownloader):
    source = "GMO coin"

    def fetch_source_day(self, symbol: str, source_date: str) -> list[dict] | None:
        from . import gmo_archive

        return gmo_archive.fetch_day(symbol, source_date, self.http)


# Which venues publish their own trade history, keyed on what a buyer types.
IMPORTERS: dict[str, type[TradeArchiveDownloader]] = {
    "BINANCE": BinanceVisionDownloader,
    "GMO": GmoTradesDownloader,
}

__all__ = [
    "Downloader", "Unit", "Outcome", "YukinoshitaDownloader",
    "TradeArchiveDownloader", "BinanceVisionDownloader", "GmoTradesDownloader",
    "IMPORTERS", "ImportError_",
]
