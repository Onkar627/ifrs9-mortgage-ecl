"""The data quality report is generated and flags the planted problems."""

from __future__ import annotations

from pathlib import Path

from ecl.ingest import discover
from ecl.quality import integrity_results, write_report
from ecl.synthetic import edge_cases, write_files


def test_integrity_checks_flag_exactly_the_planted_problems(edge_db):
    flagged = {label for label, value, expected in integrity_results(edge_db)
               if expected is not None and value != expected}
    assert flagged == {
        "Duplicate (loan, month) records removed",                   # E13
        "Performance loans with no origination record (excluded)",   # E15
        "Loans with gaps in their monthly history",                  # E14
    }


def test_report_is_written_with_all_sections(edge_db, tmp_path):
    orig, perf = edge_cases()
    write_files(tmp_path / "raw", orig, perf)
    path = write_report(edge_db, tmp_path / "dq.md", discover(tmp_path / "raw"), synthetic=True)
    text = Path(path).read_text()
    for heading in ("Integrity checks", "Missing origination fields", "Outcomes by vintage",
                    "Prepayment and default speeds", "Event mix", "What happened after default"):
        assert heading in text
    assert "Synthetic data" in text
    assert "| 2007 |" in text  # years are not printed as 2,007
