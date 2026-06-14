-- Payment-level grain, enriched with invoice context.
-- Joining here (not in staging) because days_late requires both
-- payment_date (payments table) and due_date (invoices table).
SELECT
    p.payment_id,
    p.vendor_id,
    p.invoice_id,
    p.payment_date,
    p.amount,
    p.is_disputed,
    i.due_date,
    i.invoice_date,
    i.status                                            AS invoice_status,
    {{ calculate_days_late('p.payment_date', 'i.due_date') }}  AS days_late,
    p.amount / NULLIF(i.amount, 0)                     AS payment_to_invoice_ratio
FROM {{ ref('stg_payments') }} p
LEFT JOIN {{ ref('stg_invoices') }} i USING (invoice_id)
