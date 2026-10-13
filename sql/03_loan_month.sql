-- 03_loan_month.sql
-- The modelling panel for a discrete-time competing-risks hazard:
-- one row per loan per month in which the loan was at risk.
--
--   event       'continue' | 'prepay' | 'default' | 'other_exit'
--   event_code   0           1          2           3
--
-- A multinomial logit fitted on these rows (outcome = event) IS the competing-risks
-- hazard model: each month a surviving loan "chooses" to continue, prepay or default.
--
-- Definitions (reasons in docs/DECISIONS.md):
--   default    = first month that is 90+ days past due, REO-acquired, or ends in a
--                credit-related zero balance (02 third-party sale, 03 short sale /
--                charge-off, 09 REO disposition, 15 whole-loan sale). Absorbing: later
--                months are dropped here but stay in `perf` for LGD and cure work.
--   prepay     = voluntary payoff (01) more than one month before scheduled maturity
--   other_exit = payoff at maturity, reperforming-loan sale (16), defect repurchase (96);
--                treated as censoring in the hazard model
--
-- Leakage guard: everything observed in month t helps define month t's outcome, so the
-- predictors taken from the performance file are lagged one month (suffix _lag1).
--
-- Entry rule: a loan must be observed in good standing before it can default. A loan that
-- is already in default in its first reported month is flagged `entered_in_default` and
-- left out of `hazard_panel`, the view the models use.

CREATE OR REPLACE TABLE loan_month AS
WITH base AS (
    SELECT
        p.loan_id,
        p.period,
        -- Months on book, counted from the first payment date. Freddie Mac's own
        -- loan_age restarts after a modification; this clock never does.
        date_diff('month', l.first_payment_date, p.period) + 1       AS mob,
        p.current_upb,
        p.zb_removal_upb,
        p.dlq_months,
        p.zb_code,
        p.remaining_months,
        p.current_rate,
        p.eltv,
        coalesce(p.modification_flag IN ('Y', 'P'), false)           AS is_modified,
        coalesce(p.assistance_plan = 'F', false)                     AS in_forbearance,
        coalesce(p.payment_deferral_flag IN ('C', 'P'), false)       AS has_payment_deferral,
        p.disaster_delinquency,
        l.orig_rate,
        -- what happens in month t (outcome side only)
        coalesce(p.dlq_months >= 3, false) OR p.is_reo_acquired      AS is_dpd90,
        coalesce(p.zb_code IN ('02', '03', '09', '15'), false)       AS is_credit_exit
    FROM perf p
    JOIN loans l USING (loan_id)        -- performance rows with no origination record drop out
),
history AS (
    SELECT
        *,
        min(CASE WHEN is_dpd90 OR is_credit_exit THEN period END)
            OVER (PARTITION BY loan_id)                              AS default_period,
        min(CASE WHEN zb_code IS NOT NULL THEN period END)
            OVER (PARTITION BY loan_id)                              AS exit_period,
        lag(dlq_months)           OVER w                             AS dlq_months_prev,
        lag(current_upb)          OVER w                             AS upb_prev,
        lag(current_rate)         OVER w                             AS rate_prev,
        lag(eltv)                 OVER w                             AS eltv_prev,
        lag(is_modified)          OVER w                             AS modified_prev,
        lag(in_forbearance)       OVER w                             AS forbearance_prev,
        lag(has_payment_deferral) OVER w                             AS deferral_prev,
        row_number()              OVER w                             AS obs_number
    FROM base
    WINDOW w AS (PARTITION BY loan_id ORDER BY period)
),
coded AS (
    SELECT
        *,
        CASE
            WHEN period = default_period                              THEN 'default'
            WHEN zb_code = '01' AND coalesce(remaining_months, 2) <= 1 THEN 'other_exit'  -- matured
            WHEN zb_code = '01'                                       THEN 'prepay'
            WHEN zb_code IS NOT NULL                                  THEN 'other_exit'  -- 16, 96
            ELSE 'continue'
        END                                                          AS event
    FROM history
    -- keep months up to and including the first default or zero-balance month
    WHERE period <= least(coalesce(default_period, DATE '9999-12-01'),
                          coalesce(exit_period,    DATE '9999-12-01'))
)
SELECT
    loan_id,
    period,
    mob,
    obs_number,
    obs_number = 1                                                   AS is_first_obs,
    event,
    CASE event WHEN 'continue' THEN 0 WHEN 'prepay' THEN 1
               WHEN 'default'  THEN 2 ELSE 3 END                     AS event_code,

    -- balances (upb_start is the exposure during the month; upb_end is after it)
    coalesce(upb_prev, zb_removal_upb, current_upb)                  AS upb_start,
    current_upb                                                      AS upb_end,
    -- Exposure at default, on the default row only. A default that IS a zero-balance
    -- event (e.g. a short sale before 90 days) already shows current_upb = 0, so its
    -- exposure is the balance removed at that event.
    CASE WHEN event = 'default'
         THEN CASE WHEN zb_code IS NOT NULL
                   THEN coalesce(zb_removal_upb, upb_prev)
                   ELSE current_upb END
    END                                                              AS upb_at_default,

    -- predictors from the performance file, known at the start of month t
    CASE WHEN obs_number = 1 THEN 0 ELSE dlq_months_prev END        AS dlq_months_lag1,
    coalesce(rate_prev, orig_rate)                                   AS rate_lag1,
    eltv_prev                                                        AS eltv_lag1,
    coalesce(modified_prev, false)                                   AS modified_lag1,
    coalesce(forbearance_prev, false)                                AS forbearance_lag1,
    coalesce(deferral_prev, false)                                   AS deferral_lag1,

    -- diagnostic on the default row only: was the loan in forbearance / disaster relief?
    CASE WHEN event = 'default'
         THEN in_forbearance OR disaster_delinquency OR coalesce(forbearance_prev, false)
    END                                                              AS default_in_forbearance,

    -- Already in default when first reported (e.g. a seller-owned modification delivered
    -- years after origination): never observed at risk. Such a loan has exactly one row
    -- here, its default, because default is absorbing.
    obs_number = 1 AND event = 'default'                             AS entered_in_default
FROM coded;

-- The modelling view: loans observed at risk, with origination attributes attached.
CREATE OR REPLACE VIEW hazard_panel AS
SELECT m.*, l.* EXCLUDE (loan_id, source_file)
FROM loan_month m
JOIN loans l USING (loan_id)
WHERE NOT m.entered_in_default;
