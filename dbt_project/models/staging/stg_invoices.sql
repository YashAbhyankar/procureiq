SELECT
    invoice_id,
    po_id,
    vendor_id,
    invoice_date::DATE      AS invoice_date,
    amount::NUMERIC         AS amount,
    due_date::DATE          AS due_date,
    status,
    loaded_at::TIMESTAMP    AS loaded_at
FROM {{ source('raw', 'invoices') }}
