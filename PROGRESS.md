# ProcureIQ — Progress Tracker

_Update this file at the end of each session. Add comments, blockers, or notes below each phase._

---

## Phase 0 — Prerequisites ✅ DONE
- Docker Desktop installed (v29.5.3)
- Git installed (v2.54.0)
- Git identity configured (YashAbhyankar / yashabhyankar22@gmail.com)
- [ ] GitHub repo `procureiq` created and remote added ← do at end of Phase 1

---

## Phase 1 — Infrastructure & Schema ✅ DONE
**Goal:** `docker-compose up -d` → all services healthy, Postgres schema live

- [x] `.gitignore`
- [x] `.env.example`
- [x] `init_airflow.sql`
- [x] `init_db.sql`
- [x] `docker-compose.yml`
- [x] `airflow/Dockerfile`
- [x] `Makefile`
- [x] `frontend/` placeholder

Verification:
- [x] All 13/13 containers up
- [x] Airflow UI at localhost:8080 ✓
- [x] MLflow UI at localhost:5000 ✓
- [x] Streamlit at localhost:8501 ✓

**Notes:**
- Used `apache/airflow:2.8.0-python3.11` (not plain 2.8.0) — default tag is Python 3.8 which is incompatible with scikit-learn 1.4.x and dbt-core 1.7.x
- Fixed daemon.json MTU + DNS + registry mirror for Docker Hub CDN issues on Indian ISP

---

## Phase 2 — Data Generation & Ingestion ✅ DONE
**Goal:** Synthetic data in raw Postgres tables

- [x] `ingestion/generate_data.py`
- [x] `ingestion/load_raw.py`
- [x] Load verified: 500 vendors, 10,000 POs, 12,000 invoices, 10,093 payments (~505 anomalous)

**Notes:**
- Payments landed at 10,093 (not 11,000) — some vendors had too few invoices to fill anomaly batches; anomaly rate still ~5%
- 3 anomaly types injected: velocity spike (15 vendors), round-number fraud (180 payments), dormant-then-burst (20 vendors)

---

## Phase 3 — dbt Project ✅ DONE
**Goal:** `dbt run && dbt test` — all green

- [x] Staging models: stg_vendors, stg_purchase_orders, stg_invoices, stg_payments
- [x] Intermediate models: int_vendor_payment_joined, int_vendor_payment_stats
- [x] Mart models: vendor_risk_summary, payment_anomaly_flags
- [x] schema.yml — 22 tests (unique, not_null, relationships, accepted_values)
- [x] Macro: calculate_days_late
- [x] Singular test: assert_days_late_in_range (severity=warn)

Result: PASS=22 WARN=1 ERROR=0 — warning is expected (175 dormant-then-burst anomalies with days_late > 365)

---

## Phase 4 — ML Layer 🔄 IN PROGRESS
**Goal:** Models trained, tracked in MLflow, scores in warehouse

- [x] `ml/train_anomaly.py` — IsolationForest trained, v1 → Production ✓
- [x] `ml/train_risk.py` — RandomForest trained, v1 → Production ✓
- [ ] `ml/score.py` — errored, needs fix next session
- [ ] `ml/explain.py` — not run yet (runs after score.py works)

**Where we stopped (2026-06-14):**
- Both models registered and in Production in MLflow (localhost:5000 → Models tab)
- `score.py` threw an error — paste the error at start of next session to fix
- `explain.py` not attempted yet

**docker-compose fix applied this session:**
- Switched MLflow from named volume to bind mount `./mlflow/`
- Same bind mount added to Airflow containers — fixes `PermissionError: /mlflow`

**Resume trigger:** *"Continue ProcureIQ — Phase 4 in progress, score.py errored, let's fix it"*

---

## Phase 5 — Airflow DAG ⏳ PENDING
**Goal:** Full DAG runs end-to-end on manual trigger

- [ ] `airflow/dags/procureiq_dag.py`
- [ ] All 6 tasks green on manual trigger

---

## Phase 6 — LLM Digest ⏳ PENDING
**Goal:** Narrative written to `warehouse.llm_risk_digest`

- [ ] `llm/digest.py`
- [ ] Groq provider tested and working

---

## Phase 7 — Streamlit Frontend ⏳ PENDING
**Goal:** localhost:8501 — all 3 pages live with real data

- [ ] `frontend/app.py`
- [ ] `frontend/Dockerfile`

---

## Phase 8 — README & GitHub Polish ⏳ PENDING
**Goal:** Repo ready to share with hiring managers

- [ ] `README.md` (with real screenshots)
- [ ] Final push to GitHub
