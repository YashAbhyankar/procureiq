# ProcureIQ — Session 01 Journal
**Date:** 2026-06-14  
**Phases completed:** 0, 1, 2

---

## What We Built

### Phase 0 — Prerequisites
- Installed Docker Desktop 29.5.3 and Git 2.54.0
- Configured global Git identity (YashAbhyankar / yashabhyankar22@gmail.com)
- Created public GitHub repo `procureiq` and connected local repo via `gh auth login`
- Installed GitHub CLI via `winget` to handle HTTPS authentication

### Phase 1 — Infrastructure & Schema
Created the full Docker Compose stack from scratch:

**Files created:**
- `docker-compose.yml` — 5 services on a shared `procureiq_net` bridge network
- `init_airflow.sql` — creates the `airflow` metadata database on first Postgres start
- `init_db.sql` — creates `raw` + `warehouse` schemas and all 7 tables
- `airflow/Dockerfile` — extends Airflow with dbt, sklearn, mlflow, shap, anthropic, etc.
- `.env.example` — template for secrets (LLM keys, Postgres password)
- `Makefile` — `make up/down/seed/test/reset/demo` shortcuts
- `frontend/Dockerfile` + `frontend/app.py` — placeholder so Streamlit service doesn't crash
- `PLAN.md` — full project reference (phases, decisions, verification checklist)
- `PROGRESS.md` — session-by-session progress tracker

**Verified:**
- All 13/13 containers healthy
- Airflow UI at localhost:8080 (admin/admin) ✓
- MLflow UI at localhost:5000 ✓
- Streamlit placeholder at localhost:8501 ✓

### Phase 2 — Data Generation & Ingestion
Created two scripts in `ingestion/`:

**`generate_data.py`:**
- 500 vendors (40% tier A, 40% B, 20% C) across 8 categories
- 10,000 purchase orders linked to vendors
- 12,000 invoices (net-30 terms, linked to POs)
- 10,093 payments with ~5% injected anomalies:
  - **Velocity spike** — 15 vendors making 10-12 payments in a single day
  - **Round-number fraud** — 180 payments with amounts exactly divisible by 1,000 (> ₹50k)
  - **Dormant-then-burst** — 20 vendors go silent 60+ days then make 5 payments in 3 days
- Fixed `random.seed(42)` for full reproducibility

**`load_raw.py`:**
- Parses `PROCUREIQ_DB_URL` env var for connection
- Truncates in reverse FK order, inserts in forward FK order
- Uses PostgreSQL `COPY` (not INSERT) for bulk loading — ~10x faster
- Fully idempotent — safe to re-run anytime
- Loaded: 500 / 10,000 / 12,000 / 10,093 rows confirmed

---

## Issues Encountered & Fixes

| Issue | Root Cause | Fix |
|---|---|---|
| `docker-compose up` failing with EOF | Docker Hub CloudFront CDN poor connectivity from Indian ISP | Added `registry-mirrors: ["https://mirror.gcr.io"]` + `mtu: 1450` + `dns: [8.8.8.8]` to daemon.json (at top level, not inside `builder` block) |
| `daemon.json` DNS/MTU settings ignored | Settings were nested inside `"builder": {}` block instead of top-level | Moved to top level — fixed |
| `scikit-learn==1.4.2` install failed | `apache/airflow:2.8.0` default tag uses Python 3.8; sklearn 1.4.x requires Python ≥3.9 | Switched to `apache/airflow:2.8.0-python3.11` |
| `git push` not working | GitHub no longer accepts password auth; needed token-based auth | Installed GitHub CLI (`winget install GitHub.cli`), ran `gh auth login` |

---

## Current State
- Docker stack: running
- Raw layer: populated
- GitHub: both Phase 1 + Phase 2 commits pushed to `YashAbhyankar/procureiq`

---

## Next Session — Phase 3 (dbt)
**Goal:** `dbt run && dbt test` all green

Files to create:
- `dbt_project/dbt_project.yml` + `profiles.yml`
- Staging models: `stg_vendors`, `stg_payments`, `stg_invoices`, `stg_purchase_orders`
- Intermediate models: `int_vendor_payment_stats`, `int_vendor_payment_joined`
- Mart models: `vendor_risk_summary`, `payment_anomaly_flags`
- `schema.yml` tests + `calculate_days_late` macro

Resume trigger: *"Continue ProcureIQ — Phase 2 done, let's start Phase 3"*
