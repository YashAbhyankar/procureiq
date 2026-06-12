# ProcureIQ — Project Plan

## What It Is
End-to-end data engineering + MLOps pipeline that detects high-risk vendors and anomalous payments, then surfaces a human-readable risk digest via LLM. Runs entirely on localhost via Docker Compose.

**Target roles:** Analytics Engineer, APM, Product at Indian fintech (Razorpay, CRED, Zepto, Meesho).

---

## Stack
| Layer | Tool |
|---|---|
| Infrastructure | Docker Compose, PostgreSQL 15 |
| Ingestion | Python (Faker, SQLAlchemy) |
| Transformation | dbt Core |
| ML | Scikit-learn (IsolationForest + RandomForest), MLflow, SHAP |
| Orchestration | Apache Airflow 2.8 |
| LLM | Groq (default/free) · Claude · OpenRouter — swappable via `LLM_PROVIDER` env var |
| Frontend v1 | Streamlit |
| Frontend v2 | React + FastAPI (future session) |

---

## Key Decisions
- **Python 3.12.10 — do NOT upgrade** (NumPy/Airflow incompatibility with 3.13)
- **LLM is provider-agnostic.** Default = Groq for public GitHub. Set `LLM_PROVIDER=claude` locally — Claude key never goes to GitHub.
- **One commit per phase** with `feat: phase N — description` message for clean history.

---

## Phase Map

### Phase 0 — Prerequisites ✅
Docker Desktop + Git installed, identity configured, GitHub repo created.

### Phase 1 — Infrastructure & Schema
**Files:** `docker-compose.yml`, `init_db.sql`, `init_airflow.sql`, `.env.example`, `airflow/Dockerfile`, `Makefile`

**Services:**
- `postgres:15` → port 5432 (app data + airflow metadata)
- `airflow-webserver` → port 8080 (custom image extending apache/airflow:2.8.0)
- `airflow-scheduler` → same custom image
- `ghcr.io/mlflow/mlflow` → port 5000
- `streamlit` (custom) → port 8501

**Schemas:**
- `raw`: vendors, purchase_orders, invoices, payments
- `warehouse`: vendor_risk_summary, payment_anomaly_flags, llm_risk_digest

**Verify:** `docker-compose up -d` → all 5 services healthy

### Phase 2 — Data Generation & Ingestion
**Files:** `ingestion/generate_data.py`, `ingestion/load_raw.py`

- 500 vendors × 8 categories, 3 credit tiers
- 10,000 POs → 12,000 invoices → 11,000 payments
- 5% injected anomalies: velocity spike, round-number fraud, dormant-then-burst

**Verify:** `make seed` → raw tables populated, row counts correct

### Phase 3 — dbt Project
**Files:** `dbt_project/` (profiles.yml, dbt_project.yml, models, schema.yml, macros)

- Staging: stg_vendors, stg_payments, stg_invoices, stg_purchase_orders
- Intermediate: int_vendor_payment_stats, int_vendor_payment_joined
- Marts: vendor_risk_summary, payment_anomaly_flags

**Verify:** `dbt run && dbt test` — all green

### Phase 4 — ML Layer
**Files:** `ml/train_anomaly.py`, `ml/train_risk.py`, `ml/score.py`, `ml/explain.py`

- IsolationForest → anomaly detection
- RandomForest → vendor risk scoring
- SHAP → feature attribution
- MLflow → experiment tracking + model registry

**Verify:** Models visible in MLflow UI (localhost:5000), scores written to warehouse tables

### Phase 5 — Airflow DAG
**File:** `airflow/dags/procureiq_dag.py`

Pipeline: `ingest_raw → run_dbt_models → run_dbt_tests → score_models → generate_digest → notify_complete`
Schedule: `0 6 * * *` (daily 6am)

**Verify:** Trigger manually → all 6 tasks green

### Phase 6 — LLM Digest
**File:** `llm/digest.py`

Pulls top 5 vendors by risk score + SHAP JSON → calls LLM → writes narrative to `warehouse.llm_risk_digest`

| Provider | Model |
|---|---|
| groq (default) | llama-3.3-70b-versatile |
| openrouter | meta-llama/llama-3.3-70b-instruct |
| claude | claude-sonnet-4-20250514 |

### Phase 7 — Streamlit Frontend (v1)
**Files:** `frontend/app.py`, `frontend/Dockerfile`

3 pages: Pipeline Status · Vendor Risk Explorer · AI Risk Digest

**Verify:** localhost:8501 — all pages load with live data, SHAP waterfall renders

### Phase 8 — README & GitHub Polish
Written last, after everything works. Includes real screenshots, architecture diagram, quick-start block, skills table for recruiters.

---

## End-to-End Verification Checklist
1. `docker-compose up -d` → 5 services healthy
2. `make seed` → raw tables populated
3. `dbt run && dbt test` → all tests green
4. ML training → models in MLflow UI
5. `score.py` → warehouse tables populated
6. `digest.py` → narrative in llm_risk_digest
7. Airflow DAG manual trigger → all 6 tasks green
8. Streamlit → all 3 pages live

---

## File Creation Order
1. `.env.example`
2. `init_airflow.sql` + `init_db.sql`
3. `docker-compose.yml`
4. `airflow/Dockerfile`
5. `Makefile`
6. `ingestion/generate_data.py` + `load_raw.py`
7. `dbt_project/` (full tree)
8. `ml/` (train_anomaly → train_risk → score → explain)
9. `llm/digest.py`
10. `airflow/dags/procureiq_dag.py`
11. `frontend/Dockerfile` + `app.py`
12. `README.md` (last — after screenshots exist)
