"""Find Freddie Mac files, check their layout, and expose them to DuckDB.

Nothing is copied here: raw_orig and raw_perf are TEMP views over the text files
(every column VARCHAR), and the SQL steps in sql/ turn them into typed tables in
one pass. Reading everything as text first matters because fields mix numbers and
codes (delinquency status is '03' in one month and 'RA' in another).
"""

from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .layout import ORIGINATION_COLUMNS, PERFORMANCE_COLUMNS

# sample_orig_2007.txt (sample files) or orig_2007Q1.txt (full Standard Dataset).
# Non-standard files (historical_data_excl_*) have a different layout and never match.
_ORIG_RE = re.compile(r"^(?:sample_)?orig_(\d{4})(?:Q[1-4])?\.txt$", re.IGNORECASE)
_PERF_RE = re.compile(r"^(?:sample_)?perf_(\d{4})(?:Q[1-4])?\.txt$", re.IGNORECASE)


class LayoutError(ValueError):
    """A file's column count does not match the layout in layout.py."""


@dataclass
class RawFiles:
    orig: list[Path]
    perf: list[Path]

    @property
    def vintages(self) -> list[int]:
        return sorted({_vintage(p) for p in self.orig})


def _vintage(path: Path) -> int:
    m = _ORIG_RE.match(path.name) or _PERF_RE.match(path.name)
    return int(m.group(1)) if m else -1


def extract_zips(raw_dir: Path) -> Path:
    """Extract the .txt members of every zip in raw_dir into raw_dir/_extracted.

    Idempotent: a member already extracted at the same size is skipped. Only the
    base name of each member is used, so a crafted path inside a zip cannot write
    outside the target folder.
    """
    out = raw_dir / "_extracted"
    for zpath in sorted(raw_dir.glob("*.zip")):
        with zipfile.ZipFile(zpath) as zf:
            for member in zf.infolist():
                name = Path(member.filename).name
                if not name.lower().endswith(".txt"):
                    continue
                target = out / name
                if target.exists() and target.stat().st_size == member.file_size:
                    continue
                out.mkdir(exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1 << 20)
    return out


def discover(raw_dir: str | Path, vintages: set[int] | None = None) -> RawFiles:
    """Return matching origination/performance files, optionally for some vintages.

    Accepts zips (extracted automatically) and/or already-extracted .txt files.
    If the same file name exists twice, the copy nearest raw_dir wins, so manual
    extraction plus the zip never loads a vintage twice.
    """
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"Raw data folder not found: {raw_dir}")
    extract_zips(raw_dir)

    by_name: dict[str, Path] = {}
    for path in sorted(raw_dir.rglob("*.txt"), key=lambda p: (len(p.parts), str(p))):
        by_name.setdefault(path.name.lower(), path)

    orig: list[Path] = []
    perf: list[Path] = []
    for path in by_name.values():
        for regex, bucket in ((_ORIG_RE, orig), (_PERF_RE, perf)):
            m = regex.match(path.name)
            if m and (vintages is None or int(m.group(1)) in vintages):
                bucket.append(path)

    orig.sort(key=lambda p: p.name)
    perf.sort(key=lambda p: p.name)
    if not orig or not perf:
        wanted = f" for vintages {sorted(vintages)}" if vintages else ""
        raise FileNotFoundError(
            f"No origination/performance file pairs found in {raw_dir}{wanted}. "
            "Expected sample_YYYY.zip or sample_orig_YYYY.txt + sample_perf_YYYY.txt."
        )
    missing = {_vintage(p) for p in orig} ^ {_vintage(p) for p in perf}
    if missing:
        raise FileNotFoundError(
            f"Vintages with only one of the two files: {sorted(missing)}. "
            "Each vintage needs both its origination and performance file."
        )
    return RawFiles(orig=orig, perf=perf)


def check_layout(path: Path, expected: list[str]) -> None:
    """Fail fast if the first line's field count differs from the expected layout."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        first = fh.readline().rstrip("\r\n")
    found = first.count("|") + 1 if first else 0
    if found != len(expected):
        raise LayoutError(
            f"{path.name}: found {found} pipe-delimited fields, expected {len(expected)}. "
            "The file comes from a different SFLLD release than src/ecl/layout.py describes; "
            "compare with the file layout / header file on Freddie Mac's download page."
        )


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def register_raw_views(con: duckdb.DuckDBPyConnection, files: RawFiles) -> None:
    """Create TEMP views raw_orig and raw_perf over the files (all columns VARCHAR)."""
    for view, paths, columns in (
        ("raw_orig", files.orig, ORIGINATION_COLUMNS),
        ("raw_perf", files.perf, PERFORMANCE_COLUMNS),
    ):
        for path in paths:
            check_layout(path, columns)
        file_list = "[" + ", ".join(_sql_str(p.resolve().as_posix()) for p in paths) + "]"
        col_spec = "{" + ", ".join(f"{_sql_str(c)}: 'VARCHAR'" for c in columns) + "}"
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW {view} AS
            SELECT *
            FROM read_csv(
                {file_list},
                delim = '|', header = false, columns = {col_spec},
                quote = '', escape = '',   -- the files are unquoted; a stray " stays data
                auto_detect = false, filename = true
            )
            """
        )
