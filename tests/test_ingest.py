"""File discovery, zip handling, layout checks and typing of the raw fields."""

from __future__ import annotations

import zipfile

import pytest

from ecl.ingest import LayoutError, check_layout, discover
from ecl.layout import ORIGINATION_COLUMNS, PERFORMANCE_COLUMNS
from ecl.synthetic import edge_cases, write_files

from conftest import one


def test_layouts_match_release_47_field_counts():
    assert len(ORIGINATION_COLUMNS) == 31
    assert len(PERFORMANCE_COLUMNS) == 35
    assert ORIGINATION_COLUMNS.index("loan_id") == 19  # field 20 in the user guide
    assert len(set(ORIGINATION_COLUMNS)) == 31 and len(set(PERFORMANCE_COLUMNS)) == 35


def test_wrong_column_count_is_refused(tmp_path):
    path = tmp_path / "sample_orig_2007.txt"
    path.write_text("|".join(["x"] * 32) + "\n")  # e.g. a pre-2026 layout
    with pytest.raises(LayoutError, match="found 32 .* expected 31"):
        check_layout(path, ORIGINATION_COLUMNS)


def test_zips_are_extracted_and_never_loaded_twice(tmp_path):
    orig, perf = edge_cases()
    files = write_files(tmp_path / "staging", orig, perf)
    raw = tmp_path / "raw"
    raw.mkdir()
    # 2007 arrives as a zip, 2019 as loose text files, and 2019 ALSO inside a zip
    with zipfile.ZipFile(raw / "sample_2007.zip", "w") as zf:
        for f in files:
            if "_2007" in f.name:
                zf.write(f, arcname=f"nested/{f.name}")  # directory inside the zip is ignored
    with zipfile.ZipFile(raw / "sample_2019.zip", "w") as zf:
        for f in files:
            if "_2019" in f.name:
                zf.write(f, arcname=f.name)
    for f in files:
        if "_2019" in f.name:
            (raw / f.name).write_bytes(f.read_bytes())

    found = discover(raw)
    assert found.vintages == [2007, 2019]
    assert [p.name for p in found.orig] == ["sample_orig_2007.txt", "sample_orig_2019.txt"]
    assert found.orig[1].parent == raw  # the loose copy wins over the extracted duplicate


def test_vintage_filter_and_missing_partner_file(tmp_path):
    orig, perf = edge_cases()
    files = write_files(tmp_path, orig, perf)
    assert discover(tmp_path, {2008}).vintages == [2008]
    next(f for f in files if f.name == "sample_perf_2008.txt").unlink()
    with pytest.raises(FileNotFoundError, match="only one of the two files"):
        discover(tmp_path)


def test_sentinel_codes_become_null(edge_db):
    row = edge_db.execute("""
        SELECT fico, orig_ltv, orig_cltv, orig_dti, mi_pct, num_units, occupancy, channel,
               property_type, loan_purpose, num_borrowers, first_time_homebuyer, postal3,
               valuation_method
        FROM loans WHERE loan_id = 'F24Q1E000011'""").fetchone()
    assert all(v is None for v in row)


def test_vintage_parsed_from_loan_id(edge_db):
    assert edge_db.execute(
        "SELECT vintage_year, vintage_quarter FROM loans WHERE loan_id = 'F07Q3E000009'"
    ).fetchone() == (2007, 3)


def test_duplicate_month_removed_and_counted(edge_db):
    assert one(edge_db, "SELECT count(*) FROM perf WHERE loan_id = 'F19Q4E000013' "
                        "AND period = DATE '2020-07-01'") == 1
    assert one(edge_db, "SELECT sum(n_source_rows - 1) FROM perf") == 1


def test_reo_and_unknown_status_are_not_numbers(edge_db):
    assert one(edge_db, "SELECT count(*) FROM perf WHERE is_reo_acquired AND dlq_months IS NOT NULL") == 0
    assert one(edge_db, "SELECT count(*) FROM perf WHERE loan_id = 'F19Q4E000012' "
                        "AND dlq_months IS NULL") == 2
