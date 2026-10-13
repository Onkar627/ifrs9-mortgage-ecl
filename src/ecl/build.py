"""Build the database: raw files -> loans, perf, loan_month, loan_summary.

Usage
-----
    python -m ecl.build --raw data/raw --out data/processed
    python -m ecl.build --raw data/raw --out data/processed --vintages 2005 2006 2007 2019

Writes data/processed/ecl.duckdb (all tables), one Parquet file per output table
(for R, pandas or polars), and data_quality.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb

from .ingest import discover, register_raw_views
from .quality import write_report

REPO_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = REPO_ROOT / "sql"
SQL_STEPS = ["01_loans.sql", "02_perf.sql", "03_loan_month.sql", "04_loan_summary.sql"]
PARQUET_TABLES = ["loans", "loan_month", "loan_summary"]


def build(raw_dir: str | Path, out_dir: str | Path, vintages: set[int] | None = None,
          export_parquet: bool = True, report: bool = True, synthetic: bool = False,
          quiet: bool = False) -> Path:
    """Run the full pipeline and return the path of the DuckDB database."""
    if not SQL_DIR.is_dir():
        raise FileNotFoundError(
            f"SQL folder not found at {SQL_DIR}. Install the project in editable mode "
            "from the repo root: pip install -e \".[dev]\""
        )
    log = (lambda *_: None) if quiet else (lambda msg: print(msg, flush=True))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "ecl.duckdb"

    files = discover(raw_dir, vintages)
    log(f"Vintages: {', '.join(map(str, files.vintages))} "
        f"({len(files.orig)} origination + {len(files.perf)} performance files)")

    con = duckdb.connect(str(db_path))
    try:
        con.execute("SET preserve_insertion_order = false")  # lets DuckDB stream big sorts
        register_raw_views(con, files)
        for step in SQL_STEPS:
            t0 = time.perf_counter()
            con.execute((SQL_DIR / step).read_text(encoding="utf-8"))
            table = step[3:-4]
            n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            log(f"  {step:<22} {n:>14,} rows  ({time.perf_counter() - t0:,.1f}s)")

        if export_parquet:
            for table in PARQUET_TABLES:
                target = (out_dir / f"{table}.parquet").as_posix().replace("'", "''")
                con.execute(f"COPY {table} TO '{target}' (FORMAT parquet, COMPRESSION zstd)")
            log(f"  Parquet written: {', '.join(t + '.parquet' for t in PARQUET_TABLES)}")

        if report:
            path = write_report(con, out_dir / "data_quality.md", files, synthetic=synthetic)
            log(f"  Data quality report: {path}")
    finally:
        con.close()
    return db_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", default="data/raw", help="folder with Freddie Mac zips or .txt files")
    parser.add_argument("--out", default="data/processed", help="output folder")
    parser.add_argument("--vintages", nargs="+", type=int,
                        help="only these vintage years (zips for other years are not unpacked)")
    parser.add_argument("--no-parquet", action="store_true", help="skip Parquet export")
    parser.add_argument("--synthetic", action="store_true", help="label the report as synthetic")
    args = parser.parse_args(argv)
    try:
        build(args.raw, args.out, set(args.vintages) if args.vintages else None,
              export_parquet=not args.no_parquet, synthetic=args.synthetic)
    except (FileNotFoundError, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
