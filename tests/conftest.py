"""Build the edge-case fixture once per test session."""

from __future__ import annotations

import duckdb
import pytest

from ecl.build import build
from ecl.synthetic import edge_cases, random_loans, write_files


@pytest.fixture(scope="session")
def edge_db(tmp_path_factory) -> duckdb.DuckDBPyConnection:
    """DuckDB connection to the database built from the hand-written edge cases."""
    root = tmp_path_factory.mktemp("edge")
    orig, perf = edge_cases()
    write_files(root / "raw", orig, perf)
    db_path = build(root / "raw", root / "out", synthetic=True, quiet=True)
    con = duckdb.connect(str(db_path), read_only=True)
    yield con
    con.close()


@pytest.fixture(scope="session")
def random_db(tmp_path_factory) -> duckdb.DuckDBPyConnection:
    """Database built from 1,500 simulated loans, for invariants that must hold at scale."""
    root = tmp_path_factory.mktemp("random")
    orig, perf = random_loans(1500, seed=11)
    write_files(root / "raw", orig, perf)
    db_path = build(root / "raw", root / "out", synthetic=True, quiet=True, export_parquet=False)
    con = duckdb.connect(str(db_path), read_only=True)
    yield con
    con.close()


def one(con: duckdb.DuckDBPyConnection, sql: str, *params):
    """First column of the first row."""
    row = con.execute(sql, list(params)).fetchone()
    return None if row is None else row[0]
