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
        self.end = None
        self.__dict__.update(kw)


WEEK = [f"2025-07-{d:02d}" for d in range(1, 8)]


def _dates(args, fallback):
    return cli._dates_for(args, fallback=fallback)


def test_without_days_it_plans_the_whole_remaining_allowance():
    """The buyer should not have to work out how much they can still afford."""
    dates = _dates(Args(), fallback=21)

    assert dates[0] == "2025-07-01"
    assert dates[-1] == "2025-07-21"        # 21 days, matching the allowance
    assert len(dates) == 21


def test_days_caps_the_span():
    dates = _dates(Args(days=3), fallback=21)
    assert (dates[0], dates[-1]) == ("2025-07-01", "2025-07-03")
    assert len(dates) == 3


def test_end_is_the_other_way_to_say_it():
    """`import` was --start/--end and `download` was --start/--days. Both take
    both now, because a buyer should not have to remember which verb wants
    which."""
    dates = _dates(Args(end="2025-07-05"), fallback=21)
    assert (dates[0], dates[-1]) == ("2025-07-01", "2025-07-05")


def test_days_and_end_together_are_refused():
    """They say the same thing, so one would have to silently win."""
    import pytest

    with pytest.raises(SystemExit, match="not both"):
        _dates(Args(days=3, end="2025-07-05"), fallback=21)


def test_the_catalogue_decides_what_those_dates_actually_hold():
    """A range is dates; a plan is files. The gap between them is the gaps."""
    from komachi import downloaders

    client = FakeClient(dates=[f"2025-07-{d:02d}" for d in range(1, 30)])
    units = downloaders.YukinoshitaDownloader(client, None).plan(
        "COINCHECK:BTC_SPOT", _dates(Args(days=3), fallback=21))

    assert len({u.file_date for u in units}) == 3


def test_the_range_is_clamped_to_what_the_catalogue_holds():
    """Asking for 21 days when 7 are published should report the 7."""
    from komachi import downloaders

    client = FakeClient(dates=WEEK, remaining=21)
    units = downloaders.YukinoshitaDownloader(client, None).plan(
        "COINCHECK:BTC_SPOT", _dates(Args(), fallback=21))

    assert (units[0].file_date, units[-1].file_date) == ("2025-07-01", "2025-07-07")
    assert len({u.file_date for u in units}) == 7


def test_an_empty_catalogue_plans_nothing():
    from komachi import downloaders

    client = FakeClient(dates=[])
    assert downloaders.YukinoshitaDownloader(client, None).plan(
        "COINCHECK:BTC_SPOT", _dates(Args(), fallback=21)) == []


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
