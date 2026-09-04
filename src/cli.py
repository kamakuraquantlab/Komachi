"""Kamakura Quant Lab buyer CLI.

Run as: python src/cli.py <command> [options]

Auth resolves in the order doc/01 section 4.3 gives: --token, then
KQL_TOKEN, then the config file written by `auth login`.
"""

import argparse
import os
import sys
from pathlib import Path

import httpx

from komachi.client import DEFAULT_API_URL, ApiError, Credentials, KomachiClient
from komachi.download import download_file
from komachi.duck import DuckDBUnavailable, build_database, missing_datasets
from komachi.layout import DEFAULT_ROOT, local_inventory, root_path, view_sql


def _resolve_credentials(args) -> Credentials:
    api_url = args.api_url or os.environ.get("KQL_API_URL")
    token = args.token or os.environ.get("KQL_TOKEN")

    if not token or not api_url:
        stored = Credentials.load()
        if stored:
            token = token or stored.token
            api_url = api_url or stored.api_url

    if not token:
        raise SystemExit(
            "No token found. Pass --token, set KQL_TOKEN, or run:\n  komachi auth login --token <TOKEN>"
        )
    return Credentials(api_url=api_url or DEFAULT_API_URL, token=token)


def _client(args) -> KomachiClient:
    creds = _resolve_credentials(args)
    return KomachiClient(creds.api_url, creds.token)


def _human_bytes(n: int | None) -> str:
    if not n:
        return "-"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def cmd_auth_login(args) -> int:
    api_url = args.api_url or os.environ.get("KQL_API_URL") or DEFAULT_API_URL
    creds = Credentials(api_url=api_url, token=args.token)
    with KomachiClient(creds.api_url, creds.token) as client:
        state = client.status()
    creds.save()
    print(f"Logged in. Product {state['product_id']}, valid until {state['valid_until']}.")
    return 0


def cmd_status(args) -> int:
    with _client(args) as client:
        state = client.status()
    markets = ", ".join(state["markets"]) if state["markets"] else "none registered"
    print(f"Product        {state['product_id']}")
    print(f"Token status   {state['token_status']}")
    print(f"Valid until    {state['valid_until']}")
    print(f"Markets        {markets}{' (all markets)' if state['all_markets'] else ''}")
    if state["start_date"] or state["end_date"]:
        print(f"Date window    {state['start_date'] or 'any'} .. {state['end_date'] or 'any'}")
    print(f"Market-days    {state['used_market_days']} used, {state['remaining_market_days']} remaining"
          f" of {state['granted_market_days']}")
    return 0


def cmd_markets(args) -> int:
    with _client(args) as client:
        result = client.markets()
    for market in result["markets"]:
        print(market)

    # A buyer looking for Binance should be told where it is, not left to
    # conclude it is missing.
    for source in result.get("external_sources", []):
        print(f"\n{source['exchange']}: not sold by Kamakura Quant Lab -- available free from {source['name']}")
        print(f"  {source['reason']}")
        print(f"  Source:   {source['url']}")
        print(f"  Importer: {source['importer_command']}")
    return 0


def cmd_binance_import(args) -> int:
    """Download from Binance Vision and convert into the Kamakura Quant Lab schema."""
    from komachi import binance_vision

    dest = root_path(args.root)
    try:
        dates = binance_vision.date_range(args.start, args.end)
    except ValueError as exc:
        raise SystemExit(str(exc))

    print(f"Importing {len(dates)} day(s) of {args.symbol} trades from Binance Vision.")
    print("Downloading directly from Binance; Kamakura Quant Lab is not involved in this transfer.\n")

    failures = 0
    with httpx.Client(timeout=120.0, follow_redirects=True) as http:
        for index, file_date in enumerate(dates, start=1):
            label = f"[{index}/{len(dates)}] {file_date}"
            try:
                outcome = binance_vision.import_day(
                    args.symbol, file_date, dest, client=http, force=args.force
                )
            except Exception as exc:
                failures += 1
                print(f"{label} FAILED: {exc}", file=sys.stderr)
                continue
            if outcome.skipped:
                print(f"{label} already present, skipped")
            else:
                print(f"{label} {outcome.rows:,} trades -> {outcome.path}")

    print(f"\n{len(dates) - failures}/{len(dates)} day(s) imported into {dest}")
    if failures == 0:
        print("Layout matches your Kamakura Quant Lab data, so both load through the same reader.")
    print("\nNote: Binance Vision publishes spot trades but not L2 order book depth,")
    print("so only the Trade dataset can be produced from this source.")
    return 1 if failures else 0


def cmd_calendar(args) -> int:
    with _client(args) as client:
        days = client.calendar(args.market)
    if not days:
        print(f"No data registered for {args.market}.")
        return 0
    print(f"{'date':12} {'state':12} data types")
    for day in days:
        if day["consumed"]:
            state = "downloaded"
        elif day["available"]:
            state = "available"
        else:
            state = "unavailable"
        print(f"{day['file_date']:12} {state:12} {', '.join(day['data_types']) or '-'}")
    consumed = sum(1 for d in days if d["consumed"])
    available = sum(1 for d in days if d["available"])
    print(f"\n{available} available, {consumed} already downloaded.")
    return 0


def cmd_manifest(args) -> int:
    with _client(args) as client:
        if args.dry_run:
            estimate = client.manifest(args.market, args.start, args.end, dry_run=True)
            print(f"{estimate['files']} file(s) across {estimate['new_market_days']} new market-day(s).")
            print(f"Remaining after this request: "
                  f"{estimate['remaining_market_days'] - estimate['new_market_days']}")
            if not estimate["sufficient"]:
                print("Not enough market-days remain for this range.", file=sys.stderr)
                return 1
            return 0
        result = client.manifest(args.market, args.start, args.end)
    for entry in result["files"]:
        print(entry["url"] if args.urls_only else
              f"{entry['file_date']} {entry['data_type']:10} {_human_bytes(entry['size_bytes']):>8}"
              f"  {entry['url']}")
    return 0


def _confirm(estimate: dict) -> bool:
    print(f"This will consume {estimate['new_market_days']} market-day(s) of "
          f"{estimate['remaining_market_days']} remaining, across {estimate['files']} file(s).")
    return input("Continue? [y/N] ").strip().lower() in ("y", "yes")


def cmd_download(args) -> int:
    dest = root_path(args.root)
    with _client(args) as client:
        estimate = client.manifest(args.market, args.start, args.end, dry_run=True)
        if estimate["files"] == 0:
            print(f"No files available for {args.market} between {args.start} and {args.end}.")
            return 0
        if not estimate["sufficient"]:
            print(
                f"Not enough grant remaining: need {estimate['new_market_days']} market-day(s), "
                f"have {estimate['remaining_market_days']}.",
                file=sys.stderr,
            )
            return 1
        if not args.yes and estimate["new_market_days"] > 0 and not _confirm(estimate):
            print("Cancelled.")
            return 0

        result = client.manifest(args.market, args.start, args.end)

    entries = result["files"]
    failures = 0
    with httpx.Client(timeout=120.0, follow_redirects=True) as http:
        for index, entry in enumerate(entries, start=1):
            label = f"[{index}/{len(entries)}] {entry['file_date']} {entry['data_type']}"
            try:
                outcome = download_file(entry, dest, client=http, force=args.force)
            except Exception as exc:
                failures += 1
                print(f"{label} FAILED: {exc}", file=sys.stderr)
                print(f"    retry with: komachi refresh --file {entry['dataset_file_id']}", file=sys.stderr)
                continue
            if outcome.skipped:
                print(f"{label} already present, skipped")
            else:
                verified = " verified" if outcome.verified else ""
                print(f"{label} {_human_bytes(outcome.bytes_written)}{verified} -> {outcome.path}")

    print(f"\n{len(entries) - failures}/{len(entries)} file(s) downloaded into {dest}")
    if failures == 0:
        print("Query it with:  komachi duckdb")
    return 1 if failures else 0


def cmd_refresh(args) -> int:
    with _client(args) as client:
        entry = client.refresh(args.file)
    print(f"{entry['market']} {entry['file_date']} {entry['data_type']}")
    print(f"Refresh {entry['refresh_count']}/{entry['max_refresh_count']}, expires {entry['expires_at']}")
    print(entry["url"])
    return 0


def cmd_local(args) -> int:
    """What is already on disk, without calling the API."""
    root = root_path(args.root)
    inventory = local_inventory(root)
    if not inventory:
        print(f"Nothing downloaded under {root} yet.")
        return 0
    print(f"{root}\n")
    print(f"{'market':24} {'dataset':10} {'days':>5}  range")
    for (market, data_type), dates in sorted(inventory.items()):
        print(f"{market:24} {data_type:10} {len(dates):>5}  {dates[0]} .. {dates[-1]}")
    return 0


def cmd_duckdb(args) -> int:
    """Create or refresh a DuckDB database of views over the downloaded tree."""
    root = root_path(args.root)
    db_path = Path(args.db).expanduser() if args.db else root / "kql.duckdb"
    try:
        counts = build_database(root, db_path)
    except DuckDBUnavailable as exc:
        raise SystemExit(str(exc))

    if not counts:
        print(f"Nothing downloaded under {root} yet, so no views were created.")
        print("Run a download first:  komachi download --market MARKET --start DATE --end DATE")
        return 0

    print(f"Database  {db_path}")
    for view, rows in counts.items():
        print(f"  view {view:10} {rows:>15,} rows")
    for absent in missing_datasets(root):
        print(f"  ({absent} has no files yet, so no view was created)")
    print(f"\nOpen it with:  duckdb {db_path}")
    print("Then:          SELECT * FROM trade LIMIT 5;")
    print("\nExchange, symbol and date are columns recovered from the paths,")
    print("so you can filter on them without any extra bookkeeping:")
    print("  SELECT * FROM trade WHERE exchange = 'GMO' AND date = '2026-01-15';")
    return 0


def cmd_sql(args) -> int:
    """Print the view SQL, for use in an existing DuckDB session."""
    print(view_sql(root_path(args.root)))
    return 0


def _load_parquet(path: Path):
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit("pyarrow is required for this command. Install with: pip install 'komachi[data]'")
    return pq.read_table(path)


def cmd_stats(args) -> int:
    path = Path(args.path).expanduser()
    if not path.exists():
        raise SystemExit(f"No such file: {path}")
    table = _load_parquet(path)
    print(f"File      {path}")
    print(f"Rows      {table.num_rows:,}")
    print(f"Columns   {table.num_columns}")
    print(f"Size      {_human_bytes(path.stat().st_size)}")
    if "ts" in table.column_names and table.num_rows:
        from datetime import datetime, timezone

        timestamps = table.column("ts")
        first = datetime.fromtimestamp(timestamps[0].as_py(), tz=timezone.utc)
        last = datetime.fromtimestamp(timestamps[-1].as_py(), tz=timezone.utc)
        print(f"Time      {first.isoformat()} .. {last.isoformat()}")
        span = (last - first).total_seconds()
        if span > 0:
            print(f"Rate      {table.num_rows / span:.1f} rows/sec")
    return 0


def cmd_decode(args) -> int:
    path = Path(args.path).expanduser()
    if not path.exists():
        raise SystemExit(f"No such file: {path}")
    table = _load_parquet(path)
    print("Schema:")
    for field in table.schema:
        print(f"  {field.name:20} {field.type}")
    print(f"\nFirst {args.rows} row(s):")
    print(table.slice(0, args.rows).to_pandas().to_string())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="komachi", description="Kamakura Quant Lab market data downloader")
    parser.add_argument("--token", help="Purchase token; overrides KQL_TOKEN and stored config")
    parser.add_argument("--api-url", help="Kamakura Quant Lab API base URL")
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("auth", help="Manage stored credentials")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    p = auth_sub.add_parser("login", help="Verify a token and store it locally")
    p.add_argument("--token", required=True)
    p.set_defaults(func=cmd_auth_login)

    sub.add_parser("status", help="Show grant, usage and expiry").set_defaults(func=cmd_status)
    sub.add_parser(
        "markets", help="List markets available to this token, and external sources"
    ).set_defaults(func=cmd_markets)

    p = sub.add_parser(
        "binance-import",
        help="Download Binance history from Binance Vision and convert it to the Kamakura Quant Lab schema",
    )
    p.add_argument("--symbol", required=True, help="Kamakura Quant Lab symbol, for example BTC_USDT")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--root", help=f"Data root. Defaults to $ROOT_PATH, else {DEFAULT_ROOT}")
    p.add_argument("--force", action="store_true", help="Re-import days already present")
    p.set_defaults(func=cmd_binance_import)

    p = sub.add_parser("calendar", help="Show available and downloaded dates for a market")
    p.add_argument("--market", required=True)
    p.set_defaults(func=cmd_calendar)

    p = sub.add_parser("manifest", help="Generate temporary URLs for a date range")
    p.add_argument("--market", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--dry-run", action="store_true", help="Report cost without consuming the grant")
    p.add_argument("--urls-only", action="store_true", help="Print bare URLs, for wget or aria2c")
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("download", help="Download a date range for one market")
    p.add_argument("--market", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--root", help=f"Data root. Defaults to $ROOT_PATH, else {DEFAULT_ROOT}")
    p.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    p.add_argument("--force", action="store_true", help="Re-download files already present")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("refresh", help="Re-sign a file whose URL expired or failed")
    p.add_argument("--file", required=True, help="dataset_file_id from a manifest or error message")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("local", help="Show what is already downloaded")
    p.add_argument("--root", help=f"Data root. Defaults to $ROOT_PATH, else {DEFAULT_ROOT}")
    p.set_defaults(func=cmd_local)

    p = sub.add_parser("duckdb", help="Create or refresh a DuckDB database over the downloaded tree")
    p.add_argument("--root", help=f"Data root. Defaults to $ROOT_PATH, else {DEFAULT_ROOT}")
    p.add_argument("--db", help="Database file. Defaults to <root>/kql.duckdb")
    p.set_defaults(func=cmd_duckdb)

    p = sub.add_parser("sql", help="Print DuckDB view SQL for the downloaded tree")
    p.add_argument("--root", help=f"Data root. Defaults to $ROOT_PATH, else {DEFAULT_ROOT}")
    p.set_defaults(func=cmd_sql)

    p = sub.add_parser("stats", help="Row count and time range for a local file")
    p.add_argument("--path", required=True)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("decode", help="Schema and first rows of a local file")
    p.add_argument("--path", required=True)
    p.add_argument("--rows", type=int, default=5)
    p.set_defaults(func=cmd_decode)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ApiError as exc:
        print(f"API error {exc.status_code}: {exc.detail}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"Could not reach the Kamakura Quant Lab API: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
