"""
ProcureIQ — Main Orchestration DAG
Runs the full vendor risk pipeline daily at 6am (IST-friendly UTC offset).

Task chain:
    ingest_raw → dbt_run → dbt_test → score_models → explain_models → llm_digest → notify_complete

Each stage is a BashOperator that delegates to the relevant Python script or dbt command.
If any task fails, downstream tasks are skipped and the run is marked failed in the UI.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "procureiq",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
    "email_on_retry": False,
}

with DAG(
    dag_id="procureiq_pipeline",
    description="Vendor risk pipeline: ingest → dbt → ML score → SHAP → LLM digest",
    schedule_interval="0 6 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["procureiq", "ml", "dbt"],
) as dag:

    # ── 1. Raw ingestion ───────────────────────────────────────────────────────
    # Truncates raw tables and reloads from generated CSVs/data — idempotent
    ingest_raw = BashOperator(
        task_id="ingest_raw",
        bash_command="python /opt/ingestion/load_raw.py",
    )

    # ── 2. dbt run ────────────────────────────────────────────────────────────
    # Rebuilds all staging, intermediate, and mart models
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command="dbt run --project-dir /opt/dbt --profiles-dir /opt/dbt",
    )

    # ── 3. dbt test ───────────────────────────────────────────────────────────
    # Runs all schema tests — pipeline stops here if data quality fails
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command="dbt test --project-dir /opt/dbt --profiles-dir /opt/dbt",
    )

    # ── 4. ML scoring ─────────────────────────────────────────────────────────
    # IsolationForest → payment_anomaly_flags, RandomForest → vendor_risk_summary
    score_models = BashOperator(
        task_id="score_models",
        bash_command="GIT_PYTHON_REFRESH=quiet python /opt/ml/score.py",
    )

    # ── 5. SHAP explanation ───────────────────────────────────────────────────
    # Writes per-feature attributions for high-risk vendors → shap_values JSONB
    explain_models = BashOperator(
        task_id="explain_models",
        bash_command="GIT_PYTHON_REFRESH=quiet python /opt/ml/explain.py",
    )

    # ── 6. LLM digest ─────────────────────────────────────────────────────────
    # Calls Groq/Claude → writes narrative to warehouse.llm_risk_digest
    llm_digest = BashOperator(
        task_id="llm_digest",
        bash_command="python /opt/llm/digest.py",
    )

    # ── 7. Notify complete ────────────────────────────────────────────────────
    def _notify(**context):
        logical_date = context["logical_date"]
        run_id       = context["run_id"]
        print("=" * 60)
        print(f"  ProcureIQ pipeline complete")
        print(f"  Date    : {logical_date.date()}")
        print(f"  Run ID  : {run_id}")
        print("=" * 60)

    notify_complete = PythonOperator(
        task_id="notify_complete",
        python_callable=_notify,
    )

    # ── Dependency chain ──────────────────────────────────────────────────────
    ingest_raw >> dbt_run >> dbt_test >> score_models >> explain_models >> llm_digest >> notify_complete
