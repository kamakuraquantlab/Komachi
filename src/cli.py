"""Kamakura Quant Lab buyer CLI.

Run as: python src/cli.py <command> [options]

Auth resolves in the order doc/01 section 4.3 gives: --token, then
KQL_TOKEN, then the config file written by `auth login`.
"""

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

from komachi.client import ApiError, KomachiClient
from komachi.download import already_have, download_file
from komachi import jst
from komachi.duck import DuckDBUnavailable, build_database, missing_datasets
from komachi.layout import data_path, local_inventory, view_sql
from komachi.settings import DEFAULT_ROOT, ENV_FILE, TOKEN_FILE, resolve, save_token
from komachi.weeks import describe, shapes


def _settings(args):
    return resolve(getattr(args, "root", None), args.api_url, args.token)


def _client(args) -> KomachiClient:
    s = _settings(args)
    if not s.token:
        raise SystemExit(
            "No token found. Pass --token, set KQL_TOKEN, or run:\n"
            "  komachi auth login --token <TOKEN>"
        )
    return KomachiClient(s.api_url, s.token)


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
    # Resolving here rather than after the call, so a first-time user is asked
    # for their data root once, at the moment they set the tool up.
    s = resolve(getattr(args, "root", None), args.api_url, args.token)
    with KomachiClient(s.api_url, args.token) as client:
        state = client.status()
    save_token(args.token)
    print(f"Logged in. Product {state['product_id']}, valid until {state['valid_until']}.")
    print(f"Token stored in {TOKEN_FILE} (0600). Data root is {s.root}.")
    return 0


def _in_weeks(market_days: int) -> str:
    """The storefront phrasing, when it says something the day count does not."""
    text = describe(market_days)
    return "" if text.endswith("market-days") or text == "none" else f"  ({text})"


def cmd_status(args) -> int:
    with _client(args) as client:
        state = client.status()
    granted, remaining = state["granted_market_days"], state["remaining_market_days"]
    print(f"Product        {state['product_id']}")
    print(f"Token status   {state['token_status']}")
    print(f"Valid until    {state['valid_until']}")
    print(f"Allowance      {granted} market-days{_in_weeks(granted)}")
    print(f"Remaining      {remaining} market-days{_in_weeks(remaining)}")
    if state["start_date"] or state["end_date"]:
        print(f"Date window    {state['start_date'] or 'any'} .. {state['end_date'] or 'any'}")

    for i, option in enumerate(shapes(remaining, markets=max(len(state["markets"]), 1))):
        print(f"{'Spend it as' if i == 0 else '':<15}{option}")

    print(f"\nMarkets        {', '.join(state['markets']) or 'none catalogued'}")
    print("\nA market-day is one market on one date, covering every dataset published for it.")
    print("The allowance is not tied to a market: spend it wherever you like.")
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


def _run_import(args, source: str, importer, note: str) -> int:
    """Shared shape for the free-source importers.

    Both fetch a foreign archive and re-cut it onto JST days, so the only
    thing that differs is where the bytes come from and what the source
    publishes.
    """
    dest = _settings(args).root
    try:
        dates = jst.date_range(args.start, args.end)
    except ValueError as exc:
        raise SystemExit(str(exc))

    print(f"Importing {len(dates)} JST day(s) of {args.symbol} trades from {source}.")
    print(f"Downloading directly from {source}; Kamakura Quant Lab is not involved "
          f"in this transfer.")
    print("Source days are re-cut onto Asia/Tokyo days, so each day needs the archive")
    print("before it as well; a day missing either source is not written.\n")

    try:
        results = importer(args.symbol, args.start, args.end, dest, force=args.force)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    written = [r for r in results if not r.skipped]
    skipped = [r for r in results if r.skipped]
    for r in sorted(results, key=lambda r: r.file_date):
        if r.skipped:
            print(f"{r.file_date} already present, skipped")
        else:
            print(f"{r.file_date} {r.rows:,} trades -> {r.path}")

    incomplete = [d for d in dates if d not in {r.file_date for r in results}]
    print(f"\n{len(written)} day(s) imported into {dest}"
          + (f", {len(skipped)} already present" if skipped else ""))
    if incomplete:
        print(f"{len(incomplete)} day(s) not written for want of a source archive: "
              f"{', '.join(incomplete[:5])}{' ...' if len(incomplete) > 5 else ''}")
    if written:
        print("Layout matches your Kamakura Quant Lab data, so both load through the same reader.")
    print(f"\n{note}")
    return 0


def cmd_binance_import(args) -> int:
    """Download from Binance Vision and convert into the Kamakura Quant Lab schema."""
    from komachi import binance_vision

    return _run_import(
        args, "Binance Vision", binance_vision.import_range,
        "Note: Binance Vision publishes spot trades but not L2 order book depth,\n"
        "so only the Trade dataset can be produced from this source.",
    )


def cmd_gmo_import(args) -> int:
    """Download GMO's published trade history and convert it."""
    from komachi import gmo_archive

    return _run_import(
        args, "GMO", gmo_archive.import_range,
        "Note: GMO publishes trades but not order book depth, so only the Trade\n"
        "dataset comes from this source. Order book for the delivered GMO markets\n"
        "is what a purchased market-day carries.",
    )


def _read_local(args, data_type: str):
    """One local file, addressed the way a buyer thinks about it.

    `stats` and `decode` take a path, which assumes the reader already knows
    the layout. These take a market and a date, which is what someone has
    after buying a market-day.
    """
    root = _settings(args).root
    path = data_path(root, args.market, data_type, args.date)
    if not path.exists():
        raise SystemExit(
            f"No {data_type} for {args.market} on {args.date} under {root}.\n"
            f"Run:  komachi download --market {args.market} --start {args.date} --days 1"
        )
    return _load_parquet(path), path


def cmd_trades(args) -> int:
    """Print trades for one market-day."""
    table, path = _read_local(args, "Trade")
    rows = table.to_pylist()
    print(f"{args.market}  {args.date}  Trade  {len(rows):,} trades  {path}")
    print(f"\n{'time (JST)':<14}{'side':<6}{'price':>16}{'size':>16}")
    shown = rows[-args.rows:] if args.tail else rows[:args.rows]
    for r in shown:
        side = "sell" if r["side"] else "buy"
        print(f"{_jst_clock(r['ts']):<14}{side:<6}{r['price']:>16,.4f}{r['size']:>16,.8f}")
    if len(rows) > args.rows:
        where = "first" if not args.tail else "last"
        print(f"\n{where} {args.rows} of {len(rows):,}. Use --rows N, or --tail for the end of the day.")
    return 0


def cmd_book(args) -> int:
    """Print best bid and ask for one market-day."""
    table, path = _read_local(args, "OrderBook")
    names = table.column_names
    # The warehouse names these bid0_price / ask0_price; Hase reads the same
    # pair. Level 0 is the top of book, which is all this command shows.
    bid = "bid0_price" if "bid0_price" in names else None
    ask = "ask0_price" if "ask0_price" in names else None
    rows = (table.select(["ts", bid, ask]).to_pylist() if bid and ask
            else table.select(["ts"]).to_pylist())
    print(f"{args.market}  {args.date}  OrderBook  {len(rows):,} snapshots  {path}")
    if not (bid and ask):
        print(f"\nColumns: {', '.join(names[:12])}{' ...' if len(names) > 12 else ''}")
        print("No best bid/ask column recognised; use 'komachi decode --path' for the raw schema.")
        return 0
    print(f"\n{'time (JST)':<14}{'best bid':>16}{'best ask':>16}{'spread':>12}")
    shown = rows[-args.rows:] if args.tail else rows[:args.rows]
    for r in shown:
        b, a = r[bid], r[ask]
        clock = _jst_clock(r["ts"])
        if b is None or a is None:
            print(f"{clock:<14}{'—':>16}{'—':>16}{'—':>12}")
            continue
        print(f"{clock:<14}{b:>16,.4f}{a:>16,.4f}{a - b:>12,.4f}")
    if len(rows) > args.rows:
        where = "first" if not args.tail else "last"
        print(f"\n{where} {args.rows} of {len(rows):,}. Use --rows N, or --tail for the end of the day.")
    return 0


def _jst_clock(ts: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts, jst.TOKYO).strftime("%H:%M:%S.%f")[:12]


def cmd_catalog(args) -> int:
    """What the seller holds for a market, with per-day quality.

    Defaults to the most recent week rather than the whole archive: the common
    question is "what is there now", and a market-year is 730 lines.
    """
    with _client(args) as client:
        if args.start or args.end:
            files = client.stats(args.market, start=args.start, end=args.end)
            scope = f"{args.start or 'earliest'} .. {args.end or 'latest'}"
        else:
            files = client.stats(args.market, days=args.days)
            scope = f"latest {args.days} day(s)"

    if not files:
        print(f"Nothing catalogued for {args.market} in {scope}.")
        return 0

    # One row per market-day, with the datasets folded in: a market-day is the
    # unit a buyer spends, so it is the unit worth showing.
    days: dict[str, dict] = {}
    for f in files:
        d = days.setdefault(f["file_date"], {"date": f["file_date"], "types": [], "bytes": 0,
                                             "rows": 0, "missing": 0, "partial": False})
        d["types"].append(f["data_type"])
        d["bytes"] += f["size_bytes"] or 0
        d["rows"] += f["row_count"] or 0
        d["missing"] = max(d["missing"], f["missing_minutes"] or 0)
        d["partial"] = d["partial"] or bool(f["partial"])

    print(f"{args.market}   {scope}\n")
    print(f"{'date':12} {'datasets':20} {'rows':>12} {'size':>9} {'gap':>6}  note")
    for d in sorted(days.values(), key=lambda x: x["date"]):
        note = "PARTIAL" if d["partial"] else ("" if d["missing"] < 60 else "sparse")
        gap = f"{d['missing']}m" if d["missing"] else "-"
        print(f"{d['date']:12} {','.join(sorted(d['types'])):20} {d['rows']:>12,} "
              f"{_human_bytes(d["bytes"]):>9} {gap:>6}  {note}")
    print(f"\n{len(days)} market-day(s). 'gap' is minutes with no record in the JST day.")
    return 0


def cmd_calendar(args) -> int:
    """Every catalogued day for a market, and where each one stands.

    Four states, and keeping them apart matters. "Owned" and "on disk" were
    previously one label called "downloaded", which is wrong in both
    directions: a market-day is paid for when its first URL is issued, whether
    or not the bytes ever arrived, and a buyer who deletes a file still owns
    the day and can fetch it again for nothing.
    """
    root = _settings(args).root
    with _client(args) as client:
        days = client.calendar(args.market)
    if not days:
        print(f"Nothing catalogued for {args.market}.")
        return 0

    counts = {"on disk": 0, "owned": 0, "available": 0, "-": 0}
    print(f"{'date':12} {'state':11} {'quality':10} datasets")
    for day in days:
        if not day["available"]:
            state = "-"
        elif not day["consumed"]:
            state = "available"
        elif all(
            data_path(root, args.market, dt, day["file_date"]).is_file()
            for dt in day["data_types"]
        ):
            state = "on disk"
        else:
            state = "owned"
        counts[state] += 1

        gap = day.get("missing_minutes") or 0
        quality = "PARTIAL" if day.get("partial") else (f"{gap}m gap" if gap >= 60 else "")
        print(f"{day['file_date']:12} {state:11} {quality:10} {', '.join(day['data_types']) or '-'}")

    print(f"\n{counts['on disk']} on disk, {counts['owned']} owned but not fetched, "
          f"{counts['available']} available to unlock, {counts['-']} not published.")
    if counts["available"]:
        print(f"Unlocking all {counts['available']} would cost {counts['available']} market-day(s).")
    if counts["owned"]:
        print(f"The {counts['owned']} owned day(s) are already paid for: fetching them costs nothing.")
    return 0


def cmd_manifest(args) -> int:
    start = args.start
    end = (date.fromisoformat(start) + timedelta(days=args.days - 1)).isoformat()
    with _client(args) as client:
        if args.dry_run:
            estimate = client.manifest(args.market, start, end, dry_run=True)
            print(f"{estimate['files']} file(s) across {estimate['new_market_days']} new market-day(s).")
            print(f"Remaining after this request: "
                  f"{estimate['remaining_market_days'] - estimate['new_market_days']}")
            return 0
        result = client.manifest(args.market, start, end)
    for entry in result["files"]:
        print(entry["url"] if args.urls_only else
              f"{entry['file_date']} {entry['data_type']:10} {_human_bytes(entry['size_bytes']):>8}"
              f"  {entry['url']}")
    return 0


def _show_plan(market, start, end, catalogued, pending, estimate, remaining) -> None:
    """What the run will do, before it does any of it.

    Everything here comes from the catalogue, so it is known without issuing a
    URL or spending anything. Whether the allowance actually covers it is the
    service's decision, not this one's: it refuses per file, and refusing here
    too would only be a second opinion that can be wrong.
    """
    days = len({e["file_date"] for e in catalogued})
    have = len(catalogued) - len(pending)
    spend = estimate["new_market_days"]

    print(f"Market      {market}")
    print(f"Dates       {start} .. {end}   ({days} day{'s' if days != 1 else ''}, JST)")
    print(f"Files       {len(pending)} to download"
          + (f", {have} already present" if have else "")
          + f", {_human_bytes(sum(e['size_bytes'] or 0 for e in pending))}")
    print(f"Cost        {spend} of {remaining} remaining market-day(s)")


def cmd_download(args) -> int:
    """Download from a start date, continuing wherever a previous run stopped.

    Two things make an interrupted run resumable rather than restartable.

    The disk is consulted before the API. `stats` lists what exists with sizes
    and checksums, and costs nothing, so a file already complete is dropped
    from the plan and never has a URL issued for it. That is the one rule this
    side has to keep: a re-run cannot spend a market-day that was already paid
    for. Everything else about entitlement is the service's to decide.

    Files are fetched through the API rather than from a pre-signed URL held
    on this side. The old flow asked for the whole range up front, which is
    fine for a week and wrong for a hundred days: a signature lives an hour,
    and 3.5 GB over a domestic link does not finish in one, so the tail of the
    manifest expired before it was ever used. Asking the API per file moves
    signing to the moment of use, where it cannot go stale.
    """
    dest = _settings(args).root

    with _client(args) as client:
        remaining = client.status()["remaining_market_days"]

        # stats reads the catalogue: it issues no URL and spends nothing.
        catalogued, start, end = _plan(client, args, remaining)
        if not catalogued:
            print(f"Nothing catalogued for {args.market} from {args.start}.")
            return 0

        pending = [e for e in catalogued if args.force or not already_have(e, dest)]
        if not pending:
            print(f"All {len(catalogued)} file(s) for {start}..{end} are present. Nothing to do.")
            return 0

        estimate = client.manifest(args.market, start, end, dry_run=True)
        _show_plan(args.market, start, end, catalogued, pending, estimate, remaining)
        if not args.yes and input("\nContinue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 0
        print()

        failures = []
        # httpx drops Authorization when a redirect crosses origins, so the
        # bearer token reaches the API and never object storage.
        with httpx.Client(timeout=120.0, follow_redirects=True,
                          headers=client.auth_header()) as http:
            for index, item in enumerate(pending, start=1):
                label = f"[{index}/{len(pending)}] {item['file_date']} {item['data_type']}"
                try:
                    entry = dict(item, url=client.download_link(
                        args.market, item["file_date"], item["data_type"]))
                    outcome = download_file(entry, dest, client=http, force=args.force)
                except Exception as exc:
                    failures.append(item)
                    print(f"{label} FAILED: {exc}", file=sys.stderr)
                    continue
                verified = " verified" if outcome.verified else ""
                print(f"{label} {_human_bytes(outcome.bytes_written)}{verified}")

    done = len(pending) - len(failures)
    print(f"\n{done}/{len(pending)} file(s) downloaded into {dest}")
    if failures:
        print(f"{len(failures)} failed. Re-run the same command to continue; what "
              f"succeeded is kept and will not be paid for again.", file=sys.stderr)
        return 1
    print("Query it with:  komachi duckdb")
    return 0


def cmd_local(args) -> int:
    """What is already on disk, without calling the API."""
    root = _settings(args).root
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
    root = _settings(args).root
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
    print(view_sql(_settings(args).root))
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


def _plan(client, args, remaining: int) -> tuple[list[dict], str, str]:
    """What the run covers, and over which dates.

    Without `--days` it spans as many days as the remaining allowance could pay
    for. The range is then reported as the dates the catalogue actually holds,
    so the summary does not overstate a span that runs across a gap.
    """
    span = args.days or remaining
    last = (date.fromisoformat(args.start) + timedelta(days=max(span, 1) - 1)).isoformat()
    catalogued = client.stats(args.market, start=args.start, end=last)
    if not catalogued:
        return [], args.start, last
    dates = sorted({e["file_date"] for e in catalogued})
    return catalogued, dates[0], dates[-1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="komachi",
        description="Kamakura Quant Lab market data downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
settings
  Downloaded data goes under one root directory. On first use Komachi asks for
  it and writes the answer to {ENV_FILE} in the current directory:

      KQL_ROOT_PATH=<your data root>     default {DEFAULT_ROOT}
      KQL_API_URL=<api address>

  Edit that file to change either, or override per run with --root and
  --api-url, or by setting ROOT_PATH or KQL_ROOT_PATH in the environment.

  Your purchase token is kept separately in {TOKEN_FILE} at mode 0600, not in
  {ENV_FILE}, so a data directory can be committed to git without leaking it.

layout
  <root>/bronze/dataset=Trade/exchange=GMO/symbol=BTC_JPY/date=2026-01-15/data.parquet

  Dates are Asia/Tokyo days; timestamps inside the files are UTC epochs.
  Run 'komachi duckdb' after downloading to query it.

downloading
  komachi download --market MARKET --start YYYY-MM-DD [--days N]

  Needs a market and a start date. Without --days it takes as many days as the
  remaining allowance covers. It shows the range, size and cost before
  fetching anything, and re-running continues an interrupted run for free.
""")
    parser.add_argument("--token", help="Purchase token; overrides KQL_TOKEN and stored config")
    parser.add_argument("--api-url", help="Kamakura Quant Lab API base URL")
    parser.add_argument("--root", help=f"Data root; overrides {ENV_FILE}. Default {DEFAULT_ROOT}")
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
    p.add_argument("--force", action="store_true", help="Re-import days already present")
    p.set_defaults(func=cmd_binance_import)

    p = sub.add_parser(
        "gmo-import",
        help="Download GMO's published trade history and convert it to the Kamakura Quant Lab schema",
    )
    p.add_argument("--symbol", required=True, help="GMO symbol, for example BTC_JPY")
    p.add_argument("--start", required=True, help="First JST date, inclusive")
    p.add_argument("--end", required=True, help="Last JST date, inclusive")
    p.add_argument("--force", action="store_true", help="Re-import days already present")
    p.set_defaults(func=cmd_gmo_import)

    p = sub.add_parser("trades", help="Print trades for one market-day")
    p.add_argument("--market", required=True, help="EXCHANGE:SYMBOL")
    p.add_argument("--date", required=True, help="JST date, YYYY-MM-DD")
    p.add_argument("--rows", type=int, default=20)
    p.add_argument("--tail", action="store_true", help="Show the end of the day instead of the start")
    p.set_defaults(func=cmd_trades)

    p = sub.add_parser("book", help="Print best bid and ask for one market-day")
    p.add_argument("--market", required=True, help="EXCHANGE:SYMBOL")
    p.add_argument("--date", required=True, help="JST date, YYYY-MM-DD")
    p.add_argument("--rows", type=int, default=20)
    p.add_argument("--tail", action="store_true", help="Show the end of the day instead of the start")
    p.set_defaults(func=cmd_book)

    p = sub.add_parser("catalog", help="What the seller holds for a market, with per-day quality")
    p.add_argument("--market", required=True)
    p.add_argument("--start", help="First JST date, inclusive")
    p.add_argument("--end", help="Last JST date, inclusive")
    p.add_argument("--days", type=int, default=7, help="Most recent N days when no range is given")
    p.set_defaults(func=cmd_catalog)

    p = sub.add_parser("calendar", help="Show available and downloaded dates for a market")
    p.add_argument("--market", required=True)
    p.set_defaults(func=cmd_calendar)

    p = sub.add_parser("manifest", help="Generate temporary URLs for a date range")
    p.add_argument("--market", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--days", type=int, default=7, help="Days from --start")
    p.add_argument("--dry-run", action="store_true", help="Report cost without consuming the grant")
    p.add_argument("--urls-only", action="store_true", help="Print bare URLs, for wget or aria2c")
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("download", help="Download from a start date. Resumable")
    p.add_argument("--market", required=True, help="EXCHANGE:SYMBOL")
    p.add_argument("--start", required=True, help="First JST date, YYYY-MM-DD")
    p.add_argument("--days", type=int,
                   help="Days from --start. Defaults to what the remaining allowance covers")
    p.add_argument("--yes", action="store_true", help="Skip the confirmation")
    p.add_argument("--force", action="store_true", help="Re-download files already present")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("local", help="Show what is already downloaded")
    p.set_defaults(func=cmd_local)

    p = sub.add_parser("duckdb", help="Create or refresh a DuckDB database over the downloaded tree")
    p.add_argument("--db", help="Database file. Defaults to <root>/kql.duckdb")
    p.set_defaults(func=cmd_duckdb)

    p = sub.add_parser("sql", help="Print DuckDB view SQL for the downloaded tree")
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
