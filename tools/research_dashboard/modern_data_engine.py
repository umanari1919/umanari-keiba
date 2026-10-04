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


def inventory_scan(path: Path):
    """Return JRA/NAR inventory rows using DuckDB, or None when unavailable/incompatible."""
    try:
        import duckdb
        ext=path.suffix.lower()
        rel="read_parquet(?)" if ext==".parquet" else "read_csv_auto(?, header=true, sample_size=-1)"
        con=duckdb.connect()
        cols={r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {rel}",[str(path)]).fetchall()}
        required={"race_scope_cd"}
        if not required.issubset(cols):
            con.close();return None
        race="count(distinct cast(race_id as varchar))" if "race_id" in cols else "0"
        horse="count(distinct cast(horse_id as varchar))" if "horse_id" in cols else "0"
        labeled=("count(*) filter (where label_win is not null)" if "label_win" in cols else ("count(*) filter (where finish_order is not null)" if "finish_order" in cols else "0"))
        start=("min(try_cast(race_date as date))" if "race_date" in cols else "NULL")
        end=("max(try_cast(race_date as date))" if "race_date" in cols else "NULL")
        q=f"""select case when cast(race_scope_cd as varchar) in ('1','1.0','JRA') then 'JRA' when cast(race_scope_cd as varchar) in ('2','2.0','NAR') then 'NAR' else 'OTHER' end domain, count(*) rows, {race} races, {horse} horses, {labeled} labeled_rows, {start} start_date, {end} end_date from {rel} group by 1"""
        rows=con.execute(q,[str(path)]).fetchall();con.close()
        return [{"domain":d,"rows":int(n or 0),"races":int(r or 0),"horses":int(h or 0),"labeled_rows":int(l or 0),"start_date":str(s) if s else "","end_date":str(e) if e else ""} for d,n,r,h,l,s,e in rows if d in {"JRA","NAR"}]
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
