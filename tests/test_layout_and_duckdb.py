"""The tree on disk, and querying it with DuckDB."""

import pytest

from komachi import binance_vision
from komachi.layout import (
    InvalidMarketError,
    data_path,
    dataset_glob,
    local_inventory,
    root_path,
    view_sql,
)


def test_root_path_prefers_explicit_then_env(tmp_path, monkeypatch):
    monkeypatch.delenv("ROOT_PATH", raising=False)
    monkeypatch.delenv("KQL_ROOT_PATH", raising=False)
    assert root_path(str(tmp_path)) == tmp_path

    monkeypatch.setenv("ROOT_PATH", "/from/env")
    assert root_path(None).as_posix() == "/from/env"
    assert root_path(str(tmp_path)) == tmp_path  # explicit still wins


def test_root_path_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("ROOT_PATH", raising=False)
    monkeypatch.delenv("KQL_ROOT_PATH", raising=False)
    assert root_path(None).name == "kamakuraquantlab-data"


def test_invalid_market_is_rejected(tmp_path):
    with pytest.raises(InvalidMarketError):
        data_path(tmp_path, "not-a-market", "Trade", "2026-01-01")


def test_purchased_and_imported_data_share_one_tree(tmp_path):
    """The importer must land beside bought data, not next to it."""
    bought = data_path(tmp_path, "GMO:BTC_JPY", "Trade", "2026-01-15")
    imported = binance_vision.output_path(tmp_path, "BTC_USDT", "2026-01-15")

    assert bought.parents[3] == imported.parents[3] == tmp_path / "bronze" / "dataset=Trade"
    assert imported.relative_to(tmp_path).as_posix() == (
        "bronze/dataset=Trade/exchange=BINANCE/symbol=BTC_USDT/date=2026-01-15/data.parquet"
    )


def test_glob_covers_every_market_by_default(tmp_path):
    glob = dataset_glob(tmp_path, "Trade")
    assert "exchange=*" in glob and "symbol=*" in glob and "date=*" in glob

    scoped = dataset_glob(tmp_path, "Trade", "GMO:BTC_JPY")
    assert "exchange=GMO" in scoped and "symbol=BTC_JPY" in scoped


def test_view_sql_declares_both_datasets(tmp_path):
    sql = view_sql(tmp_path)
    assert "CREATE OR REPLACE VIEW trade" in sql
    assert "CREATE OR REPLACE VIEW orderbook" in sql
    assert "hive_partitioning = true" in sql
    assert "union_by_name = true" in sql


def test_local_inventory_reports_what_is_present(tmp_path):
    assert local_inventory(tmp_path) == {}

    for date in ("2026-01-01", "2026-01-02"):
        p = data_path(tmp_path, "GMO:BTC_JPY", "Trade", date)
        p.parent.mkdir(parents=True)
        p.write_bytes(b"x")

    inventory = local_inventory(tmp_path)
    assert inventory[("GMO:BTC_JPY", "Trade")] == ["2026-01-01", "2026-01-02"]


def _write_parquet(path, rows):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pydict(rows), path)


def test_duckdb_recovers_partitions_as_columns(tmp_path):
    """The reason for matching the warehouse layout: no manifest needed."""
    pytest.importorskip("duckdb")
    from komachi.duck import build_database

    for market, date in [("GMO:BTC_JPY", "2026-01-01"), ("COINCHECK:BTC_SPOT", "2026-01-02")]:
        _write_parquet(
            data_path(tmp_path, market, "Trade", date),
            {"ts": [1.0, 2.0], "side": [0, 1], "price": [100.0, 101.0], "size": [0.5, 0.25]},
        )

    counts = build_database(tmp_path, tmp_path / "kql.duckdb")
    assert counts["trade"] == 4

    import duckdb

    conn = duckdb.connect(str(tmp_path / "kql.duckdb"))
    try:
        exchanges = {r[0] for r in conn.execute("SELECT DISTINCT exchange FROM trade").fetchall()}
        assert exchanges == {"GMO", "COINCHECK"}
        # date comes back from the path, so a buyer can filter without a manifest
        rows = conn.execute("SELECT count(*) FROM trade WHERE exchange = 'GMO'").fetchone()[0]
        assert rows == 2
    finally:
        conn.close()


def test_duckdb_spans_purchased_and_imported_data(tmp_path):
    """One view over both sources is the cross-market pitch, made concrete."""
    pytest.importorskip("duckdb")
    from komachi.duck import build_database

    _write_parquet(
        data_path(tmp_path, "GMO:BTC_JPY", "Trade", "2026-01-01"),
        {"ts": [1.0], "side": [0], "price": [100.0], "size": [1.0]},
    )
    _write_parquet(
        binance_vision.output_path(tmp_path, "BTC_USDT", "2026-01-01"),
        {"ts": [1.0], "side": [0], "price": [50000.0], "size": [0.1]},
    )

    build_database(tmp_path, tmp_path / "kql.duckdb")
    import duckdb

    conn = duckdb.connect(str(tmp_path / "kql.duckdb"))
    try:
        exchanges = {r[0] for r in conn.execute("SELECT DISTINCT exchange FROM trade").fetchall()}
        assert exchanges == {"GMO", "BINANCE"}
    finally:
        conn.close()


def test_duckdb_works_when_only_one_dataset_was_bought(tmp_path):
    """A buyer with trades but no order book is normal, not an error."""
    pytest.importorskip("duckdb")
    from komachi.duck import build_database, missing_datasets

    _write_parquet(
        data_path(tmp_path, "GMO:BTC_JPY", "Trade", "2026-01-01"),
        {"ts": [1.0], "side": [0], "price": [100.0], "size": [1.0]},
    )

    counts = build_database(tmp_path, tmp_path / "kql.duckdb")
    assert counts == {"trade": 1}
    assert missing_datasets(tmp_path) == ["OrderBook"]


def test_duckdb_on_an_empty_root_is_not_an_error(tmp_path):
    pytest.importorskip("duckdb")
    from komachi.duck import build_database

    assert build_database(tmp_path, tmp_path / "kql.duckdb") == {}
