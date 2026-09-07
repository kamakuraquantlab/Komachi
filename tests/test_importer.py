"""The shape both importers share: fetch, re-cut, write whole days only."""

import datetime as dt

import pytest

from komachi import importer, jst
from komachi.layout import data_path

MARKET = "GMO:BTC_JPY"


def _ts(y, m, d, hh):
    return dt.datetime(y, m, d, hh, tzinfo=dt.timezone.utc).timestamp()


def _row(ts):
    return {"ts": ts, "side": 0, "price": 1.0, "size": 1.0}


def _fetcher(available):
    """A source that publishes only the dates it was given."""
    seen = []

    def fetch(date):
        seen.append(date)
        return available.get(date)

    fetch.seen = seen
    return fetch


def test_each_source_archive_is_fetched_once_not_once_per_day(tmp_path):
    """Consecutive JST days share a source archive, so fetching per JST day
    would download every file twice."""
    days = {d: [_row(_ts(2026, 1, int(d[-2:]), 12))] for d in
            ["2026-01-14", "2026-01-15", "2026-01-16"]}
    fetch = _fetcher(days)

    importer.run_range(fetch, MARKET, "2026-01-15", "2026-01-16", tmp_path)

    assert sorted(fetch.seen) == ["2026-01-14", "2026-01-15", "2026-01-16"]
    assert len(fetch.seen) == len(set(fetch.seen))


def test_a_day_is_written_only_when_every_source_it_needs_arrived(tmp_path):
    fetch = _fetcher({"2026-01-15": [_row(_ts(2026, 1, 15, 3))]})   # the 14th is missing
    assert importer.run_range(fetch, MARKET, "2026-01-15", "2026-01-15", tmp_path) == []
    assert not data_path(tmp_path, MARKET, "Trade", "2026-01-15").exists()


def test_a_day_with_no_rows_is_not_written_as_an_empty_file(tmp_path):
    """Both archives exist and neither contains anything for this JST day."""
    fetch = _fetcher({"2026-01-14": [], "2026-01-15": []})
    assert importer.run_range(fetch, MARKET, "2026-01-15", "2026-01-15", tmp_path) == []


def test_rows_land_in_the_jst_day_they_belong_to(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    fetch = _fetcher({
        "2026-01-14": [_row(_ts(2026, 1, 14, 16))],   # 01:00 JST on the 15th
        "2026-01-15": [_row(_ts(2026, 1, 15, 3)),     # 12:00 JST on the 15th
                       _row(_ts(2026, 1, 15, 16))],   # 01:00 JST on the 16th
    })

    results = importer.run_range(fetch, MARKET, "2026-01-15", "2026-01-15", tmp_path)

    assert [r.rows for r in results] == [2]
    table = pq.read_table(results[0].path)
    assert all(jst.day_of(t) == "2026-01-15" for t in table.column("ts").to_pylist())


def test_an_existing_day_is_skipped_without_fetching_anything(tmp_path):
    path = data_path(tmp_path, MARKET, "Trade", "2026-01-15")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"already here")

    def fetch(date):  # pragma: no cover - must not be reached
        raise AssertionError("nothing should have been fetched")

    results = importer.run_range(fetch, MARKET, "2026-01-15", "2026-01-15", tmp_path)
    assert [r.skipped for r in results] == [True]


def test_force_refetches_a_day_already_on_disk(tmp_path):
    path = data_path(tmp_path, MARKET, "Trade", "2026-01-15")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"stale")
    fetch = _fetcher({"2026-01-14": [], "2026-01-15": [_row(_ts(2026, 1, 15, 3))]})

    results = importer.run_range(fetch, MARKET, "2026-01-15", "2026-01-15",
                                 tmp_path, force=True)

    assert [r.rows for r in results] == [1]
    assert path.read_bytes() != b"stale"


def test_a_range_reports_what_it_skipped_alongside_what_it_wrote(tmp_path):
    done = data_path(tmp_path, MARKET, "Trade", "2026-01-15")
    done.parent.mkdir(parents=True)
    done.write_bytes(b"already here")
    fetch = _fetcher({d: [_row(_ts(2026, 1, 16, 3))] for d in
                      ["2026-01-14", "2026-01-15", "2026-01-16"]})

    results = importer.run_range(fetch, MARKET, "2026-01-15", "2026-01-16", tmp_path)

    by_date = {r.file_date: r for r in results}
    assert by_date["2026-01-15"].skipped is True
    assert by_date["2026-01-16"].skipped is False
    assert [r.file_date for r in results] == sorted(by_date)


def test_write_parquet_produces_the_trade_schema(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    path = tmp_path / "data.parquet"
    importer.write_parquet([_row(_ts(2026, 1, 15, 3))], path)
    assert pq.read_table(path).column_names == ["ts", "side", "price", "size"]
