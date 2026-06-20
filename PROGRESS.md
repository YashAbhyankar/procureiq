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

## Phase 4 — ML Layer ✅ DONE
**Goal:** Models trained, tracked in MLflow, scores in warehouse

- [x] `ml/train_anomaly.py` — IsolationForest trained, v1 → Production ✓
- [x] `ml/train_risk.py` — RandomForest trained, v1 → Production ✓
- [x] `ml/score.py` — 505 payments flagged, 500 vendors scored ✓
- [x] `ml/explain.py` — SHAP values for 31 high-risk vendors written to warehouse ✓

**Fixes applied (2026-06-20):**
- `score.py`: replaced `ON CONFLICT` upsert with TRUNCATE + plain INSERT (no unique constraint on payment_id)
- `score.py` + `explain.py`: replaced `engine.connect()` + `conn.commit()` with `engine.begin()` (SQLAlchemy 1.x API)
- `explain.py`: SHAP returns 3D ndarray `(n_samples, n_features, n_classes)` in this version — fixed extraction to `shap_vals[:, :, high_idx]`

---

## Phase 5 — Airflow DAG ✅ DONE
**Goal:** Full DAG runs end-to-end on manual trigger

- [x] `airflow/dags/procureiq_dag.py` — 7 tasks, schedule `0 6 * * *`
- [x] All 7 tasks green on manual trigger (clean run after full reset)

**Fixes applied (2026-06-21):**
- Dropped stale `stg_invoices__dbt_backup` and `stg_vendors__dbt_backup` relations left by previous interrupted dbt run
- Verified clean end-to-end run after `docker-compose down -v` reset

---

## Phase 6 — LLM Digest ✅ DONE
**Goal:** Narrative written to `warehouse.llm_risk_digest`

- [x] `llm/digest.py` — full implementation (fetch → prompt → LLM → DB write)
- [x] Groq provider tested and working (`llama-3.3-70b-versatile`)
- [x] Digest saved to `warehouse.llm_risk_digest` — verified end-to-end

**Design:** OpenAI SDK used for Groq + OpenRouter (both OpenAI-compatible). Anthropic SDK used for Claude. `LLM_PROVIDER` env var dispatches between the three. SHAP values embedded in prompt so LLM explains *why* vendors are risky, not just that they are.

**Note:** `docker-compose restart` does NOT pick up `.env` changes — must use `docker-compose up -d --force-recreate` to inject updated keys into running containers.

---

## Phase 7 — Streamlit Frontend ✅ DONE
**Goal:** localhost:8501 — all 3 pages live with real data

- [x] `frontend/app.py` — 3 pages: Risk Dashboard, Payment Anomalies, LLM Digest
- [x] `frontend/Dockerfile` — pinned `httpx==0.27.2` to fix openai/httpx version conflict
- [x] Risk Dashboard: 5 metric cards, risk distribution bar, risk vs days-late scatter, SHAP attribution chart per vendor, high-risk table
- [x] Payment Anomalies: 4 metric cards, anomaly type bar, flagged payments over time, filterable table
- [x] LLM Digest: latest digest card, history expander, multi-turn chat with 6 starter chips
- [x] Chat: full conversation history passed as messages array (multi-turn), all 31 high-risk vendors in context, vendor deep-dive on name mention, pipeline + SHAP semantics in system prompt

**Fixes applied:**
- `httpx==0.27.2` pinned — `openai==1.23.2` breaks with `httpx>=0.28` (dropped `proxies` kwarg)
- LLM env vars added to Streamlit service in `docker-compose.yml` (were only in Airflow)
- `docker-compose restart` does not reload `.env` — must use `up -d --force-recreate`

---

## Phase 8 — README & GitHub Polish ✅ DONE
**Goal:** Repo ready to share with hiring managers

- [x] `README.md` — architecture diagram, tech stack, quick start, pipeline walkthrough, design decisions
- [ ] Add real screenshots to README (Risk Dashboard, Payment Anomalies, LLM Digest + Chat)
- [ ] Final push to GitHub
