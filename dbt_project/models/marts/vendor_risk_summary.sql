-- One row per vendor. dbt populates the business features; ml/score.py
-- fills in risk_score, risk_label, anomaly_score, shap_values, scored_at
-- via UPDATE after this table is created each DAG run.
SELECT
    v.vendor_id,
    v.vendor_name,
    v.category,
    v.credit_tier,
    COALESCE(s.avg_days_late, 0)::NUMERIC(8, 2)     AS avg_days_late,
    COALESCE(s.payment_count, 0)                     AS payment_count,
    COALESCE(s.dispute_rate, 0)::NUMERIC(6, 4)       AS dispute_rate,
    COALESCE(s.days_since_last_payment, 999)         AS days_since_last_payment,
    COALESCE(s.po_to_payment_ratio, 0)::NUMERIC(8, 4) AS po_to_payment_ratio,
    -- ML columns — NULL until ml/score.py and ml/explain.py run
    NULL::NUMERIC(6, 4)     AS risk_score,
    NULL::VARCHAR(20)       AS risk_label,
    NULL::NUMERIC(6, 4)     AS anomaly_score,
    NULL::JSONB             AS shap_values,
    NULL::TIMESTAMP         AS scored_at
FROM {{ ref('stg_vendors') }} v
LEFT JOIN {{ ref('int_vendor_payment_stats') }} s USING (vendor_id)
