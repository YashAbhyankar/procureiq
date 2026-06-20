# ProcureIQ — Vendor Payment Risk Intelligence

End-to-end data engineering and MLOps pipeline that detects vendor payment fraud and risk on a local Docker stack. Ingests synthetic procurement data, transforms it with dbt, scores it with ML models, explains predictions with SHAP, generates a daily LLM risk narrative, and surfaces everything through a Streamlit dashboard with a multi-turn AI chat interface.

Built to demonstrate a production-style analytics pipeline running entirely on localhost — no cloud account required.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Compose                           │
│                                                                 │
│  ┌──────────┐    ┌─────────────┐    ┌──────────────────────┐   │
│  │ Airflow  │───▶│  PostgreSQL │◀───│       dbt Core       │   │
│  │  DAG     │    │             │    │  (staging → marts)   │   │
│  │ (7 tasks)│    │  raw schema │    └──────────────────────┘   │
│  └────┬─────┘    │  warehouse  │                               │
│       │          │    schema   │    ┌──────────────────────┐   │
│       ▼          └──────┬──────┘    │       MLflow         │   │
│  ingest_raw             │           │  experiment tracking  │   │
│  dbt_run                │           │  model registry       │   │
│  dbt_test               │           └──────────────────────┘   │
│  score_models  ─────────┘                                      │
│  explain_models          ▲                                      │
│  llm_digest    ──────────┘           ┌───────────────────────┐ │
│  notify_complete                     │     Streamlit :8501   │ │
│                                      │  Risk Dashboard       │ │
│  ┌──────────────────────┐            │  Payment Anomalies    │ │
│  │   ML Layer           │            │  LLM Digest + Chat    │ │
│  │  IsolationForest     │            └───────────────────────┘ │
│  │  RandomForest        │                                      │
│  │  SHAP TreeExplainer  │   ┌──────────────────────────────┐   │
│  └──────────────────────┘   │  LLM Layer (Groq / Claude)   │   │
│                             │  llama-3.3-70b-versatile     │   │
│                             │  daily digest + chat Q&A     │   │
│                             └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | Apache Airflow 2.8 (LocalExecutor) |
| Warehouse | PostgreSQL 15 — `raw` + `warehouse` schemas |
| Transformation | dbt Core 1.7 — staging, intermediate, mart models |
| Anomaly detection | Scikit-learn IsolationForest |
| Risk scoring | Scikit-learn RandomForest |
| Explainability | SHAP TreeExplainer |
| Experiment tracking | MLflow 2.12 |
| LLM | Groq `llama-3.3-70b-versatile` (default, free) · Claude Sonnet · OpenRouter |
| Frontend | Streamlit 1.32 + Plotly |
| Infrastructure | Docker Compose (all services, no cloud required) |
| Data generation | Faker — 500 vendors, 10k POs, 12k invoices, 10k+ payments |

---

## Quick Start

**Prerequisites:** Docker Desktop, Git

```bash
git clone https://github.com/YashAbhyankar/procureiq.git
cd procureiq
cp .env.example .env          # fill in POSTGRES_PASSWORD and GROQ_API_KEY
docker-compose up -d --build
```

On first start, run the pipeline once to populate the warehouse:

```bash
# Train ML models (one-time)
docker-compose exec airflow-scheduler python /opt/ml/train_anomaly.py
docker-compose exec airflow-scheduler python /opt/ml/train_risk.py

# Run the full DAG manually
# Airflow UI → localhost:8080 → procureiq_pipeline → Trigger DAG
```

| Service | URL | Credentials |
|---|---|---|
| Streamlit dashboard | http://localhost:8501 | — |
| Airflow UI | http://localhost:8080 | admin / admin |
| MLflow UI | http://localhost:5000 | — |

---

## Pipeline Walkthrough

The Airflow DAG (`airflow/dags/procureiq_dag.py`) runs daily at 6am and chains 7 tasks:

### 1. `ingest_raw` — Data ingestion
`ingestion/load_raw.py` truncates and reloads four raw tables from CSVs. Idempotent — safe to re-run any number of times.

Synthetic data (`ingestion/generate_data.py`) injects three fraud patterns at ~5% rate:
- **Velocity spike** — 15 vendors with ≥8 payments per day
- **Round-number fraud** — 180 payments ≥₹50,000 divisible by ₹1,000
- **Dormant-then-burst** — 20 vendors reactivated after long inactivity

### 2 & 3. `dbt_run` / `dbt_test` — Transformation and data quality
dbt rebuilds 8 models across three layers:

```
raw schema
  └── staging/     stg_vendors, stg_purchase_orders, stg_invoices, stg_payments
  └── intermediate/ int_vendor_payment_joined, int_vendor_payment_stats
  └── marts/        vendor_risk_summary, payment_anomaly_flags
```

22 schema tests (unique, not_null, relationships, accepted_values) + 1 singular test. Pipeline halts if any test fails — data quality is a hard gate before ML scoring.

### 4. `score_models` — ML scoring
`ml/score.py` loads both production models from the MLflow registry and writes scores to the warehouse:

- **IsolationForest** → `warehouse.payment_anomaly_flags` — flags ~5% of payments as anomalous, classifies each as velocity_spike / round_number / dormant_burst
- **RandomForest** → `warehouse.vendor_risk_summary` — `risk_score` is `predict_proba["high"]`, the model's probability that a vendor belongs in the high-risk class

### 5. `explain_models` — SHAP explainability
`ml/explain.py` runs SHAP's `TreeExplainer` on the RandomForest for every high-risk vendor. Each SHAP value is the marginal contribution of one feature to that vendor's risk prediction — positive pushes toward "high", negative pulls away. Values are stored as JSONB in `vendor_risk_summary.shap_values` and rendered as a horizontal bar chart in the dashboard.

### 6. `llm_digest` — LLM risk narrative
`llm/digest.py` pulls the top vendors and their SHAP drivers, constructs a structured prompt, and calls the configured LLM to generate a ~200-word daily risk narrative. Stored per-run in `warehouse.llm_risk_digest` for historical comparison.

Provider is controlled by `LLM_PROVIDER` env var — swap between Groq, Claude, or OpenRouter without touching code.

### 7. `notify_complete` — Completion log
Prints a run summary to Airflow task logs. Extensible — can be replaced with a Slack/email notification.

---

## LLM Chat Interface

The Streamlit dashboard includes a multi-turn AI chat on the LLM Digest page. Every query:

1. Fetches a live warehouse snapshot (all 31 high-risk vendors with SHAP drivers, medium/low samples, flagged payment breakdown)
2. Injects the full pipeline architecture and feature semantics into the system prompt — so the LLM can explain *why* a vendor is risky in business terms, not just cite a number
3. Passes the full conversation history as a messages array — follow-up questions like "why is the first one risky?" or "what should we do about it?" work correctly

Example questions:
- *"Which 3 vendors should we avoid and why?"*
- *"How is the risk score calculated?"*
- *"Walk me through the SHAP values for Tata-Mani."*
- *"What's the pattern in dormant-burst anomalies?"*

---

## Project Structure

```
procureiq/
├── airflow/
│   ├── Dockerfile                  # Airflow image with dbt, sklearn, mlflow, openai, anthropic
│   └── dags/procureiq_dag.py       # 7-task daily pipeline DAG
├── dbt_project/
│   ├── models/
│   │   ├── staging/                # stg_vendors, stg_purchase_orders, stg_invoices, stg_payments
│   │   ├── intermediate/           # int_vendor_payment_joined, int_vendor_payment_stats
│   │   └── marts/                  # vendor_risk_summary, payment_anomaly_flags
│   ├── macros/calculate_days_late.sql
│   ├── tests/assert_days_late_in_range.sql
│   └── schema.yml                  # 22 schema tests
├── ingestion/
│   ├── generate_data.py            # Faker-based synthetic data with injected fraud patterns
│   └── load_raw.py                 # Idempotent bulk load into raw schema
├── ml/
│   ├── train_anomaly.py            # IsolationForest training + MLflow registration
│   ├── train_risk.py               # RandomForest training + MLflow registration
│   ├── score.py                    # Batch scoring → warehouse tables
│   └── explain.py                  # SHAP values → vendor_risk_summary.shap_values (JSONB)
├── llm/
│   └── digest.py                   # Provider-agnostic LLM digest (Groq / Claude / OpenRouter)
├── frontend/
│   ├── app.py                      # Streamlit — 3 pages + multi-turn LLM chat
│   └── Dockerfile
├── docker-compose.yml
├── init_db.sql                     # raw + warehouse schema DDL
├── init_airflow.sql                # Airflow metadata DB setup
├── .env.example
└── Makefile
```

---

## Key Design Decisions

**Why IsolationForest for payments and RandomForest for vendors?**
Payments don't have labelled fraud data in a real procurement system, so unsupervised anomaly detection is the right approach. Vendor risk is an aggregate signal — once we have payment-level anomaly labels, we can supervise a classifier over vendor-level statistics. The two models operate at different granularities on purpose.

**Why SHAP?**
Risk scores without explanations are not actionable. A finance team needs to know *why* a vendor is high-risk before freezing payments. SHAP's TreeExplainer gives exact feature attributions that are rendered per-vendor in the dashboard and fed to the LLM so it can explain risk in plain English.

**Why store SHAP values as JSONB?**
Keeps the explanation co-located with the prediction in one row. Streamlit and the LLM both read from the same table — no separate vector store or explanation service.

**Why use the OpenAI SDK for Groq?**
Groq's API is OpenAI-compatible. Using the same SDK for Groq and OpenRouter means one fewer dependency and a simpler provider-swap pattern. Only Claude requires the Anthropic SDK (different auth and message format). The `LLM_PROVIDER` env var dispatches between all three.

**Why is everything on Docker Compose instead of cloud?**
Reproducibility — anyone with Docker Desktop can clone and run the full pipeline in under 10 minutes. Cloud deployment is a natural next step (swap Compose for Kubernetes, RDS for Postgres, Managed Airflow for the scheduler) but adds cost and setup friction for a portfolio project.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```bash
POSTGRES_PASSWORD=your_password
AIRFLOW_UID=50000

# LLM provider — groq (default, free) | claude | openrouter
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...          # console.groq.com — free tier
CLAUDE_API_KEY=sk-ant-...     # optional, keep private
OPENROUTER_API_KEY=sk-or-...  # optional
```

---

## Makefile Shortcuts

```bash
make up        # docker-compose up -d
make down      # docker-compose down
make logs      # tail all service logs
make psql      # connect to procureiq DB
```
