SELECT
    payment_id,
    invoice_id,
    vendor_id,
    payment_date::DATE      AS payment_date,
    amount::NUMERIC         AS amount,
    is_disputed::BOOLEAN    AS is_disputed,
    loaded_at::TIMESTAMP    AS loaded_at
FROM {{ source('raw', 'payments') }}
