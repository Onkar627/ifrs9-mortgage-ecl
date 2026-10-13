# Modelling decisions

Each entry says what was decided, what else was possible, and why. The **open** entries at the end are yours to decide. They are the questions a model validator, or an interviewer, will ask first.

Facts about the data come from Freddie Mac's [SFLLD General User Guide, Release 47 (July 2026)](https://www.freddiemac.com/fmac-resources/research/pdf/general_user_guide_july_2026.pdf).

---

## Settled in Phase 1

### D1. Default = the first month that is 90+ days past due, REO-acquired, or ends in a credit-related zero balance

* **90 days past due** is the Basel default backstop. IFRS 9 also presumes that default happens no later than 90 days past due (IFRS 9 para. B5.5.37), so the PD here lines up with both regimes.
* **REO acquired** (status `RA`) means Freddie Mac took the property, which is a default whatever the day count says.
* **Credit-related zero balances** count even before 90 days: `02` third-party sale, `03` short sale or charge-off, `09` REO disposition, `15` whole-loan sale. A short sale at 60 days late is still a credit loss (edge case E06). These are exactly the codes for which Freddie Mac computes Actual Loss.
* Delinquency is computed from the due date of the last paid installment, so the 90-day clock is mechanical, not a servicer's judgement.
* A loan that reaches 90 days in the same month it is paid off or repurchased still defaults that month. In the real 2007 sample that happened to 81 payoffs and 3 defect repurchases, all with status `03` in that month. Their resolution is `paid_off` or `defect`, so each one is a default with no loss.
* *Alternatives:* 180 days past due (used in some mortgage studies), or liquidation only. Both trigger later and sit less naturally with IFRS 9. They are worth running as sensitivities, not as the base case.

### D2. Default is absorbing for PD; the history after default is kept for LGD

PD here is the probability of a **first** default. After default the loan leaves `loan_month`, but every later month stays in `perf`, and `loan_summary.post_default_resolution` records how it ended. A loan that defaults and then cures (E05) is still a default for PD purposes. Its cure shows up as a zero loss on the LGD side, which is how cure-rate LGD models work.

### D3. Prepayment = voluntary payoff more than one month before scheduled maturity

Zero-balance code `01` means "prepaid **or matured**". A 15-year loan making its final scheduled payment is not prepaying (E07), so a payoff with `remaining_months <= 1` is coded `other_exit`.

### D4. Other exits are treated as censoring

Payoff at maturity, defect repurchase (`96`) and reperforming-loan sale (`16`) end observation for reasons outside the default and prepayment mechanisms. In the hazard model those months count as survived (non-informative censoring).

*Caveat:* reperforming-loan sales are, by definition, loans that were in trouble before. Censoring them may bias PD down slightly. Sensitivity check: recode `16` as default when the loan was ever 60+ days late.

### D5. The time axis is months on book from the first payment date

Freddie Mac's `loan_age` restarts after a modification (E09: 34 → 1). The hazard's baseline, the seasoning curve, needs a clock that never resets, so `mob` is computed from `first_payment_date`.

### D6. Seasoned acquisitions enter the risk set late (left truncation)

Freddie Mac reports a loan from when it acquired the loan. Some loans first appear several months after origination (E07 enters at month 6). In the discrete-time panel this is handled automatically, because there are simply no rows before entry. In R, use the counting-process form `Surv(entry_mob - 1, exit_mob, event)`; plain `Surv(exit_mob, event)` would treat those loans as observed from month 1 and overstate early survival.

### D7. Predictors from the performance file are lagged one month

Whatever is observed in month *t* helps define month *t*'s outcome. Using month-*t* delinquency to predict month-*t* default is leakage. Every `_lag1` column is known at the start of the month. At E03's default row the loan is 90 days late, but `dlq_months_lag1` shows the 60 days known beforehand.

### D8. Exposure at default

Exposure at default is the balance in the default month. When the default **is** a zero-balance event (a short sale before 90 days), that month already shows a balance of 0, so the exposure is the balance removed at the event. The first version of the pipeline got this wrong: E06 had zero exposure and no LGD. The edge-case test caught it, and `upb_at_default` now handles both cases.

### D9. Definitional breaks to remember when pooling vintages

| Field | Break | Handling |
|---|---|---|
| Number of borrowers | Up to 2018Q1, `2` meant "more than one" | Use `multiple_borrowers` (a binary flag that means the same in every vintage) |
| LTV / CLTV | Allowed ranges widened from 2018Q2 (6–105% before, 1–998% after) | Cap or bucket LTV before modelling |
| Estimated LTV (ELTV) | Only populated from April 2017 | `eltv_lag1` is NULL earlier; never use it in a model trained on earlier periods |
| Delinquency `00` | Up to September 2025 it can also mean "before the first payment date" | Harmless for default timing |
| File layout | Release 47 moved Servicer Name and MI cancellation to the performance file, added VantageScore 4.0 | `layout.py`; the loader refuses any other column count |
| HARP | A HARP loan is `harp_flag = Y` **and** original LTV > 80 | `is_harp` |
| First payment date | For construction-to-permanent conversions and seller-owned modifications it is the conversion date, so a few loans start paying years after their vintage (44 in the 2007 sample, in 2009–2012) | Months on book count from that date, as Freddie Mac's own loan age does |

---

## Settled after checking the real data

The pipeline was first run on the 2007 sample (50,000 loans, 3,012,061 monthly records through March 2026), then on all nine chosen vintages (450,000 loans, 27,428,974 monthly records). These are the things only real data could show. Counts are from the 2007 sample unless they say otherwise.

### D10. Most loans appear the month before their first payment is due

42,091 of the 50,000 loans first show up at months on book 0, the month before the first payment is due. Those months stay in the panel. A loan can be paid off then (34 were), but it cannot default, because no payment is due yet.

### D11. Missing months after default do not affect the PD panel

30 loans have missing months in their history, and every gap comes after the loan's default, during long foreclosure timelines. The panel stops at the default month, so the PD model never sees them. The quality report therefore checks gaps inside the panel (expected 0) separately from gaps anywhere in the history (information only).

Across the nine vintages, 105 loans have gaps, and exactly one has a gap while at risk: `F06Q40191966` has no record for February 2009. It was current in January, 30 days late in March, and defaulted in May 2009, which the panel records. No default can hide in the missing month, because a loan that was current in January cannot be 90 days late in February. So it stays as it is: the panel has no row for that month, which drops one month at risk out of 25.8 million. The report keeps flagging it, because any new gap would need the same check.

### D12. A blank loss means a defect was found

441 of the 4,484 liquidations have no reported loss, and every one of them has a defect settlement date: the lender bought the loan back or made Freddie Mac whole, so Freddie Mac publishes no loss. They are left out of LGD.

LGD is reported balance-weighted (total loss / total balance at default, 0.50 for the 2007 sample) next to the median loan's LGD (0.52). Balance-weighted is what banks report, because a large loan's loss matters more. About one in twelve liquidations (340 of 4,043) loses more than the balance at default, because unpaid interest and foreclosure costs build up over long timelines. A few show a gain, where sale proceeds and mortgage insurance exceed the balance. Across the nine vintages, the balance-weighted LGD is 0.48.

### D13. A loan's vintage is the file it came from

The loan id encodes the origination year, but one loan in the 2008 file (`F09Q10107924`) carries a 2009 id. It was the only one of 450,000 where the two disagree, and it showed up in the report as a one-loan "2009 vintage". Vintage now comes from the file name (`sample_orig_2008.txt` → 2008), so it always matches the years asked for with `--vintages`; the id is only a fallback for files named differently.

### D14. A loan must be seen in good standing before it can default

5 loans across the nine vintages are already 90+ days late in their first reported month. They are modified loans delivered to Freddie Mac years after origination: their first payment dates (2010–2015) and terms (61 to 360 months) date from the modification, which is how Freddie Mac reports seller-owned modifications, so they enter at months on book 0 already in default. They were never observed at risk, so a model would learn nothing true from them: their one panel row shows a "current" loan defaulting at once. They are flagged `entered_in_default` and left out of `hazard_panel`, the modelling view, but stay in `loan_month` and `loan_summary` so they are still counted. This is the standard survival-analysis rule that a subject must be event-free when it enters the risk set.

---

## Open: yours to decide

### O1. COVID forbearance (the most interesting one)

In 2020 borrowers in forbearance stopped paying with their servicer's agreement. Because status counts from the last paid installment, many reached 90 days past due while in a relief plan (E10), so under D1 they are defaults. Most later cured through payment deferrals.

* **(a) Keep D1.** A pure backstop; 2020 becomes a regime the model has to survive.
* **(b) Exclude defaults with `default_in_forbearance = true`.** This mirrors 2020 regulatory guidance that loans under COVID relief schemes should not automatically count as defaulted.
* **(c) Keep them and add a forbearance indicator** as a predictor or segment.

*Evidence from the real 2007 sample:* the 2020 default rate (CDR 6.0%) matched 2009's (6.1%), at the height of the financial crisis. But 122 of the 140 defaults in 2020 happened during forbearance or disaster relief. By March 2026, 103 of those 122 had paid off or become current, and 2 had been liquidated. Under (a), 2020 looks like a second crisis; under (b), it nearly disappears.

*Evidence from the nine vintages:* 6,752 defaults happened during forbearance or disaster relief, and 6,028 of them later paid off or became current; 90 were liquidated. The choice also reorders the vintages. Under (a), 2019 loans default more often (5.6%) than 2012 (3.4%) or 2016 (4.7%) loans; 84% of the 2019 defaults were in forbearance. Under (b), 2019 is the safest of the three (0.9%, against 1.9% and 1.2%).

*Suggestion:* build with (a), report (b) as a sensitivity, and make the gap between them a headline of the validation write-up. It is the same management-overlay debate banks had in 2020–21, and the out-of-time test period runs straight through it.

### O2. HARP and relief-refinance loans

DTI is not disclosed for HARP loans, their LTV is above 80 by construction, and they are refinances of loans already in the data (`pre_harp_loan_id` links them). Keep them with a flag, model them separately, or exclude them? Each choice changes the default rates of the 2009–2015 vintages.

*Evidence from the nine vintages:* 35% of 2012 loans (17,399) and 5% of 2016 loans are relief refinances, and DTI is blank for every one of them, not only the HARP subset; it is almost never blank otherwise. They also default more: 6.3% against 1.9% for other 2012 loans. So a missing DTI is not random noise. It identifies a riskier group, and imputing it with an average would hide that. At minimum, a model needs the `relief_refi` flag next to DTI.

### O3. Development and out-of-time split

The plan is to develop on data before 2019 and test on 2019 onwards, which covers COVID. Decide whether the split is by **calendar time** (all loan-months before 2019 vs after) or by **vintage** (loans originated before 2017 vs after). Calendar-time splits are what banks backtest against; vintage splits test generalisation to new books.

### O4. Which vintages to load

**Current choice:** start with nine vintages: crisis (2005–2008), calm years (2012, 2016) and COVID-era (2019–2021). That keeps builds quick while getting started and still covers both stress periods.

All 17 sample years from 2005 to 2021 are downloaded. The other eight stay zipped in `data/raw` and are not unpacked until asked for, so scaling up later is one build command. A full 17-year build was tested at about 54 million monthly records: under 4 minutes on 2 cores, about 5.5 GB of memory and 2 GB of database.
