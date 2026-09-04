"""Resume, verification and layout for downloaded files."""

import hashlib

import httpx
import pytest

from komachi.download import download_file, local_path


def _entry(url: str, **overrides) -> dict:
    entry = {
        "dataset_file_id": "file-1",
        "market": "COINCHECK:BTC_SPOT",
        "data_type": "Trade",
        "file_date": "2026-01-01",
        "url": url,
        "size_bytes": None,
        "checksum": None,
    }
    entry.update(overrides)
    return entry


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_layout_matches_the_warehouse_tree(tmp_path):
    path = local_path(tmp_path, "COINCHECK:BTC_SPOT", "Trade", "2026-01-15")
    assert path.relative_to(tmp_path).as_posix() == (
        "bronze/dataset=Trade/exchange=COINCHECK/symbol=BTC_SPOT/date=2026-01-15/data.parquet"
    )


def test_downloads_and_verifies_checksum(tmp_path):
    payload = b"parquet-bytes" * 100
    checksum = hashlib.sha256(payload).hexdigest()
    client = _client(lambda request: httpx.Response(200, content=payload))

    result = download_file(
        _entry("https://s3.test/f", size_bytes=len(payload), checksum=checksum),
        tmp_path,
        client=client,
    )

    assert result.skipped is False
    assert result.verified is True
    assert result.path.read_bytes() == payload


def test_checksum_mismatch_raises_and_leaves_no_file(tmp_path):
    client = _client(lambda request: httpx.Response(200, content=b"wrong"))
    entry = _entry("https://s3.test/f", checksum=hashlib.sha256(b"right").hexdigest())

    with pytest.raises(OSError, match="Checksum mismatch"):
        download_file(entry, tmp_path, client=client)

    assert not local_path(tmp_path, entry["market"], entry["data_type"], entry["file_date"]).exists()


def test_size_mismatch_raises(tmp_path):
    client = _client(lambda request: httpx.Response(200, content=b"short"))
    with pytest.raises(OSError, match="Size mismatch"):
        download_file(_entry("https://s3.test/f", size_bytes=999), tmp_path, client=client)


def test_complete_file_is_skipped(tmp_path):
    payload = b"already-here"
    path = local_path(tmp_path, "COINCHECK:BTC_SPOT", "Trade", "2026-01-01")
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)

    def handler(request):  # pragma: no cover - must not be reached
        raise AssertionError("should not have been fetched")

    result = download_file(
        _entry("https://s3.test/f", size_bytes=len(payload)), tmp_path, client=_client(handler)
    )
    assert result.skipped is True


def test_force_redownloads_an_existing_file(tmp_path):
    path = local_path(tmp_path, "COINCHECK:BTC_SPOT", "Trade", "2026-01-01")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"stale")
    client = _client(lambda request: httpx.Response(200, content=b"fresh"))

    result = download_file(_entry("https://s3.test/f"), tmp_path, client=client, force=True)

    assert result.skipped is False
    assert path.read_bytes() == b"fresh"


def test_partial_file_resumes_from_its_offset(tmp_path):
    payload = b"0123456789" * 10
    path = local_path(tmp_path, "COINCHECK:BTC_SPOT", "Trade", "2026-01-01")
    path.parent.mkdir(parents=True)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_bytes(payload[:40])

    seen = {}

    def handler(request):
        seen["range"] = request.headers.get("Range")
        start = int(request.headers["Range"].split("=")[1].split("-")[0])
        return httpx.Response(206, content=payload[start:])

    result = download_file(
        _entry("https://s3.test/f", size_bytes=len(payload)), tmp_path, client=_client(handler)
    )

    assert seen["range"] == "bytes=40-"
    assert result.path.read_bytes() == payload


def test_server_ignoring_range_restarts_cleanly(tmp_path):
    """A 200 in reply to a Range request means the whole object is coming."""
    payload = b"abcdefghij" * 10
    path = local_path(tmp_path, "COINCHECK:BTC_SPOT", "Trade", "2026-01-01")
    path.parent.mkdir(parents=True)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_bytes(b"garbage")

    client = _client(lambda request: httpx.Response(200, content=payload))
    result = download_file(
        _entry("https://s3.test/f", size_bytes=len(payload)), tmp_path, client=client
    )

    assert result.path.read_bytes() == payload


def test_transient_failure_is_retried(tmp_path):
    payload = b"eventually-fine"
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=payload)

    result = download_file(_entry("https://s3.test/f"), tmp_path, client=_client(handler), retries=3)

    assert attempts["n"] == 2
    assert result.path.read_bytes() == payload


def test_a_rejected_signature_is_not_retried(tmp_path):
    """A 403 will answer the same way however often it is asked, so fail fast."""
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        return httpx.Response(403, content=b"<Error>AccessDenied</Error>")

    with pytest.raises(OSError, match="rejected the signature"):
        download_file(_entry("https://s3.test/f"), tmp_path, client=_client(handler), retries=3)

    assert attempts["n"] == 1


def test_server_error_is_retried(tmp_path):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=b"ok")

    result = download_file(_entry("https://s3.test/f"), tmp_path, client=_client(handler), retries=3)

    assert attempts["n"] == 3
    assert result.path.read_bytes() == b"ok"


def test_a_prefixed_checksum_from_the_catalogue_verifies(tmp_path):
    """Kitakamakura records "sha256:<hex>"; a bare comparison rejects every file."""
    payload = b"parquet-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    client = _client(lambda request: httpx.Response(200, content=payload))

    result = download_file(
        _entry("https://s3.test/f", checksum=f"sha256:{digest}"), tmp_path, client=client
    )
    assert result.verified is True


def test_a_bare_checksum_still_verifies(tmp_path):
    payload = b"parquet-bytes"
    client = _client(lambda request: httpx.Response(200, content=payload))
    result = download_file(
        _entry("https://s3.test/f", checksum=hashlib.sha256(payload).hexdigest()),
        tmp_path, client=client,
    )
    assert result.verified is True


def test_an_unknown_algorithm_is_refused_not_ignored(tmp_path):
    client = _client(lambda request: httpx.Response(200, content=b"x"))
    with pytest.raises(OSError, match="Unsupported checksum algorithm"):
        download_file(_entry("https://s3.test/f", checksum="blake3:abc"), tmp_path, client=client)


# ---- resuming ---------------------------------------------------------------


def test_already_have_recognises_a_complete_file(tmp_path):
    """What a resumed run consults before asking the API for anything."""
    from komachi.download import already_have

    payload = b"parquet-bytes"
    entry = _entry("https://s3.test/f", size_bytes=len(payload),
                   checksum=f"sha256:{hashlib.sha256(payload).hexdigest()}")
    assert already_have(entry, tmp_path) is False

    path = local_path(tmp_path, entry["market"], entry["data_type"], entry["file_date"])
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    assert already_have(entry, tmp_path) is True


def test_a_truncated_file_is_not_treated_as_complete(tmp_path):
    """An interrupted write leaves a short file. Trusting it would give the
    buyer a silently incomplete day."""
    from komachi.download import already_have

    entry = _entry("https://s3.test/f", size_bytes=5_000)
    path = local_path(tmp_path, entry["market"], entry["data_type"], entry["file_date"])
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * 100)

    assert already_have(entry, tmp_path) is False


def test_a_corrupted_file_is_not_treated_as_complete(tmp_path):
    from komachi.download import already_have

    payload = b"right"
    entry = _entry("https://s3.test/f", size_bytes=len(payload),
                   checksum=f"sha256:{hashlib.sha256(payload).hexdigest()}")
    path = local_path(tmp_path, entry["market"], entry["data_type"], entry["file_date"])
    path.parent.mkdir(parents=True)
    path.write_bytes(b"wrong")  # same length, different bytes

    assert already_have(entry, tmp_path) is False


def test_a_file_with_no_published_checksum_is_taken_at_face_value(tmp_path):
    """There is nothing to check against, so an existing file is accepted
    rather than re-fetched forever."""
    from komachi.download import already_have

    entry = _entry("https://s3.test/f")
    path = local_path(tmp_path, entry["market"], entry["data_type"], entry["file_date"])
    path.parent.mkdir(parents=True)
    path.write_bytes(b"anything")

    assert already_have(entry, tmp_path) is True
