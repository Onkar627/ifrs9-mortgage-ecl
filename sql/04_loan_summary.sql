-- 04_loan_summary.sql
-- One row per loan: how it entered, how (and whether) it left, and, for defaults,
-- what happened afterwards. This is the starting table for the survival baselines
-- (Phase 2) and for LGD and cure-rate modelling (Phase 4).
--
--   outcome                  'default' | 'prepay' | 'other_exit' | 'active' (censored at data end)
--   entry_mob > 1            the loan was acquired seasoned: left truncation (delayed entry)
--   post_default_resolution  for defaults only, from the full history in `perf`:
--       liquidated         ended in 02 / 03 / 09 / 15 (a loss event)
--       paid_off           paid in full after defaulting (a cure for LGD purposes)
--       reperforming_sale  sold as reperforming (16)
--       defect             repurchased for a defect (96)
--       cured_active       no zero balance yet and current at the last record
--       delinquent_open    no zero balance yet and still delinquent or in REO
--   realized_lgd             actual_loss / balance at default, liquidated loans only

CREATE OR REPLACE TABLE loan_summary AS
WITH panel AS (
    SELECT
        loan_id,
        min(period)                                                  AS first_period,
        min(mob)                                                     AS entry_mob,
        max(mob)                                                     AS exit_mob,
        count(*)                                                     AS months_at_risk,
        count(*) FILTER (WHERE event <> 'continue')                  AS n_terminal_events,
        max(period) FILTER (WHERE event <> 'continue')               AS outcome_period,
        max(event) FILTER (WHERE event <> 'continue')                AS terminal_event,
        max(upb_at_default)                                          AS default_upb,
        bool_or(default_in_forbearance)                              AS default_in_forbearance
    FROM loan_month
    GROUP BY loan_id
),
history AS (
    -- arg_max(x, period) = x on the latest record where x is not NULL
    SELECT
        loan_id,
        max(period)                                                  AS last_period,
        count(*)                                                     AS months_observed,
        date_diff('month', min(period), max(period)) + 1 - count(*)  AS gap_months,
        arg_max(zb_code, period)                                     AS final_zb_code,
        arg_max(zb_date, period)                                     AS final_zb_date,
        arg_max(dlq_months, period)                                  AS last_dlq_months,
        arg_max(is_reo_acquired, period)                             AS last_is_reo,
        arg_max(zb_removal_upb, period)                              AS zb_removal_upb,
        arg_max(actual_loss, period)                                 AS actual_loss,
        arg_max(net_sale_proceeds, period)                           AS net_sale_proceeds,
        arg_max(total_expenses, period)                              AS total_expenses,
        arg_max(mi_recoveries, period)                               AS mi_recoveries,
        arg_max(non_mi_recoveries, period)                           AS non_mi_recoveries,
        arg_max(delinquent_accrued_interest, period)                 AS delinquent_accrued_interest,
        max(defect_settlement_date)                                  AS defect_settlement_date
    FROM perf
    GROUP BY loan_id
)
SELECT
    l.loan_id,
    l.vintage_year,
    p.first_period,
    h.last_period,
    p.entry_mob,
    p.exit_mob,
    p.months_at_risk,
    h.months_observed,
    h.gap_months,
    coalesce(p.terminal_event, 'active')                             AS outcome,
    p.outcome_period,
    p.n_terminal_events,
    p.default_upb,
    p.default_in_forbearance,
    CASE
        WHEN p.terminal_event IS DISTINCT FROM 'default'             THEN NULL
        WHEN h.final_zb_code IN ('02', '03', '09', '15')             THEN 'liquidated'
        WHEN h.final_zb_code = '01'                                  THEN 'paid_off'
        WHEN h.final_zb_code = '16'                                  THEN 'reperforming_sale'
        WHEN h.final_zb_code = '96'                                  THEN 'defect'
        WHEN NOT h.last_is_reo AND h.last_dlq_months = 0             THEN 'cured_active'
        ELSE 'delinquent_open'
    END                                                              AS post_default_resolution,
    h.final_zb_code,
    h.final_zb_date,
    h.zb_removal_upb,
    h.actual_loss,
    h.net_sale_proceeds,
    h.total_expenses,
    h.mi_recoveries,
    h.non_mi_recoveries,
    h.delinquent_accrued_interest,
    CASE WHEN p.terminal_event = 'default'
          AND h.final_zb_code IN ('02', '03', '09', '15')
          AND p.default_upb > 0
         THEN h.actual_loss / p.default_upb
    END                                                              AS realized_lgd,
    h.defect_settlement_date
FROM loans l
JOIN panel p USING (loan_id)
JOIN history h USING (loan_id);
