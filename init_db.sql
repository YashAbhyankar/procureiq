-- ProcureIQ schema and table definitions.
-- Runs automatically on first postgres container start.
--
-- Two schemas:
--   raw       → data as-ingested from source CSVs (no transforms)
--   warehouse → dbt-transformed marts + ML scores + LLM digest

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS warehouse;

-- ─── RAW LAYER ────────────────────────────────────────────────────────────────

CREATE TABLE raw.vendors (
    vendor_id         VARCHAR(50)  PRIMARY KEY,
    vendor_name       VARCHAR(200) NOT NULL,
    category          VARCHAR(100),               -- e.g. 'Logistics', 'IT Services'
    credit_tier       VARCHAR(10),                -- 'A', 'B', 'C'
    registration_date DATE,
    is_active         BOOLEAN      DEFAULT TRUE,
    contact_email     VARCHAR(200),
    loaded_at         TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE raw.purchase_orders (
    po_id         VARCHAR(50)    PRIMARY KEY,
    vendor_id     VARCHAR(50)    REFERENCES raw.vendors(vendor_id),
    po_date       DATE,
    total_amount  NUMERIC(12, 2),
    status        VARCHAR(50),                    -- 'open', 'closed', 'cancelled'
    department    VARCHAR(100),
    loaded_at     TIMESTAMP      DEFAULT NOW()
);

CREATE TABLE raw.invoices (
    invoice_id    VARCHAR(50)    PRIMARY KEY,
    po_id         VARCHAR(50)    REFERENCES raw.purchase_orders(po_id),
    vendor_id     VARCHAR(50)    REFERENCES raw.vendors(vendor_id),
    invoice_date  DATE,
    amount        NUMERIC(12, 2),
    due_date      DATE,
    status        VARCHAR(50),                    -- 'pending', 'paid', 'overdue'
    loaded_at     TIMESTAMP      DEFAULT NOW()
);

CREATE TABLE raw.payments (
    payment_id    VARCHAR(50)    PRIMARY KEY,
    invoice_id    VARCHAR(50)    REFERENCES raw.invoices(invoice_id),
    vendor_id     VARCHAR(50)    REFERENCES raw.vendors(vendor_id),
    payment_date  DATE,
    amount        NUMERIC(12, 2),
    is_disputed   BOOLEAN        DEFAULT FALSE,
    loaded_at     TIMESTAMP      DEFAULT NOW()
);

-- ─── WAREHOUSE LAYER ──────────────────────────────────────────────────────────

-- Populated by dbt mart model first, then updated in-place by ml/score.py and ml/explain.py
CREATE TABLE warehouse.vendor_risk_summary (
    vendor_id     VARCHAR(50)    PRIMARY KEY,
    vendor_name   VARCHAR(200),
    category      VARCHAR(100),
    risk_score    NUMERIC(6, 4),                  -- 0.0 → 1.0; higher = riskier
    risk_label    VARCHAR(20),                    -- 'low', 'medium', 'high'
    anomaly_score NUMERIC(6, 4),                  -- IsolationForest output
    avg_days_late NUMERIC(8, 2),
    payment_count INTEGER,
    dispute_rate  NUMERIC(6, 4),
    shap_values   JSONB,                          -- feature attributions for top-N vendors
    scored_at     TIMESTAMP
);

-- Rows inserted by ml/score.py after anomaly detection
CREATE TABLE warehouse.payment_anomaly_flags (
    payment_id    VARCHAR(50)    PRIMARY KEY,
    vendor_id     VARCHAR(50),
    payment_date  DATE,
    amount        NUMERIC(12, 2),
    anomaly_score NUMERIC(6, 4),
    anomaly_type  VARCHAR(100),                   -- 'velocity_spike', 'round_number', 'dormant_burst'
    flagged_at    TIMESTAMP      DEFAULT NOW()
);

-- One row per digest run; queried by Streamlit Page 3
CREATE TABLE warehouse.llm_risk_digest (
    id            SERIAL         PRIMARY KEY,
    narrative     TEXT,
    run_date      DATE,
    model_version VARCHAR(100),
    provider      VARCHAR(50),                    -- 'groq', 'claude', 'openrouter'
    created_at    TIMESTAMP      DEFAULT NOW()
);
