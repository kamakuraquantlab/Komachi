"""Deciding what a run covers, before it spends anything."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
import cli  # noqa: E402


class FakeClient:
    """Stands in for the API. Records what was asked for."""

    def __init__(self, dates, remaining=21):
        self.dates = dates
        self.remaining = remaining
        self.stats_calls = []

    def status(self):
        return {"remaining_market_days": self.remaining, "product_id": "starter-4w"}

    def stats(self, market, start=None, end=None, days=None):
        self.stats_calls.append((start, end))
        return [
            {"market": market, "data_type": dt, "file_date": d,
             "size_bytes": 1000, "checksum": "sha256:" + "0" * 64}
            for d in self.dates if (not start or d >= start) and (not end or d <= end)
            for dt in ("OrderBook", "Trade")
        ]


class Args:
    def __init__(self, **kw):
        self.market = "COINCHECK:BTC_SPOT"
        self.start = "2025-07-01"
        self.days = None
        self.__dict__.update(kw)


WEEK = [f"2025-07-{d:02d}" for d in range(1, 8)]


def test_without_days_it_plans_the_whole_remaining_allowance():
    """The buyer should not have to work out how much they can still afford."""
    client = FakeClient(dates=[f"2025-07-{d:02d}" for d in range(1, 30)], remaining=21)

    files, start, end = cli._plan(client, Args(), remaining=21)

    assert start == "2025-07-01"
    assert end == "2025-07-21"          # 21 days, matching the allowance
    assert len({f["file_date"] for f in files}) == 21


def test_days_caps_the_span():
    client = FakeClient(dates=[f"2025-07-{d:02d}" for d in range(1, 30)])
    files, start, end = cli._plan(client, Args(days=3), remaining=21)

    assert (start, end) == ("2025-07-01", "2025-07-03")
    assert len({f["file_date"] for f in files}) == 3


def test_the_range_is_clamped_to_what_the_catalogue_holds():
    """Asking for 21 days when 7 are published should report the 7."""
    client = FakeClient(dates=WEEK, remaining=21)
    files, start, end = cli._plan(client, Args(), remaining=21)

    assert (start, end) == ("2025-07-01", "2025-07-07")
    assert len({f["file_date"] for f in files}) == 7


def test_an_empty_catalogue_plans_nothing():
    client = FakeClient(dates=[])
    files, _, _ = cli._plan(client, Args(), remaining=21)
    assert files == []


def test_the_plan_shows_range_size_and_cost(capsys):
    """The summary is the whole of the client's judgement: it reports, and the
    service decides whether the allowance covers it."""
    catalogued = [{"file_date": d, "size_bytes": 1000} for d in WEEK]
    estimate = {"new_market_days": 7, "remaining_market_days": 21}

    cli._show_plan("COINCHECK:BTC_SPOT", WEEK[0], WEEK[-1], catalogued, catalogued, estimate, 21)

    out = capsys.readouterr().out
    assert "COINCHECK:BTC_SPOT" in out
    assert f"{WEEK[0]} .. {WEEK[-1]}" in out
    assert "7 days" in out
    assert "7 of 21 remaining" in out


def test_files_already_present_are_reported_and_not_counted_to_fetch(capsys):
    catalogued = [{"file_date": d, "size_bytes": 1000} for d in WEEK]
    pending = catalogued[3:]
    estimate = {"new_market_days": 4, "remaining_market_days": 21}

    cli._show_plan("COINCHECK:BTC_SPOT", WEEK[0], WEEK[-1], catalogued, pending, estimate, 21)

    out = capsys.readouterr().out
    assert "4 to download, 3 already present" in out
