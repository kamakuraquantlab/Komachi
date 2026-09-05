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


def test_import_writes_the_warehouse_layout(tmp_path):
    payload = _zip_of(
        [
            "1,50000.0,0.5,25000.0,1767225600000,true,true",
            "2,50001.0,0.25,12500.0,1767225601000,false,true",
        ]
    )

    result = binance_vision.import_day("BTC_USDT", "2026-01-01", tmp_path, client=_client(payload))

    assert result.rows == 2
    assert result.path.relative_to(tmp_path).as_posix() == (
        "bronze/dataset=Trade/exchange=BINANCE/symbol=BTC_USDT/date=2026-01-01/data.parquet"
    )


def test_imported_file_matches_the_trade_schema(tmp_path):
    """The whole point: both sources load through one reader."""
    pq = pytest.importorskip("pyarrow.parquet")
    payload = _zip_of(["1,50000.0,0.5,25000.0,1767225600000,true,true"])

    result = binance_vision.import_day("BTC_USDT", "2026-01-01", tmp_path, client=_client(payload))
    table = pq.read_table(result.path)

    # The data columns match the Trade schema, and pyarrow additionally recovers
    # dataset/exchange/symbol/date from the Hive path -- the same discovery that
    # works against the parquet warehouse, which is the point.
    assert table.column_names[:4] == ["ts", "side", "price", "size"]
    assert {"dataset", "exchange", "symbol", "date"} <= set(table.column_names)
    assert table.num_rows == 1


def test_existing_day_is_skipped(tmp_path):
    path = binance_vision.output_path(tmp_path, "BTC_USDT", "2026-01-01")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"already here")

    def handler(request):  # pragma: no cover - must not be reached
        raise AssertionError("should not have been fetched")

    result = binance_vision.import_day(
        "BTC_USDT", "2026-01-01", tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result.skipped is True


def test_missing_archive_explains_itself(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(binance_vision.ImportError_, match="no trades archive"):
        binance_vision.import_day("BTC_USDT", "2099-01-01", tmp_path, client=client)


def test_date_range_is_inclusive():
    assert binance_vision.date_range("2026-01-01", "2026-01-03") == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    with pytest.raises(ValueError):
        binance_vision.date_range("2026-01-03", "2026-01-01")
