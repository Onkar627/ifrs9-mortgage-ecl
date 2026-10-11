"""Column layouts of Freddie Mac's Single-Family Loan-Level Dataset (SFLLD).

Source: SFLLD General User Guide, Release 47 (July 2026), Glossary section, which
lists attributes "in the order in which they appear in the files". The files are
pipe-delimited with no header row, so these lists are the only thing that maps a
position to a meaning.

Release 47 moved Servicer Name and the MI Cancellation Indicator from the
origination file to the performance file, and added VantageScore 4.0 and
Bankruptcy Cramdown Costs. If a future release changes the layout again,
ingest.check_layout() refuses the file (column-count check): compare against the
header file on the SFLLD download page and update the lists below.
"""

ORIGINATION_COLUMNS: list[str] = [
    "fico",                  # 1  Classic FICO; 9999 = not available
    "first_payment_date",    # 2  YYYYMM
    "first_time_homebuyer",  # 3  Y / N / 9 = n.a.
    "maturity_date",         # 4  YYYYMM
    "msa",                   # 5  MSA or Metropolitan Division; null = none/unknown
    "mi_pct",                # 6  mortgage insurance %; 0 = no MI, 999 = n.a.
    "num_units",             # 7  1-4; 99 = n.a.
    "occupancy",             # 8  P primary / I investment / S second home / 9
    "orig_cltv",             # 9  combined LTV %; 999 = n.a.
    "orig_dti",              # 10 debt-to-income %; 999 = n.a. (all HARP loans)
    "orig_upb",              # 11 original balance, rounded to $1,000
    "orig_ltv",              # 12 LTV %; 999 = n.a.
    "orig_rate",             # 13 note rate %
    "channel",               # 14 R retail / B broker / C correspondent / T TPO / 9
    "prepay_penalty",        # 15 Y / N
    "amortization_type",     # 16 FRM / ARM
    "property_state",        # 17 two-letter code
    "property_type",         # 18 CP / CO / PU / SF / MH / 99
    "postal_code",           # 19 first three digits; 000 = unknown
    "loan_id",               # 20 PYYQnXXXXXXX (product, vintage year+quarter, digits)
    "loan_purpose",          # 21 P purchase / C cash-out / N no cash-out / R / 9
    "orig_term",             # 22 months
    "num_borrowers",         # 23 99 = n.a. (coding changed in 2018Q2, see docs)
    "seller_name",           # 24 'OTHER' for small sellers
    "super_conforming",      # 25 Y / N
    "pre_harp_loan_id",      # 26 only for HARP loans
    "special_program",       # 27 H / F / R / null
    "harp_flag",             # 28 Y / N (relief refinance)
    "valuation_method",      # 29 1 ACE / 2 appraisal / 3 other / 4 ACE+PDR / 7 n.a.
    "interest_only",         # 30 Y / N
    "vantage4",              # 31 VantageScore 4.0; 9999 = n.a.
]

PERFORMANCE_COLUMNS: list[str] = [
    "loan_id",                      # 1
    "period",                       # 2  monthly reporting period, YYYYMM
    "current_upb",                  # 3  actual balance at end of month
    "dlq_status",                   # 4  00, 01, 02, ... (months past due), RA = REO acquired, XX = n.a.
    "loan_age",                     # 5  resets after a modification
    "remaining_months",             # 6  months to legal maturity
    "defect_settlement_date",       # 7  YYYYMM
    "modification_flag",            # 8  Y = modified this month / P = earlier / null
    "zero_balance_code",            # 9  01, 02, 03, 09, 15, 16, 96 (see docs/DECISIONS.md)
    "zero_balance_date",            # 10 YYYYMM
    "current_rate",                 # 11 note rate in effect
    "non_interest_bearing_upb",     # 12 deferred balance after modification / deferral
    "ddlpi",                        # 13 due date of last paid installment, YYYYMM
    "mi_recoveries",                # 14 recoveries are negative, costs positive
    "net_sale_proceeds",            # 15
    "non_mi_recoveries",            # 16
    "total_expenses",               # 17
    "legal_costs",                  # 18
    "maintenance_costs",            # 19
    "taxes_insurance",              # 20
    "misc_expenses",                # 21
    "actual_loss",                  # 22 positive = loss (codes 02, 03, 09, 15 only)
    "cum_modification_cost",        # 23
    "step_rate_flag",               # 24
    "payment_deferral_flag",        # 25 C current / P prior
    "eltv",                         # 26 estimated (mark-to-market) LTV; from Apr 2017; 999 = n.a.
    "zero_balance_removal_upb",     # 27 balance just before the zero-balance event
    "delinquent_accrued_interest",  # 28
    "disaster_delinquency",         # 29 Y / null
    "assistance_plan",              # 30 F forbearance / R repayment / T trial / null
    "current_modification_cost",    # 31
    "interest_bearing_upb",         # 32
    "mi_cancellation",              # 33 Y / N / 7
    "servicer_name",                # 34
    "bankruptcy_cramdown_costs",    # 35
]
