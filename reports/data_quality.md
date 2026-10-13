# Data quality report

Built 2026-10-13 11:00 from 9 vintage file pair(s): 2005, 2006, 2007, 2008, 2012, 2016, 2019, 2020, 2021.

## 1. Integrity checks

| Check | Value | Expected | Status |
|---|---|---|---|
| Loans in origination files | 450,000 | — | info |
| Performance records read | 27,428,974 | — | info |
| Duplicate (loan, month) records removed | 0 | 0 | ok |
| Performance loans with no origination record (excluded) | 0 | 0 | ok |
| Origination loans with no performance records | 0 | 0 | ok |
| Loans with missing first payment date | 0 | 0 | ok |
| Loans with a missing month while at risk (in the hazard panel) | 1 | 0 | **investigate** |
| Loans with missing months anywhere in their history (incl. after default) | 105 | — | info |
| Loans that stop reporting before the data ends, without a termination code | 0 | 0 | ok |
| Records after a loan's zero-balance month | 0 | 0 | ok |
| Months with unknown delinquency status (XX) | 0 | — | info |
| Loans with more than one terminal event in the panel | 0 | 0 | ok |
| Panel rows after a loan's default month | 0 | 0 | ok |
| Loans entering the panel seasoned (entry_mob > 1) | 17,801 | — | info |
| Loans already in default when first reported (left out of hazard_panel) | 5 | — | info |

## 2. Missing origination fields (after sentinel codes became NULL)

| Field | % missing |
|---|---|
| fico | 0.04 |
| orig_ltv | 0 |
| orig_cltv | 0 |
| orig_dti | 5.49 |
| mi_pct | 0 |
| num_borrowers | 0.02 |
| first_time_homebuyer | 0.01 |
| loan_purpose | 0 |
| occupancy | 0 |
| channel | 0 |
| property_type | 0 |
| num_units | 0.01 |
| postal3 | 0 |
| vantage4 | 100 |

## 3. Outcomes by vintage

Share of each vintage's loans by how they left the panel. `active` loans are censored at the end of the data.

| vintage | loans | default_pct | prepay_pct | other_exit_pct | active_pct | avg_fico | avg_ltv | avg_rate |
|---|---|---|---|---|---|---|---|---|
| 2005 | 50,000 | 11.03 | 86.44 | 0.76 | 1.76 | 725 | 68.8 | 5.8 |
| 2006 | 50,000 | 14.43 | 83.6 | 0.48 | 1.49 | 724 | 70 | 6.4 |
| 2007 | 50,000 | 16.53 | 81.3 | 0.44 | 1.72 | 725 | 71.3 | 6.37 |
| 2008 | 50,000 | 9.34 | 88.54 | 0.44 | 1.69 | 742 | 69.9 | 6.05 |
| 2012 | 50,000 | 3.44 | 77.78 | 0.57 | 18.21 | 759 | 76.5 | 3.76 |
| 2016 | 50,000 | 4.73 | 69.26 | 0.13 | 25.88 | 749 | 73.2 | 3.79 |
| 2019 | 50,000 | 5.57 | 68.43 | 0.2 | 25.8 | 749 | 75.6 | 4.24 |
| 2020 | 50,000 | 2.26 | 38 | 0.22 | 59.53 | 758 | 70.8 | 3.2 |
| 2021 | 50,000 | 2.01 | 18.86 | 0.2 | 78.93 | 751 | 69.4 | 2.97 |

## 4. Prepayment and default speeds by calendar year

Count-based monthly rates over loans at risk, annualised: CPR = 1 - (1 - SMM)^12 and CDR likewise.

| year | loan_months | prepays | defaults | cpr_pct | cdr_pct |
|---|---|---|---|---|---|
| 2005 | 255,751 | 1,159 | 76 | 5.3 | 0.356 |
| 2006 | 801,416 | 4,524 | 250 | 6.57 | 0.374 |
| 2007 | 1,307,289 | 8,637 | 858 | 7.65 | 0.785 |
| 2008 | 1,767,403 | 13,928 | 2,633 | 9.06 | 1.773 |
| 2009 | 1,760,852 | 34,646 | 6,510 | 21.22 | 4.347 |
| 2010 | 1,356,467 | 26,962 | 5,225 | 21.41 | 4.526 |
| 2011 | 1,014,122 | 17,545 | 3,443 | 18.89 | 3.999 |
| 2012 | 1,010,811 | 22,013 | 2,349 | 23.22 | 2.753 |
| 2013 | 1,049,913 | 18,255 | 1,477 | 18.98 | 1.675 |
| 2014 | 887,213 | 8,701 | 931 | 11.15 | 1.252 |
| 2015 | 778,031 | 8,654 | 649 | 12.56 | 0.996 |
| 2016 | 934,918 | 9,077 | 476 | 11.05 | 0.609 |
| 2017 | 1,148,478 | 9,120 | 657 | 9.12 | 0.684 |
| 2018 | 1,035,478 | 8,102 | 469 | 9 | 0.542 |
| 2019 | 1,197,321 | 11,394 | 379 | 10.84 | 0.379 |
| 2020 | 1,534,552 | 33,505 | 4,941 | 23.27 | 3.796 |
| 2021 | 1,634,243 | 34,216 | 1,036 | 22.42 | 0.758 |
| 2022 | 1,658,240 | 13,094 | 642 | 9.07 | 0.464 |
| 2023 | 1,539,118 | 7,142 | 559 | 5.43 | 0.435 |
| 2024 | 1,449,405 | 6,928 | 507 | 5.59 | 0.419 |
| 2025 | 1,359,780 | 6,999 | 474 | 6 | 0.418 |
| 2026 | 325,943 | 1,510 | 130 | 5.42 | 0.478 |

## 5. Event mix in the hazard panel

| event | loan_months | pct |
|---|---|---|
| continue | 25,464,248 | 98.673 |
| prepay | 306,111 | 1.186 |
| default | 34,671 | 0.134 |
| other_exit | 1,714 | 0.007 |

## 6. What happened after default

From the full history, including months after default. LGD (loss given default) = actual loss / balance at default, for liquidations with a reported loss. `balance_weighted_lgd` is total loss / total balance, the figure banks report. `loss_not_reported` counts liquidations where Freddie Mac found a defect, so the lender covered the loss and none is published.

| resolution | loans | pct_of_defaults | median_lgd | balance_weighted_lgd | loss_not_reported | defaulted_in_forbearance |
|---|---|---|---|---|---|---|
| liquidated | 14,110 | 40.7 | 0.503 | 0.481 | 1,093 | 90 |
| paid_off | 10,037 | 28.9 | — | — | 0 | 3,054 |
| cured_active | 4,722 | 13.6 | — | — | 0 | 2,974 |
| reperforming_sale | 3,681 | 10.6 | — | — | 0 | 184 |
| defect | 1,094 | 3.2 | — | — | 0 | 53 |
| delinquent_open | 1,027 | 3 | — | — | 0 | 397 |
