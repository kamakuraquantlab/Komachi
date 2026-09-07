"""The GMO importer.

GMO publishes trades free, so Komachi imports rather than Kamakura Quant Lab
reselling. Two things about that archive are easy to get wrong and silent when
wrong: its timestamps carry no zone marker, and its day starts at 21:00 UTC
rather than at midnight anywhere.
"""

import datetime as dt
import gzip
import io
import os
import subprocess
import sys

import httpx
import pytest

from komachi import gmo_archive, jst
from komachi.importer import ImportError_

HEADER = "symbol,side,size,price,timestamp"
ROWS = [
    "BTC_JPY,BUY,0.0010,15499938.000,2025-06-30 21:00:19.862",
    "BTC_JPY,SELL,0.0040,15499853.000,2025-07-01 05:30:00.500",
]


def _gz(lines):
    return gzip.compress(("\n".join([HEADER, *lines]) + "\n").encode())


def test_archive_url_nests_by_year_and_month():
    assert gmo_archive.archive_url("BTC_JPY", "2025-07-01") == (
        "https://api.coin.z.com/data/trades/BTC_JPY/2025/07/20250701_BTC_JPY.csv.gz"
    )


def test_the_header_row_is_not_a_trade():
    rows = gmo_archive.parse_trades_csv(("\n".join([HEADER, *ROWS])).encode())
    assert len(rows) == 2


def test_side_maps_to_the_aggressor_encoding():
    rows = gmo_archive.parse_trades_csv(("\n".join([HEADER, *ROWS])).encode())
    assert [r["side"] for r in rows] == [gmo_archive.SIDE_BUY, gmo_archive.SIDE_SELL]
    assert rows[0]["price"] == 15499938.0
    assert rows[0]["size"] == 0.001


def test_timestamps_are_read_as_utc_not_as_local_time():
    """GMO writes `2025-06-30 21:00:19.862` with no zone. It is UTC.

    Parsed as local time on a Tokyo machine this row would be stamped nine
    hours early and filed a day late, and nothing downstream would object.
    """
    rows = gmo_archive.parse_trades_csv(("\n".join([HEADER, ROWS[0]])).encode())
    expected = dt.datetime(2025, 6, 30, 21, 0, 19, 862000, tzinfo=dt.timezone.utc)
    assert rows[0]["ts"] == expected.timestamp()


@pytest.mark.parametrize("tz", ["UTC", "Asia/Tokyo", "America/New_York"])
def test_parsing_does_not_depend_on_the_machine(tz):
    script = (
        "from komachi import gmo_archive as g;"
        "rows = g.parse_trades_csv("
        "b'symbol,side,size,price,timestamp\\n"
        "BTC_JPY,BUY,0.001,1.0,2025-06-30 21:00:19.862\\n');"
        "print(repr(rows[0]['ts']))"
    )
    env = {**os.environ, "TZ": tz, "PYTHONPATH": "src"}
    out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, env=env, cwd=os.getcwd())
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "1751317219.862"


def test_a_gmo_day_spans_two_jst_days():
    """The file named for 1 July begins on the evening of 30 June, which is
    why an import re-cuts rows instead of renaming files."""
    rows = gmo_archive.parse_trades_csv(("\n".join([HEADER, *ROWS])).encode())
    days = jst.bucket_by_day(rows)
    assert sorted(days) == ["2025-07-01"]
    # Both rows land in the same JST day despite spanning two UTC dates.
    assert len(days["2025-07-01"]) == 2


def test_fetch_day_returns_none_when_gmo_has_not_published_it():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert gmo_archive.fetch_day("BTC_JPY", "2099-01-01", client) is None


def test_fetch_day_decompresses_and_parses():
    payload = _gz(ROWS)
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=payload)))
    rows = gmo_archive.fetch_day("BTC_JPY", "2025-07-01", client)
    assert len(rows) == 2


def test_a_body_that_is_not_gzip_says_so():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=b"<html>maintenance</html>")))
    with pytest.raises(ImportError_, match="not valid gzip"):
        gmo_archive.fetch_day("BTC_JPY", "2025-07-01", client)


def test_a_server_error_is_raised_rather_than_treated_as_missing():
    """404 means not published; 500 means try again, and the two must not look
    the same or an outage would silently produce an incomplete import."""
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        gmo_archive.fetch_day("BTC_JPY", "2025-07-01", client)


def test_import_range_writes_whole_jst_days(tmp_path):
    def handler(request):
        for d in ("20250630", "20250701"):
            if d in str(request.url):
                return httpx.Response(200, content=_gz(ROWS))
        return httpx.Response(404)

    results = gmo_archive.import_range(
        "BTC_JPY", "2025-07-01", "2025-07-01", tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert [r.file_date for r in results] == ["2025-07-01"]
    assert results[0].path.relative_to(tmp_path).as_posix() == (
        "bronze/dataset=Trade/exchange=GMO/symbol=BTC_JPY/date=2025-07-01/data.parquet")


def test_a_day_missing_its_earlier_source_is_not_written(tmp_path):
    """Half a JST day presented as a whole one is the failure to avoid."""
    def handler(request):
        return httpx.Response(200, content=_gz(ROWS)) if "20250701" in str(request.url) \
            else httpx.Response(404)

    results = gmo_archive.import_range(
        "BTC_JPY", "2025-07-01", "2025-07-01", tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert results == []
