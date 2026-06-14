SELECT
    po_id,
    vendor_id,
    po_date::DATE           AS po_date,
    total_amount::NUMERIC   AS total_amount,
    status,
    department,
    loaded_at::TIMESTAMP    AS loaded_at
FROM {{ source('raw', 'purchase_orders') }}
