-- 02_perf.sql
-- Typed monthly performance records: exactly one row per (loan_id, period).
-- Input : raw_perf (TEMP view, every column VARCHAR)
-- Output: perf   (the full history, including months after default, which the
--                 LGD and cure work in later phases needs)
--
-- n_source_rows counts how many raw lines shared this (loan_id, period) before
-- de-duplication; the data quality report sums it, so the raw files never have
-- to be read twice.

CREATE OR REPLACE TABLE perf AS
WITH typed AS (
    SELECT
        trim(loan_id)                                                  AS loan_id,
        try_strptime(trim(period) || '01', '%Y%m%d')::DATE            AS period,
        TRY_CAST(current_upb AS DOUBLE)                                AS current_upb,

        -- Delinquency: months past due. 'RA' (REO acquired) and 'XX' (not available)
        -- are not numbers, so they are kept apart instead of being cast.
        CASE WHEN trim(dlq_status) IN ('RA', 'XX') THEN NULL
             ELSE TRY_CAST(trim(dlq_status) AS INTEGER) END            AS dlq_months,
        coalesce(trim(dlq_status) = 'RA', false)                       AS is_reo_acquired,

        TRY_CAST(loan_age AS INTEGER)                                  AS loan_age,
        TRY_CAST(remaining_months AS INTEGER)                          AS remaining_months,
        TRY_CAST(current_rate AS DOUBLE)                               AS current_rate,
        nullif(TRY_CAST(eltv AS INTEGER), 999)                         AS eltv,

        -- termination: '1' and '01' both mean voluntary payoff, so pad to two digits
        lpad(nullif(trim(zero_balance_code), ''), 2, '0')              AS zb_code,
        try_strptime(trim(zero_balance_date) || '01', '%Y%m%d')::DATE  AS zb_date,
        TRY_CAST(zero_balance_removal_upb AS DOUBLE)                   AS zb_removal_upb,
        try_strptime(trim(defect_settlement_date) || '01', '%Y%m%d')::DATE AS defect_settlement_date,

        -- loss components (recoveries negative, costs positive; actual_loss > 0 is a loss)
        TRY_CAST(actual_loss AS DOUBLE)                                AS actual_loss,
        TRY_CAST(net_sale_proceeds AS DOUBLE)                          AS net_sale_proceeds,
        TRY_CAST(mi_recoveries AS DOUBLE)                              AS mi_recoveries,
        TRY_CAST(non_mi_recoveries AS DOUBLE)                          AS non_mi_recoveries,
        TRY_CAST(total_expenses AS DOUBLE)                             AS total_expenses,
        TRY_CAST(delinquent_accrued_interest AS DOUBLE)                AS delinquent_accrued_interest,

        -- workouts and relief
        nullif(trim(modification_flag), '')                            AS modification_flag,
        nullif(trim(payment_deferral_flag), '')                        AS payment_deferral_flag,
        nullif(trim(assistance_plan), '')                              AS assistance_plan,
        coalesce(trim(disaster_delinquency) = 'Y', false)              AS disaster_delinquency,
        TRY_CAST(non_interest_bearing_upb AS DOUBLE)                   AS non_interest_bearing_upb,
        try_strptime(trim(ddlpi) || '01', '%Y%m%d')::DATE              AS ddlpi,
        nullif(trim(servicer_name), '')                                AS servicer_name
    FROM raw_perf
)
SELECT
    *,
    count(*) OVER (PARTITION BY loan_id, period)                       AS n_source_rows
FROM typed
WHERE loan_id IS NOT NULL AND period IS NOT NULL
-- If a month appears twice, keep the record carrying termination information.
QUALIFY row_number() OVER (
    PARTITION BY loan_id, period
    ORDER BY (zb_code IS NULL), current_upb
) = 1;
