"""The Binance Vision importer.

Binance is referred, never delivered: `doc/03` section 4.5. Komachi ships the
importer so a buyer's own download lands in the same tree, schema and partition
layout as purchased data, which is what lets one DuckDB view span both.

These tests moved here with the importer when the single repository was split.
"""

import io
import zipfile

import httpx
import pytest

from komachi import binance_vision


def _zip_of(rows: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BTCUSDT-trades-2026-01-01.csv", "\n".join(rows))
    return buffer.getvalue()


def _client(payload: bytes) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=payload)))


def test_symbol_and_url_translation():
    assert binance_vision.to_binance_symbol("BTC_USDT") == "BTCUSDT"
    assert binance_vision.archive_url("BTC_USDT", "2026-01-15").endswith(
        "/BTCUSDT/BTCUSDT-trades-2026-01-15.zip"
    )


def test_buyer_maker_flag_maps_to_the_aggressor_side():
    """is_buyer_maker means the resting order was the buy, so the taker sold."""
    rows = binance_vision.parse_trades_csv(
        b"1,50000.0,0.5,25000.0,1767225600000,true,true\n"
        b"2,50001.0,0.25,12500.0,1767225601000,false,true\n"
    )
    assert [r["side"] for r in rows] == [binance_vision.SIDE_SELL, binance_vision.SIDE_BUY]
    assert rows[0]["price"] == 50000.0
    assert rows[0]["size"] == 0.5


def test_millisecond_and_microsecond_timestamps_both_normalise():
    ms = binance_vision.parse_trades_csv(b"1,1.0,1.0,1.0,1767225600000,true,true")
    us = binance_vision.parse_trades_csv(b"1,1.0,1.0,1.0,1767225600000000,true,true")
    assert ms[0]["ts"] == us[0]["ts"] == 1767225600.0


def _serving(per_date: dict) -> httpx.Client:
    """Serve one zip per source date; 404 for anything else."""
    def handler(request):
        for date, payload in per_date.items():
            if date in str(request.url):
                return httpx.Response(200, content=payload)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


# 2026-01-01 00:00 UTC is 09:00 JST the same day; 23:00 UTC is 08:00 JST the next.
_UTC_MORNING = "1,50000.0,0.5,25000.0,1767225600000,true,true"    # 2026-01-01 00:00Z
_UTC_EVENING = "2,50001.0,0.25,12500.0,1767308400000,false,true"  # 2026-01-01 23:00Z


def test_a_source_day_is_re_cut_onto_jst_days(tmp_path):
    """A Binance archive spans two JST days, and must not be filed under one.

    The source day starts at 00:00 UTC, nine hours into the JST day of the
    same date, so its evening rows belong to the next JST day. Filing the
    whole archive under its own date would offset imported data from
    purchased data by nine hours, silently.
    """
    client = _serving({
        "2026-01-01": _zip_of([_UTC_MORNING, _UTC_EVENING]),
        "2025-12-31": _zip_of(["3,49000.0,1.0,49000.0,1767196800000,true,true"]),  # 2025-12-31 12:00Z
    })

    results = binance_vision.import_range("BTC_USDT", "2026-01-01", "2026-01-01", tmp_path,
                                          client=client)

    assert [r.file_date for r in results] == ["2026-01-01"]
    # 16:00Z on the 31st is 01:00 JST on the 1st, so it belongs to this day even
    # though it came from the previous archive. 23:00Z on the 1st is 08:00 JST on
    # the 2nd, so it does not.
    assert results[0].rows == 2


def test_import_writes_the_warehouse_layout(tmp_path):
    client = _serving({
        "2026-01-01": _zip_of([_UTC_MORNING]),
        "2025-12-31": _zip_of(["3,49000.0,1.0,49000.0,1767196800000,true,true"]),
    })

    results = binance_vision.import_range("BTC_USDT", "2026-01-01", "2026-01-01", tmp_path,
                                          client=client)

    assert results[0].path.relative_to(tmp_path).as_posix() == (
        "bronze/dataset=Trade/exchange=BINANCE/symbol=BTC_USDT/date=2026-01-01/data.parquet"
    )


def test_imported_file_matches_the_trade_schema(tmp_path):
    """The whole point: both sources load through one reader."""
    pq = pytest.importorskip("pyarrow.parquet")
    client = _serving({
        "2026-01-01": _zip_of([_UTC_MORNING]),
        "2025-12-31": _zip_of(["3,49000.0,1.0,49000.0,1767196800000,true,true"]),
    })

    results = binance_vision.import_range("BTC_USDT", "2026-01-01", "2026-01-01", tmp_path,
                                          client=client)

    # The data columns match the Trade schema, and reading the tree recovers
    # dataset/exchange/symbol/date from the Hive path -- the same discovery
    # that works against the parquet warehouse, which is the point.
    #
    # The file's own schema, not a read of it. `read_table` on a path inside a
    # Hive tree recovers the partition columns on some pyarrow versions and not
    # others -- 22 does, and the assertion below used to fail on it -- so going
    # through the reader tests the reader's version rather than what was
    # written. `schema_arrow` is what is in the file.
    written = pq.ParquetFile(results[0].path).schema_arrow.names
    assert written == ["ts", "side", "price", "size"]
    tree = pq.read_table(tmp_path / "bronze")
    assert {"dataset", "exchange", "symbol", "date"} <= set(tree.column_names)


def test_existing_day_is_skipped(tmp_path):
    path = binance_vision.output_path(tmp_path, "BTC_USDT", "2026-01-01")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"already here")

    def handler(request):  # pragma: no cover - must not be reached
        raise AssertionError("should not have been fetched")

    results = binance_vision.import_range(
        "BTC_USDT", "2026-01-01", "2026-01-01", tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert [r.skipped for r in results] == [True]


def test_a_day_missing_a_source_archive_is_not_written(tmp_path):
    """Half a JST day presented as a whole one is the failure to avoid."""
    client = _serving({"2026-01-01": _zip_of([_UTC_MORNING])})  # the 31st is 404

    results = binance_vision.import_range("BTC_USDT", "2026-01-01", "2026-01-01", tmp_path,
                                          client=client)

    assert results == []
    assert not binance_vision.output_path(tmp_path, "BTC_USDT", "2026-01-01").exists()


def test_date_range_is_inclusive():
    assert binance_vision.date_range("2026-01-01", "2026-01-03") == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    with pytest.raises(ValueError):
        binance_vision.date_range("2026-01-03", "2026-01-01")
