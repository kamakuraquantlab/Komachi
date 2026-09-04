"""DuckDB wiring over the downloaded tree.

The buyer should be able to query immediately after a download, without
writing a path glob or tracking a manifest. `komachi duckdb` creates a
persistent database of views; `komachi sql` prints the same SQL for anyone who
would rather paste it into their own session.
"""

from pathlib import Path

from .layout import DATA_TYPES, dataset_glob, local_inventory, single_view_sql


class DuckDBUnavailable(RuntimeError):
    pass


def available_datasets(root: Path) -> list[str]:
    """Datasets with at least one file on disk.

    DuckDB resolves the glob when the view is created, not when it is queried,
    so creating a view over a dataset the buyer has not downloaded fails the
    whole command. A buyer who bought only trades is a normal case, not an
    error, so only datasets that exist get a view.
    """
    present = {data_type for (_, data_type) in local_inventory(root)}
    return [d for d in DATA_TYPES if d in present]


def build_database(root: Path, db_path: Path) -> dict:
    """Create or refresh a DuckDB file holding one view per available dataset."""
    try:
        import duckdb
    except ImportError:
        raise DuckDBUnavailable(
            "duckdb is required for this command. Install with: pip install 'komachi[duckdb]'"
        ) from None

    datasets = available_datasets(root)
    if not datasets:
        return {}

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        counts = {}
        for data_type in datasets:
            view = data_type.lower()
            conn.execute(single_view_sql(root, data_type))
            counts[view] = conn.execute(f"SELECT count(*) FROM {view}").fetchone()[0]
        return counts
    finally:
        conn.close()


def missing_datasets(root: Path) -> list[str]:
    """Datasets with no files, reported so the absence is visible."""
    return [d for d in DATA_TYPES if d not in available_datasets(root)]


__all__ = [
    "DuckDBUnavailable",
    "available_datasets",
    "build_database",
    "dataset_glob",
    "missing_datasets",
]
