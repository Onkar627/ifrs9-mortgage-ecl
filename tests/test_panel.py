"""Event coding, risk-set construction and lagged predictors in loan_month / loan_summary."""

from __future__ import annotations

import datetime as dt

import pytest

from conftest import one


@pytest.mark.parametrize(
    "loan_id, outcome, month",
    [
        ("F19Q1E000001", "active", None),          # performing to the cutoff
        ("F19Q1E000002", "prepay", "2021-02"),
        ("F07Q1E000003", "default", "2009-04"),     # first month 90+ days past due
        ("F07Q2E000004", "prepay", "2012-06"),      # reached 60 days, cured: never a default
        ("F07Q2E000005", "default", "2010-08"),     # default even though it later cures
        ("F08Q1E000006", "default", "2010-06"),     # short sale at 60 days = credit event
        ("F07Q2E000007", "other_exit", "2022-05"),  # paid at maturity, not a prepayment
        ("F19Q2E000008", "other_exit", "2020-08"),  # defect repurchase
        ("F07Q3E000009", "other_exit", "2015-03"),  # reperforming-loan sale
        ("F19Q3E000010", "default", "2020-06"),     # 90 days during COVID forbearance
        ("F19Q4E000012", "active", None),           # 'XX' months are not defaults
    ],
)
def test_outcomes(edge_db, loan_id, outcome, month):
    got = edge_db.execute(
        "SELECT outcome, strftime(outcome_period, '%Y-%m') FROM loan_summary WHERE loan_id = ?",
        [loan_id],
    ).fetchone()
    assert got == (outcome, month)


def test_orphan_performance_loan_is_excluded(edge_db):
    assert one(edge_db, "SELECT count(*) FROM loan_month WHERE loan_id = 'F19Q4E000099'") == 0
    assert one(edge_db, "SELECT count(*) FROM perf WHERE loan_id = 'F19Q4E000099'") == 3


def test_default_is_absorbing(edge_db):
    # E03 has 46 months of history but only 25 months at risk (to the default month)
    assert edge_db.execute(
        "SELECT months_at_risk, months_observed FROM loan_summary WHERE loan_id = 'F07Q1E000003'"
    ).fetchone() == (25, 46)


def test_exactly_one_terminal_row_per_exited_loan(edge_db):
    assert one(edge_db, "SELECT max(n_terminal_events) FROM loan_summary") == 1
    assert one(edge_db, "SELECT count(*) FROM loan_summary WHERE outcome <> 'active' "
                        "AND n_terminal_events <> 1") == 0


def test_left_truncated_loan_enters_at_its_first_observed_month(edge_db):
    assert edge_db.execute(
        "SELECT entry_mob, exit_mob, months_at_risk FROM loan_summary WHERE loan_id = 'F07Q2E000007'"
    ).fetchone() == (6, 180, 175)


def test_months_on_book_ignores_modification_reset(edge_db):
    rows = edge_db.execute("""
        SELECT p.loan_age, m.mob FROM perf p JOIN loan_month m USING (loan_id, period)
        WHERE loan_id = 'F07Q3E000009' AND period IN (DATE '2010-07-01', DATE '2010-08-01')
        ORDER BY period""").fetchall()
    assert rows == [(34, 34), (1, 35)]  # Freddie's loan_age restarts; mob keeps counting


def test_predictors_are_lagged(edge_db):
    # At E03's default month the loan is 90 days late, but the predictor shows last month: 60
    assert one(edge_db, "SELECT dlq_months_lag1 FROM loan_month "
                        "WHERE loan_id = 'F07Q1E000003' AND event = 'default'") == 2
    # E09 is modified in 2010-08: the flag and the new rate become visible in 2010-09
    rows = edge_db.execute("""
        SELECT modified_lag1, rate_lag1 FROM loan_month WHERE loan_id = 'F07Q3E000009'
        AND period IN (DATE '2010-08-01', DATE '2010-09-01') ORDER BY period""").fetchall()
    assert rows == [(False, 6.75), (True, 4.0)]
    # first observed month: no history, so lagged delinquency is 0 by convention
    assert one(edge_db, "SELECT count(*) FROM loan_month WHERE is_first_obs "
                        "AND dlq_months_lag1 <> 0") == 0


def test_exposure_at_default_for_a_zero_balance_default(edge_db):
    # A short sale already has current_upb = 0 in its default month; exposure must not be 0
    ead, upb_end = edge_db.execute(
        "SELECT upb_at_default, upb_end FROM loan_month "
        "WHERE loan_id = 'F08Q1E000006' AND event = 'default'").fetchone()
    assert upb_end == 0 and ead > 150_000


@pytest.mark.parametrize(
    "loan_id, resolution",
    [
        ("F07Q1E000003", "liquidated"),
        ("F08Q1E000006", "liquidated"),
        ("F07Q2E000005", "paid_off"),
        ("F19Q3E000010", "cured_active"),
    ],
)
def test_post_default_resolution(edge_db, loan_id, resolution):
    assert one(edge_db, "SELECT post_default_resolution FROM loan_summary WHERE loan_id = ?",
               loan_id) == resolution


def test_realized_lgd_matches_freddie_loss_formula(edge_db):
    loss, ead, lgd = edge_db.execute(
        "SELECT actual_loss, default_upb, realized_lgd FROM loan_summary "
        "WHERE loan_id = 'F07Q1E000003'").fetchone()
    assert lgd == pytest.approx(loss / ead)
    assert 0.3 < lgd < 0.5


def test_forbearance_flag_on_covid_default(edge_db):
    assert one(edge_db, "SELECT default_in_forbearance FROM loan_summary "
                        "WHERE loan_id = 'F19Q3E000010'") is True
    assert one(edge_db, "SELECT default_in_forbearance FROM loan_summary "
                        "WHERE loan_id = 'F07Q1E000003'") is False


def test_gap_is_detected(edge_db):
    assert one(edge_db, "SELECT gap_months FROM loan_summary WHERE loan_id = 'F19Q4E000014'") == 1


def test_hazard_panel_view_attaches_origination_fields(edge_db):
    fico, period = edge_db.execute(
        "SELECT fico, period FROM hazard_panel WHERE loan_id = 'F07Q1E000003' "
        "AND event = 'default'").fetchone()
    assert (fico, period) == (655, dt.date(2009, 4, 1))


# --------------------------------------------------------------- invariants at scale
def test_invariants_on_simulated_portfolio(random_db):
    con = random_db
    assert one(con, "SELECT count(*) FROM loan_summary WHERE n_terminal_events > 1") == 0
    # months on book strictly increase within a loan
    assert one(con, """SELECT count(*) FROM (
        SELECT mob - lag(mob) OVER (PARTITION BY loan_id ORDER BY period) AS step FROM loan_month
    ) WHERE step <> 1""") == 0
    # the terminal row, if any, is the loan's last panel row
    assert one(con, """SELECT count(*) FROM loan_month m JOIN loan_summary s USING (loan_id)
        WHERE m.period > s.outcome_period""") == 0
    # every event code maps to exactly one label
    assert one(con, "SELECT count(DISTINCT (event, event_code)) FROM loan_month") == \
        one(con, "SELECT count(DISTINCT event) FROM loan_month")
    # realised LGDs are proportions
    assert one(con, "SELECT count(*) FROM loan_summary WHERE realized_lgd < 0 OR realized_lgd > 1.5") == 0
