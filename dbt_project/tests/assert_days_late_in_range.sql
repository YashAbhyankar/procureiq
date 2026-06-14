-- Singular test: fails if any non-null days_late is outside [-5, 365].
-- Severity is warn (not error) because dormant-then-burst anomalies can
-- legitimately produce days_late > 365 when bursting after a long gap.
{{ config(severity='warn') }}

SELECT payment_id, days_late
FROM {{ ref('int_vendor_payment_joined') }}
WHERE days_late IS NOT NULL
  AND (days_late < -5 OR days_late > 365)
