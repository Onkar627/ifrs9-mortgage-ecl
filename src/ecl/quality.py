"""Data quality report for a built database, written as Markdown.

Every number comes from a query against the tables built by sql/*.sql. The report
answers three questions before any modelling starts: did the files load intact,
do the event definitions behave, and do the default and prepayment rates look like
the mortgage history they should reflect (the 2005-2008 vintages, the refinance
waves)?
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb

from .ingest import RawFiles

# (label, query returning one number, expected value or None if there is no single "right" answer)
INTEGRITY_CHECKS: list[tuple[str, str, int | None]] = [
    ("Loans in origination files",
     "SELECT count(*) FROM loans", None),
    ("Performance records read",
     "SELECT sum(n_source_rows) FROM perf", None),
    ("Duplicate (loan, month) records removed",
     "SELECT sum(n_source_rows - 1) FROM perf", 0),
    ("Performance loans with no origination record (excluded)",
     "SELECT count(DISTINCT loan_id) FROM perf WHERE loan_id NOT IN (SELECT loan_id FROM loans)", 0),
    ("Origination loans with no performance records",
     "SELECT count(*) FROM loans WHERE loan_id NOT IN (SELECT DISTINCT loan_id FROM perf)", 0),
    ("Loans with missing first payment date",
     "SELECT count(*) FROM loans WHERE first_payment_date IS NULL", 0),
    # A missing month only matters while the loan is at risk: that is what the PD
    # model is fitted on. Gaps after default (seen in real foreclosure histories)
    # touch only the post-default record, so they are reported but not flagged.
    ("Loans with a missing month while at risk (in the hazard panel)",
     """SELECT count(DISTINCT loan_id) FROM (
            SELECT loan_id, date_diff('month', lag(period) OVER (PARTITION BY loan_id ORDER BY period),
                                      period) AS step
            FROM loan_month) WHERE step > 1""", 0),
    ("Loans with missing months anywhere in their history (incl. after default)",
     "SELECT count(*) FROM loan_summary WHERE gap_months > 0", None),
    ("Loans that stop reporting before the data ends, without a termination code",
     """SELECT count(*) FROM loan_summary
        WHERE final_zb_code IS NULL AND last_period < (SELECT max(period) FROM perf)""", 0),
    ("Records after a loan's zero-balance month",
     """SELECT count(*) FROM (
            SELECT period, min(CASE WHEN zb_code IS NOT NULL THEN period END)
                               OVER (PARTITION BY loan_id) AS first_zb
            FROM perf) WHERE period > first_zb""", 0),
    ("Months with unknown delinquency status (XX)",
     "SELECT count(*) FROM perf WHERE dlq_months IS NULL AND NOT is_reo_acquired", None),
    ("Loans with more than one terminal event in the panel",
     "SELECT count(*) FROM loan_summary WHERE n_terminal_events > 1", 0),
    ("Panel rows after a loan's default month",
     """SELECT count(*) FROM loan_month m JOIN loan_summary s USING (loan_id)
        WHERE s.outcome = 'default' AND m.period > s.outcome_period""", 0),
    ("Loans entering the panel seasoned (entry_mob > 1)",
     "SELECT count(*) FROM loan_summary WHERE entry_mob > 1", None),
    ("Loans in default at their first observed month",
     "SELECT count(*) FROM loan_summary WHERE outcome = 'default' AND outcome_period = first_period", None),
]

MISSINGNESS_FIELDS = [
    "fico", "orig_ltv", "orig_cltv", "orig_dti", "mi_pct", "num_borrowers",
    "first_time_homebuyer", "loan_purpose", "occupancy", "channel", "property_type",
    "num_units", "postal3", "vantage4",
]

OUTCOMES_BY_VINTAGE = """
SELECT
    s.vintage_year::VARCHAR                                    AS vintage,
    count(*)                                                   AS loans,
    round(100 * avg((s.outcome = 'default')::INT), 2)          AS default_pct,
    round(100 * avg((s.outcome = 'prepay')::INT), 2)           AS prepay_pct,
    round(100 * avg((s.outcome = 'other_exit')::INT), 2)       AS other_exit_pct,
    round(100 * avg((s.outcome = 'active')::INT), 2)           AS active_pct,
    round(avg(l.fico))                                         AS avg_fico,
    round(avg(l.orig_ltv), 1)                                  AS avg_ltv,
    round(avg(l.orig_rate), 2)                                 AS avg_rate
FROM loan_summary s JOIN loans l USING (loan_id)
GROUP BY ALL ORDER BY vintage
"""

# Count-based monthly rates, annualised the way MBS desks quote speeds:
# CPR = 1 - (1 - SMM)^12 for prepayments, CDR likewise for defaults.
HAZARDS_BY_YEAR = """
WITH y AS (
    SELECT
        year(period)                                           AS year,
        count(*)                                               AS loan_months,
        sum((event = 'prepay')::INT)                           AS prepays,
        sum((event = 'default')::INT)                          AS defaults
    FROM loan_month GROUP BY ALL
)
SELECT
    year::VARCHAR AS year, loan_months, prepays, defaults,
    round(100 * (1 - pow(1 - prepays / loan_months, 12)), 2)   AS cpr_pct,
    round(100 * (1 - pow(1 - defaults / loan_months, 12)), 3)  AS cdr_pct
FROM y ORDER BY year
"""

EVENT_MIX = """
SELECT event, count(*) AS loan_months,
       round(100 * count(*) / sum(count(*)) OVER (), 3) AS pct
FROM loan_month GROUP BY event ORDER BY min(event_code)
"""

DEFAULT_RESOLUTION = """
SELECT
    post_default_resolution                                    AS resolution,
    count(*)                                                   AS loans,
    round(100 * count(*) / sum(count(*)) OVER (), 1)           AS pct_of_defaults,
    round(median(realized_lgd), 3)                             AS median_lgd,
    round(sum(actual_loss) FILTER (WHERE realized_lgd IS NOT NULL)
          / sum(default_upb) FILTER (WHERE realized_lgd IS NOT NULL), 3)
                                                               AS balance_weighted_lgd,
    count(*) FILTER (WHERE post_default_resolution = 'liquidated'
                       AND actual_loss IS NULL)                AS loss_not_reported,
    sum((default_in_forbearance)::INT)                         AS defaulted_in_forbearance
FROM loan_summary WHERE outcome = 'default'
GROUP BY ALL ORDER BY loans DESC
"""


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (int, float)):
        return f"{value:,}"  # floats arrive already rounded by the SQL
    return str(value)


def md_table(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    if not rows:
        return "_(no rows)_"
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(_fmt(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def integrity_results(con: duckdb.DuckDBPyConnection) -> list[tuple[str, int, int | None]]:
    return [(label, con.execute(sql).fetchone()[0] or 0, expected)
            for label, sql, expected in INTEGRITY_CHECKS]


def write_report(con: duckdb.DuckDBPyConnection, path: Path, files: RawFiles,
                 synthetic: bool = False) -> Path:
    out: list[str] = ["# Data quality report", ""]
    if synthetic:
        out += ["> **Synthetic data.** Every number below comes from generated test loans. "
                "It shows that the pipeline works, not anything about real mortgages.", ""]
    out += [f"Built {datetime.now():%Y-%m-%d %H:%M} from {len(files.orig)} vintage file pair(s): "
            f"{', '.join(str(v) for v in files.vintages)}.", ""]

    out += ["## 1. Integrity checks", "",
            "| Check | Value | Expected | Status |", "|---|---|---|---|"]
    for label, value, expected in integrity_results(con):
        if expected is None:
            status = "info"
        else:
            status = "ok" if value == expected else "**investigate**"
        out.append(f"| {label} | {value:,} | {'—' if expected is None else expected} | {status} |")

    out += ["", "## 2. Missing origination fields (after sentinel codes became NULL)", ""]
    parts = ", ".join(
        f"round(100 * count(*) FILTER (WHERE {f} IS NULL) / count(*), 2) AS {f}"
        for f in MISSINGNESS_FIELDS
    )
    row = con.execute(f"SELECT {parts} FROM loans").fetchone()
    out += ["| Field | % missing |", "|---|---|"]
    out += [f"| {f} | {_fmt(v)} |" for f, v in zip(MISSINGNESS_FIELDS, row)]

    out += ["", "## 3. Outcomes by vintage", "",
            "Share of each vintage's loans by how they left the panel. "
            "`active` loans are censored at the end of the data.", "",
            md_table(con, OUTCOMES_BY_VINTAGE)]

    out += ["", "## 4. Prepayment and default speeds by calendar year", "",
            "Count-based monthly rates over loans at risk, annualised: "
            "CPR = 1 - (1 - SMM)^12 and CDR likewise.", "",
            md_table(con, HAZARDS_BY_YEAR)]

    out += ["", "## 5. Event mix in the hazard panel", "", md_table(con, EVENT_MIX)]

    out += ["", "## 6. What happened after default", "",
            "From the full history, including months after default. LGD (loss given default) "
            "= actual loss / balance at default, for liquidations with a reported loss. "
            "`balance_weighted_lgd` is total loss / total balance, the figure banks report. "
            "`loss_not_reported` counts liquidations where Freddie Mac found a defect, so the "
            "lender covered the loss and none is published.", "",
            md_table(con, DEFAULT_RESOLUTION), ""]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path
