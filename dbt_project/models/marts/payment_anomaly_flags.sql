-- Empty scaffold — dbt creates the table shape, ml/score.py INSERTs
-- the flagged payment rows after running IsolationForest.
-- WHERE FALSE produces zero rows but correct column types.
SELECT
    payment_id,
    vendor_id,
    payment_date,
    amount,
    NULL::NUMERIC(6, 4)     AS anomaly_score,
    NULL::VARCHAR(100)      AS anomaly_type,
    NOW()::TIMESTAMP        AS flagged_at
FROM {{ ref('int_vendor_payment_joined') }}
WHERE FALSE
