from __future__ import annotations

from pathlib import Path


def capabilities():
    out={"duckdb":False,"polars":False,"pyarrow":False}
    try: import duckdb  # noqa: F401
    except Exception: pass
    else: out["duckdb"]=True
    try: import polars  # noqa: F401
    except Exception: pass
    else: out["polars"]=True
    try: import pyarrow  # noqa: F401
    except Exception: pass
    else: out["pyarrow"]=True
    return out


def csv_to_parquet(source: Path, dest: Path) -> bool:
    """Fast, non-destructive conversion. Returns False when modern engine is unavailable."""
    try:
        import duckdb
        dest.parent.mkdir(parents=True,exist_ok=True)
        con=duckdb.connect()
        con.execute("COPY (SELECT * FROM read_csv_auto(?)) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",[str(source),str(dest)])
        con.close()
        return True
    except Exception:
        return False


def distinct_counts(path: Path, columns: list[str]) -> dict[str,int] | None:
    """Use DuckDB for large-file distinct counts without materializing the full dataset."""
    try:
        import duckdb
        ext=path.suffix.lower()
        rel="read_parquet(?)" if ext==".parquet" else "read_csv_auto(?)"
        expr=", ".join([f"count(distinct {c}) as {c}" for c in columns])
        con=duckdb.connect()
        row=con.execute(f"SELECT {expr} FROM {rel}",[str(path)]).fetchone()
        con.close()
        return {c:int(v or 0) for c,v in zip(columns,row)}
    except Exception:
        return None


def lazy_scan(path: Path):
    """Return a Polars LazyFrame when available; callers may fall back to pandas."""
    try:
        import polars as pl
        if path.suffix.lower()==".parquet": return pl.scan_parquet(path)
        return pl.scan_csv(path, infer_schema_length=10000, ignore_errors=False)
    except Exception:
        return None
