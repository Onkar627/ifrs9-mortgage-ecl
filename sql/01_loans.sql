-- 01_loans.sql
-- One row per loan: typed origination attributes.
-- Input : raw_orig (TEMP view, every column VARCHAR; see src/ecl/ingest.py)
-- Output: loans
--
-- Freddie Mac encodes "not available" with sentinel values (9999, 999, 99, 9, 7).
-- They become NULL here so that an average FICO is never pulled up by a 9999.

CREATE OR REPLACE TABLE loans AS
WITH typed AS (
    SELECT
        trim(loan_id)                                                    AS loan_id,
        -- Vintage is encoded in the id: PYYQnXXXXXXX (P = product, YY = year, Qn = quarter).
        CASE WHEN TRY_CAST(substr(trim(loan_id), 2, 2) AS INTEGER) >= 90
             THEN 1900 ELSE 2000 END
            + TRY_CAST(substr(trim(loan_id), 2, 2) AS INTEGER)          AS vintage_year,
        TRY_CAST(substr(trim(loan_id), 5, 1) AS INTEGER)                AS vintage_quarter,

        try_strptime(trim(first_payment_date) || '01', '%Y%m%d')::DATE  AS first_payment_date,
        try_strptime(trim(maturity_date) || '01', '%Y%m%d')::DATE       AS maturity_date,
        TRY_CAST(orig_term AS INTEGER)                                   AS orig_term,
        TRY_CAST(orig_upb AS DOUBLE)                                     AS orig_upb,
        TRY_CAST(orig_rate AS DOUBLE)                                    AS orig_rate,

        -- borrower and collateral risk
        nullif(TRY_CAST(fico AS INTEGER), 9999)                          AS fico,
        nullif(TRY_CAST(vantage4 AS INTEGER), 9999)                      AS vantage4,
        nullif(TRY_CAST(orig_ltv AS INTEGER), 999)                       AS orig_ltv,
        nullif(TRY_CAST(orig_cltv AS INTEGER), 999)                      AS orig_cltv,
        nullif(TRY_CAST(orig_dti AS INTEGER), 999)                       AS orig_dti,
        nullif(TRY_CAST(mi_pct AS INTEGER), 999)                         AS mi_pct,
        nullif(TRY_CAST(num_borrowers AS INTEGER), 99)                   AS num_borrowers,
        -- Before 2018Q2, num_borrowers was only 1 or 2 (= "more than one"); this flag
        -- means the same thing in every vintage.
        nullif(TRY_CAST(num_borrowers AS INTEGER), 99) >= 2              AS multiple_borrowers,
        nullif(trim(first_time_homebuyer), '9')                          AS first_time_homebuyer,

        -- loan and property characteristics
        nullif(trim(loan_purpose), '9')                                  AS loan_purpose,
        nullif(trim(occupancy), '9')                                     AS occupancy,
        nullif(trim(channel), '9')                                       AS channel,
        nullif(trim(property_type), '99')                                AS property_type,
        nullif(TRY_CAST(num_units AS INTEGER), 99)                       AS num_units,
        trim(property_state)                                             AS property_state,
        nullif(left(trim(postal_code), 3), '000')                        AS postal3,
        nullif(trim(msa), '')                                            AS msa,
        trim(amortization_type)                                          AS amortization_type,
        trim(prepay_penalty)                                             AS prepay_penalty,
        trim(interest_only)                                              AS interest_only,
        trim(super_conforming)                                           AS super_conforming,
        nullif(trim(special_program), '')                                AS special_program,
        nullif(TRY_CAST(valuation_method AS INTEGER), 7)                 AS valuation_method,
        trim(harp_flag) = 'Y'                                            AS relief_refi,
        -- Freddie Mac's rule: HARP = relief refinance with original LTV above 80.
        trim(harp_flag) = 'Y'
            AND nullif(TRY_CAST(orig_ltv AS INTEGER), 999) > 80          AS is_harp,
        nullif(trim(pre_harp_loan_id), '')                               AS pre_harp_loan_id,
        trim(seller_name)                                                AS seller_name,

        filename                                                         AS source_file
    FROM raw_orig
)
SELECT *
FROM typed
WHERE loan_id IS NOT NULL AND loan_id <> ''
QUALIFY row_number() OVER (PARTITION BY loan_id ORDER BY source_file) = 1;
