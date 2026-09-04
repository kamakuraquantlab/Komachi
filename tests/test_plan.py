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


def test_a_spent_allowance_plans_nothing():
    client = FakeClient(dates=WEEK, remaining=0)
    files, _, _ = cli._plan(client, Args(), remaining=0)
    assert files == []
    assert client.stats_calls == []      # nothing was even asked of the API


def test_the_plan_is_shown_and_refused_when_the_allowance_is_short(capsys):
    catalogued = [{"file_date": d, "size_bytes": 1000} for d in WEEK]
    estimate = {"new_market_days": 7, "sufficient": False, "remaining_market_days": 3}

    ok = cli._show_plan("COINCHECK:BTC_SPOT", WEEK[0], WEEK[-1], catalogued,
                        catalogued, 0, estimate, remaining=3)

    assert ok is False
    err = capsys.readouterr().err
    assert "--days 3" in err        # tells the buyer how to ask for less


def test_a_zero_cost_is_explained(capsys):
    """Seven days for nothing reads as a bug unless the reason is given."""
    catalogued = [{"file_date": d, "size_bytes": 1000} for d in WEEK]
    estimate = {"new_market_days": 0, "sufficient": True, "remaining_market_days": 21}

    cli._show_plan("COINCHECK:BTC_SPOT", WEEK[0], WEEK[-1], catalogued,
                   catalogued, 0, estimate, remaining=21)

    out = capsys.readouterr().out
    assert "already paid for on this token" in out
