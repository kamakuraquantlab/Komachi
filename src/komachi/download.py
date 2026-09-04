"""Fetching files from pre-signed URLs.

doc/04 section 9.2 asks for resume, retry, checksum verification and a
predictable layout. Files land in the same Hive-style tree the parquet
warehouse uses, so downloaded data can be pointed at existing tooling without
rearranging it:

    <dest>/dataset=Trade/exchange=BINANCE/symbol=BTC_USDT/date=2026-01-15/data.parquet
"""

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .layout import data_path

CHUNK_SIZE = 1024 * 1024

# 408 and 429 are the only 4xx worth retrying. The rest will answer the same
# way however many times they are asked. Expiry is not among them: files are
# fetched through the API, which signs at the moment of the request.
_RETRYABLE_STATUSES = frozenset({408, 429})


class DownloadFailed(OSError):
    """A download that failed for a reason worth showing the buyer verbatim."""


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code in _RETRYABLE_STATUSES or code >= 500
    return isinstance(exc, (httpx.TransportError, OSError))


@dataclass
class DownloadResult:
    path: Path
    skipped: bool
    bytes_written: int
    verified: bool


def local_path(dest: Path, market: str, data_type: str, file_date: str) -> Path:
    """Where one file belongs under the root. See `layout` for the tree."""
    return data_path(dest, market, data_type, file_date)


def _parse_checksum(value: str) -> tuple[str, str]:
    """Split "sha256:<hex>" into its algorithm and digest.

    The catalogue records the algorithm alongside the digest so the format can
    outlive sha256. A bare digest is accepted as sha256 for the same reason a
    reader should be lenient about what it accepts.
    """
    if ":" in value:
        algorithm, _, digest = value.partition(":")
        return algorithm.lower(), digest.lower()
    return "sha256", value.lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_complete(path: Path, size_bytes: int | None, checksum: str | None) -> bool:
    """Whether an existing local file already satisfies the catalogue entry.

    Public because a resumed download decides what to ask the API for by
    consulting the disk first. Checking here rather than after a URL has been
    issued is what makes resuming free: a file already present is never
    requested, so it never opens a market-day.
    """
    if not path.exists():
        return False
    if size_bytes is not None and path.stat().st_size != size_bytes:
        return False
    if checksum:
        algorithm, digest = _parse_checksum(checksum)
        if algorithm != "sha256" or _sha256(path) != digest:
            return False
    # With neither size nor checksum published there is nothing to check
    # against, so any existing file is taken at face value.
    return True


def _describe(exc: Exception) -> str:
    """One line a buyer can act on, without httpx's documentation links."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 403:
            return ("403 Forbidden -- object storage rejected the signature. "
                    "Re-run the command; if it persists, contact support")
        if code == 404:
            return "404 Not Found -- the file is not in object storage; contact support"
        return f"HTTP {code} from object storage"
    return f"{type(exc).__name__}: {exc}"


def already_have(entry: dict, dest: Path) -> bool:
    """Whether this catalogue entry is satisfied on disk."""
    path = local_path(dest, entry["market"], entry["data_type"], entry["file_date"])
    return is_complete(path, entry.get("size_bytes"), entry.get("checksum"))


def download_file(
    entry: dict,
    dest: Path,
    *,
    client: httpx.Client | None = None,
    retries: int = 3,
    force: bool = False,
) -> DownloadResult:
    """Download one manifest entry, resuming a partial file where possible."""
    path = local_path(dest, entry["market"], entry["data_type"], entry["file_date"])
    size_bytes = entry.get("size_bytes")
    checksum = entry.get("checksum")

    if not force and is_complete(path, size_bytes, checksum):
        return DownloadResult(path=path, skipped=True, bytes_written=0, verified=bool(checksum))

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    owns_client = client is None
    client = client or httpx.Client(timeout=120.0, follow_redirects=True)

    try:
        last_error: Exception | None = None
        for attempt in range(retries):
            resume_from = partial.stat().st_size if partial.exists() else 0
            headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
            try:
                with client.stream("GET", entry["url"], headers=headers) as response:
                    # A server that ignores the Range header replies 200 and
                    # sends the whole object; restart rather than append to it.
                    if resume_from and response.status_code == 200:
                        resume_from = 0
                    elif response.status_code not in (200, 206):
                        response.raise_for_status()

                    mode = "ab" if resume_from else "wb"
                    with partial.open(mode) as handle:
                        for chunk in response.iter_bytes(CHUNK_SIZE):
                            handle.write(chunk)
                break
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                if not _is_retryable(exc):
                    raise DownloadFailed(_describe(exc)) from exc
                if attempt == retries - 1:
                    raise DownloadFailed(_describe(exc)) from exc
                time.sleep(2**attempt)
        else:  # pragma: no cover - loop always breaks or raises
            raise last_error

        written = partial.stat().st_size
        if size_bytes is not None and written != size_bytes:
            raise DownloadFailed(
                f"Size mismatch for {path.name}: expected {size_bytes} bytes, got {written}"
            )

        verified = False
        if checksum:
            algorithm, digest = _parse_checksum(checksum)
            if algorithm != "sha256":
                partial.unlink(missing_ok=True)
                raise DownloadFailed(
                    f"Unsupported checksum algorithm {algorithm!r} for {path.name}. "
                    "This client verifies sha256 only; upgrade it."
                )
            actual = _sha256(partial)
            if actual != digest:
                partial.unlink(missing_ok=True)
                raise DownloadFailed(
                    f"Checksum mismatch for {path.name}: expected {digest}, got {actual}"
                )
            verified = True

        partial.replace(path)
        return DownloadResult(path=path, skipped=False, bytes_written=written, verified=verified)
    finally:
        if owns_client:
            client.close()
