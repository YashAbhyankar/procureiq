SELECT
    vendor_id,
    vendor_name,
    category,
    credit_tier,
    registration_date::DATE         AS registration_date,
    is_active::BOOLEAN              AS is_active,
    contact_email,
    loaded_at::TIMESTAMP            AS loaded_at
FROM {{ source('raw', 'vendors') }}
