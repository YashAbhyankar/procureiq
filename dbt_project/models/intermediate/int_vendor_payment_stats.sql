-- Per-vendor aggregate features used by both ML models.
-- This is what the RandomForest risk scorer and IsolationForest anomaly
-- detector read as their feature matrix.
WITH payment_stats AS (
    SELECT
        vendor_id,
        COUNT(*)                                                        AS payment_count,
        AVG(days_late)                                                  AS avg_days_late,
        SUM(CASE WHEN is_disputed THEN 1 ELSE 0 END)::FLOAT
            / NULLIF(COUNT(*), 0)                                       AS dispute_rate,
        AVG(amount)                                                     AS avg_payment_amount,
        STDDEV(amount)                                                  AS stddev_payment_amount,
        MAX(payment_date)                                               AS last_payment_date,
        DATE_PART('day', NOW() - MAX(payment_date)::TIMESTAMP)         AS days_since_last_payment
    FROM {{ ref('int_vendor_payment_joined') }}
    GROUP BY vendor_id
),

po_stats AS (
    SELECT
        vendor_id,
        COUNT(*) AS po_count
    FROM {{ ref('stg_purchase_orders') }}
    GROUP BY vendor_id
)

SELECT
    s.vendor_id,
    s.payment_count,
    COALESCE(s.avg_days_late, 0)::NUMERIC(8, 2)         AS avg_days_late,
    COALESCE(s.dispute_rate, 0)::NUMERIC(6, 4)           AS dispute_rate,
    COALESCE(s.avg_payment_amount, 0)                    AS avg_payment_amount,
    COALESCE(s.stddev_payment_amount, 0)                 AS stddev_payment_amount,
    s.last_payment_date,
    COALESCE(s.days_since_last_payment, 999)::INTEGER    AS days_since_last_payment,
    COALESCE(p.po_count, 0)                              AS po_count,
    COALESCE(p.po_count::FLOAT / NULLIF(s.payment_count, 0), 0)  AS po_to_payment_ratio
FROM payment_stats s
LEFT JOIN po_stats p USING (vendor_id)
