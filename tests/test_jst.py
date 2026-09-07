"""Asia/Tokyo day arithmetic.

The highest-risk logic in Komachi and the least visible when wrong. Every
imported row is filed by these functions, and a mistake here does not raise:
it puts data in the wrong day and the file still opens, still validates, and
still joins — against the wrong hours. The Binance importer shipped exactly
that bug before this module existed.
"""

import datetime as dt
import os
import subprocess
import sys

import pytest

from komachi import jst


def _utc(y, m, d, hh=0, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=dt.timezone.utc).timestamp()


def test_a_jst_day_runs_from_1500_utc_to_1500_utc():
    start, end = jst.day_bounds("2026-01-15")
    assert start == _utc(2026, 1, 14, 15)
    assert end == _utc(2026, 1, 15, 15)
    assert end - start == jst.SECONDS_PER_DAY


def test_the_boundaries_belong_to_the_days_you_would_expect():
    """Start inclusive, end exclusive: 15:00 UTC is the first second of the day."""
    assert jst.day_of(_utc(2026, 1, 14, 14, 59)) == "2026-01-14"
    assert jst.day_of(_utc(2026, 1, 14, 15, 0)) == "2026-01-15"
    assert jst.day_of(_utc(2026, 1, 15, 14, 59)) == "2026-01-15"
    assert jst.day_of(_utc(2026, 1, 15, 15, 0)) == "2026-01-16"


def test_a_jst_day_needs_the_source_archive_before_it():
    """Both supported sources start their day inside the JST day of the same
    date, so covering one JST day takes two source archives."""
    assert jst.source_days_for("2026-01-15") == ["2026-01-14", "2026-01-15"]
    assert jst.source_days_for("2026-01-01") == ["2025-12-31", "2026-01-01"]


def test_binance_and_gmo_boundaries_land_where_the_design_says():
    """00:00 UTC and 21:00 UTC both fall inside the JST day of the same date,
    which is what makes one rule cover both sources."""
    assert jst.day_of(_utc(2026, 1, 15, 0)) == "2026-01-15"      # Binance Vision
    assert jst.day_of(_utc(2026, 1, 15, 21)) == "2026-01-16"     # GMO rollover
    # ... so a GMO file named for the 16th begins on the evening of the 15th.
    assert jst.source_days_for("2026-01-16")[0] == "2026-01-15"


def test_date_range_is_inclusive_and_refuses_a_backwards_range():
    assert jst.date_range("2026-01-01", "2026-01-03") == [
        "2026-01-01", "2026-01-02", "2026-01-03"]
    assert jst.date_range("2026-01-01", "2026-01-01") == ["2026-01-01"]
    with pytest.raises(ValueError):
        jst.date_range("2026-01-03", "2026-01-01")


def test_date_range_crosses_a_month_and_a_year():
    assert jst.date_range("2026-01-30", "2026-02-02") == [
        "2026-01-30", "2026-01-31", "2026-02-01", "2026-02-02"]
    assert jst.date_range("2025-12-31", "2026-01-01") == ["2025-12-31", "2026-01-01"]


def test_a_leap_day_is_a_day_like_any_other():
    assert jst.date_range("2028-02-28", "2028-03-01") == [
        "2028-02-28", "2028-02-29", "2028-03-01"]


def test_bucket_by_day_splits_a_source_file_across_two_jst_days():
    rows = [
        {"ts": _utc(2026, 1, 14, 16), "n": "evening of the 14th UTC"},
        {"ts": _utc(2026, 1, 15, 3), "n": "morning of the 15th UTC"},
        {"ts": _utc(2026, 1, 15, 23), "n": "night of the 15th UTC"},
    ]
    out = jst.bucket_by_day(rows)
    assert sorted(out) == ["2026-01-15", "2026-01-16"]
    assert len(out["2026-01-15"]) == 2
    assert len(out["2026-01-16"]) == 1


def test_each_bucket_comes_out_sorted():
    later, earlier = _utc(2026, 1, 15, 5), _utc(2026, 1, 15, 1)
    out = jst.bucket_by_day([{"ts": later}, {"ts": earlier}])
    assert [r["ts"] for r in out["2026-01-15"]] == [earlier, later]


@pytest.mark.parametrize("tz", ["UTC", "Asia/Tokyo", "America/New_York", "Europe/London"])
def test_the_answer_does_not_depend_on_the_machine(tz):
    """A JST day is a JST day wherever the importer runs.

    Run in a subprocess because TZ is read once per process. Without this the
    same file imported on a Tokyo laptop and a UTC server would land in
    different days, and both would look correct locally.
    """
    script = (
        "import datetime as dt;"
        "from komachi import jst;"
        "t = dt.datetime(2026, 1, 14, 15, 0, tzinfo=dt.timezone.utc).timestamp();"
        "print(jst.day_of(t), jst.day_bounds('2026-01-15')[0])"
    )
    env = {**os.environ, "TZ": tz, "PYTHONPATH": "src"}
    out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, env=env, cwd=os.getcwd())
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["2026-01-15", str(_utc(2026, 1, 14, 15))]
