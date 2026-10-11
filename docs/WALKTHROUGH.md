# Walkthrough: from Freddie Mac text files to a hazard panel

Read this with the code open. Every table below is real pipeline output for the synthetic edge-case loans, so you can reproduce each one:

```bash
python -m ecl.synthetic data/synthetic_edge --n-random 0
python -m ecl.build --raw data/synthetic_edge --out data/processed_edge --synthetic
```

## 0. The idea, from first principles

A loan that is alive at the start of a month can do one of three things in that month: keep paying, pay off early, or default. So write **one row per loan per month at risk**, and label each row with what happened.

For loan *i* in month *t*, with predictors **x** known at the start of the month, a multinomial logit on those rows gives

$$
h_k(t) = P(Y_{it} = k \mid \text{alive at start of } t,\ \mathbf{x}_{i,t-1}) = \frac{e^{\eta_k}}{1 + e^{\eta_{\text{prepay}}} + e^{\eta_{\text{default}}}}, \quad k \in \{\text{prepay}, \text{default}\}
$$

with "continue" as the base outcome. That is a **discrete-time competing-risks hazard model**, which is just a discrete choice model where the loan does the choosing. Chain the monthly hazards and you get the lifetime numbers IFRS 9 needs (Phase 4):

$$
S(t) = \prod_{s \le t} \big(1 - h_{\text{prepay}}(s) - h_{\text{default}}(s)\big), \qquad
\text{lifetime PD}(T) = \sum_{t=1}^{T} S(t-1)\, h_{\text{default}}(t)
$$

Prepayment matters for credit losses: a loan that prepays can no longer default, so a model that ignores prepayment overstates lifetime PD.

Phase 1 builds the table of rows. The rest of this document follows loans through it.

## 1. One loan, all the way through: E03 (default, REO, loss)

### 1a. Raw origination line → `loans`

```text
655|200704|N|203703|19100|25|1|P|90|45|200000|90|6.5|R|N|FRM|TX|SF|750|F07Q1E000003|P|360|2|OTHER|N|||N|2|N|9999
```

No header row, so position is everything (`src/ecl/layout.py`): field 1 is the FICO score (655), field 12 the LTV (90), field 20 the loan id, and field 31 is VantageScore 4.0, where `9999` means "not available" and becomes NULL. The loan id `F07Q1…` says fixed-rate, originated 2007 Q1. `sql/01_loans.sql` gives:

| loan_id | vintage_year | first_payment_date | fico | orig_ltv | orig_dti | mi_pct | orig_upb | orig_rate |
|---|---|---|---|---|---|---|---|---|
| F07Q1E000003 | 2007 | 2007-04-01 | 655 | 90 | 45 | 25 | 200,000 | 6.5 |

### 1b. Raw performance lines → `perf`

Four consecutive months and the final record (fields: loan id, period, balance, delinquency status, loan age, remaining months, …):

```text
F07Q1E000003|200901|195787.73|00|22|338|||||6.5|0|200901|...
F07Q1E000003|200902|195787.73|01|23|337|||||6.5|0|200901|...
F07Q1E000003|200903|195787.73|02|24|336|||||6.5|0|200901|...
F07Q1E000003|200904|195787.73|03|25|335|||||6.5|0|200901|...
F07Q1E000003|201101|0|RA|46|314|||09|201101|6.5|0||-20000.0|-130000.0|-1500.0|12500.0|...|79787.73|...
```

Two things to notice. The balance stops falling in 2009-02 because no payments arrive, and the "due date of last paid installment" stays at 2009-01, which is what drives the status 01 → 02 → 03. The last record has status `RA` (REO acquired, not a number) and zero-balance code `09` (REO disposition), with the loss components filled in. `sql/02_perf.sql` keeps `RA` out of the numeric column:

| period | current_upb | dlq_months | is_reo_acquired | zb_code | actual_loss |
|---|---|---|---|---|---|
| 2009-01 | 195,788 | 0 | false | | |
| 2009-02 | 195,788 | 1 | false | | |
| 2009-03 | 195,788 | 2 | false | | |
| 2009-04 | 195,788 | 3 | false | | |
| 2009-05 | 195,788 | 4 | false | | |
| 2011-01 | 0 | NULL | true | 09 | 79,788 |

### 1c. `perf` → `loan_month` (the panel)

`sql/03_loan_month.sql` finds the first month that meets the default definition (2009-04, the first month at 3+ months late), labels it, and drops everything after it:

| period | mob | event | event_code | upb_start | upb_end | dlq_months_lag1 |
|---|---|---|---|---|---|---|
| 2009-01 | 22 | continue | 0 | 195,990 | 195,788 | 0 |
| 2009-02 | 23 | continue | 0 | 195,788 | 195,788 | 0 |
| 2009-03 | 24 | continue | 0 | 195,788 | 195,788 | 1 |
| 2009-04 | 25 | **default** | 2 | 195,788 | 195,788 | **2** |

The loan has 46 months of history but only 25 rows here: default is absorbing (decision D2). And on the default row, `dlq_months_lag1` is 2, not 3. The month's own status is what *defines* the default, so using it as a predictor would leak the answer (D7).

### 1d. `loan_summary`: what default cost

| outcome | outcome_month | months_at_risk | months_observed | default_upb | post_default_resolution | actual_loss | realized_lgd |
|---|---|---|---|---|---|---|---|
| default | 2009-04 | 25 | 46 | 195,788 | liquidated | 79,788 | 0.408 |

Freddie Mac's Actual Loss is removal balance + net sale proceeds + delinquent interest + expenses + MI recoveries + non-MI recoveries, with recoveries negative:

```text
195,788 − 130,000 + 23,000 + 12,500 − 20,000 − 1,500 = 79,788
LGD = 79,788 / 195,788 = 0.408
```

That `realized_lgd` is the raw material for the LGD model in Phase 4.

## 2. Five more loans, one rule each

**E05: defaults, then cures.** 90 days late in 2010-08, back to current by 2010-11, paid off in 2013-03.

| period | dlq_months | event |
|---|---|---|
| 2010-07 | 2 | continue |
| 2010-08 | 3 | **default** |
| 2010-09 | 2 | *(not in panel)* |
| 2010-10 | 1 | *(not in panel)* |
| 2010-11 | 0 | *(not in panel)* |

Still a default for PD. `post_default_resolution = paid_off`: a cure, so zero loss on the LGD side. Mortgage LGD is mostly "probability of cure × 0 + probability of liquidation × severity", and this is where the cure probability comes from.

**E06: short sale at 60 days late.** Never reached 90 days, but sold at a loss (code `03`), so it defaults in its zero-balance month.

| period | dlq_months_lag1 | event | upb_end | upb_at_default |
|---|---|---|---|---|
| 2010-05 | 1 | continue | 184,976 | |
| 2010-06 | 2 | **default** | 0 | 184,762 |

`upb_end` is already 0 in that month, so the exposure comes from the balance removed at the event. The first version of the pipeline used `upb_end`, gave this loan zero exposure and no LGD, and the edge-case test caught it (D8). That is a good story for "how do you know your pipeline is right?"

**E07: 15-year loan, bought seasoned, paid at maturity.** First appears at month 6 on book; last record in 2022-05 has `remaining_months = 0` and code `01`.

| entry_mob | exit_mob | months_at_risk | outcome |
|---|---|---|---|
| 6 | 180 | 175 | other_exit |

Code `01` means "prepaid or matured", so a payoff with no months left is not a prepayment (D3). And `entry_mob = 6` is left truncation: the loan was never observable in months 1–5 (D6).

**E09: modified loan.** 60 days late, then modified in 2010-08 with a rate cut from 6.75% to 4%.

| period | Freddie `loan_age` | `mob` | modification_flag | rate_lag1 | modified_lag1 |
|---|---|---|---|---|---|
| 2010-07 | 34 | 34 | | 6.75 | false |
| 2010-08 | **1** | 35 | Y | 6.75 | false |
| 2010-09 | 2 | 36 | P | **4.00** | **true** |

Freddie Mac's clock restarts at the modification; `mob` keeps counting, because the seasoning curve needs an unbroken time axis (D5). The new rate and the flag reach the predictors one month later, as D7 requires. The loan later leaves as a reperforming-loan sale (`16`): `other_exit`, censored (D4).

**E10: COVID forbearance.** Stops paying in 2020-04 inside a forbearance plan (`F`), reaches 90 days in 2020-06, gets a payment deferral in 2021-01 and is current to the end of the data.

| period | dlq_months | assistance_plan | deferral | event | default_in_forbearance |
|---|---|---|---|---|---|
| 2020-04 | 1 | F | | continue | |
| 2020-05 | 2 | F | | continue | |
| 2020-06 | 3 | F | | **default** | **true** |
| 2021-01 | 0 | | C | *(not in panel)* | |

Under the plain 90-day rule this is a default (`post_default_resolution = cured_active`), even though the borrower never really failed. Whether it should count is open decision O1, the most interesting modelling question in the project.

## 3. How the tests protect these rules

`pytest` runs 37 tests: the edge cases above, layout and file handling, and invariants checked on 1,500 simulated loans (one terminal event per loan, months on book always +1, nothing after the outcome month). To check that the tests really bite, each rule was broken on purpose in the SQL and the suite rerun:

| Deliberate bug | Caught |
|---|---|
| default at 120 days instead of 90 | yes |
| month-*t* delinquency used as a predictor (no lag) | yes |
| payoff at maturity counted as prepayment | yes |
| Freddie's resetting `loan_age` used as the clock | yes |
| zero exposure for zero-balance defaults | yes |
| short sales (`03`) not treated as credit events | yes |

When you change a definition later, add the edge case first and watch the test fail, then change the SQL.

## 4. Your turn, on the real data

Answers on request; try each one first. They are all SQL on `ecl.duckdb` (open it in Python with `duckdb.connect("data/processed/ecl.duckdb")`, or in the DuckDB CLI).

1. **Vintage curves.** For each vintage, the share of loans that have defaulted by 12, 24, 36 and 60 months on book. Careful: a 2021 loan cannot have defaulted by month 60 yet. What is the right denominator at each horizon?
2. **Roll rates.** For each calendar year, among loans 30 days late, the share that are 60 days late next month and the share that cure. Use `lead()` on `perf`. Do 2009 and 2020 look different, and why?
3. **Prepayment S-curve.** CPR by refinance incentive (`rate_lag1` minus the market mortgage rate). You will need Freddie Mac's weekly 30-year PMMS rate averaged by month, which is the first macro join of Phase 4.
4. **Default in the first observed month.** How many loans, which vintages, and what does that say about when Freddie Mac acquired them?
5. **Severity.** Mean `realized_lgd` by original LTV band and by liquidation year. Does it peak in 2009–2011?
6. **COVID check.** How many 2020 defaults have `default_in_forbearance = true`, and what share ended `cured_active`? This sizes open decision O1.

## 5. Questions to be ready for

* *How did you define default, and why 90 days?* D1, with the IFRS 9 presumption and the credit-event codes.
* *How did you handle loans that enter the data late?* D6: delayed entry, and what goes wrong if you ignore it.
* *How do you avoid leakage in a monthly panel?* D7, with E03's default row as the example.
* *How do you know the pipeline is right?* Edge cases, invariants at scale, mutation testing, and the exposure bug they caught.
* *What happens to your model in 2020?* O1. Have numbers for (a) vs (b) by the time you are interviewing.
