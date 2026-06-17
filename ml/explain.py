"""
ProcureIQ — SHAP Explainability
Computes SHAP (SHapley Additive exPlanations) values for the top 10 vendors
by risk_score and stores them as JSON in vendor_risk_summary.shap_values.

SHAP tells us WHY the model scored a vendor as high risk — which feature
contributed most. This powers the waterfall chart in the Streamlit frontend.

Run via:
    docker-compose exec airflow-scheduler python /opt/ml/explain.py
"""
import json
import os

import mlflow
import mlflow.sklearn
import pandas as pd
import shap
from sqlalchemy import create_engine, text

DB_URL     = os.getenv("PROCUREIQ_DB_URL", "postgresql+psycopg2://procureiq:procureiq_dev_password@postgres/procureiq")
MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")

RISK_FEATURES = [
    "avg_days_late", "payment_count", "dispute_rate",
    "days_since_last_payment", "po_to_payment_ratio", "stddev_payment_amount",
    "credit_tier_encoded", "category_encoded",
]
CREDIT_TIER_MAP = {"A": 0, "B": 1, "C": 2}
TOP_N = 10


def main():
    mlflow.set_tracking_uri(MLFLOW_URI)
    engine = create_engine(DB_URL)

    print("Loading production risk model...")
    model = mlflow.sklearn.load_model("models:/vendor_risk_scorer/Production")

    print(f"Loading top {TOP_N} vendors by risk score...")
    top_ids = pd.read_sql(f"""
        SELECT vendor_id FROM warehouse.vendor_risk_summary
        ORDER BY risk_score DESC NULLS LAST
        LIMIT {TOP_N}
    """, engine)

    if top_ids.empty:
        print("No scored vendors found — run score.py first.")
        return

    # Load full feature set (must match train_risk.py encoding exactly)
    stats_df   = pd.read_sql("SELECT * FROM warehouse.int_vendor_payment_stats", engine)
    vendors_df = pd.read_sql("SELECT vendor_id, credit_tier, category FROM warehouse.stg_vendors", engine)
    df = stats_df.merge(vendors_df, on="vendor_id", how="left")

    df["credit_tier_encoded"] = df["credit_tier"].map(CREDIT_TIER_MAP).fillna(1)
    categories = sorted(df["category"].dropna().unique())
    cat_map    = {c: i for i, c in enumerate(categories)}
    df["category_encoded"] = df["category"].map(cat_map).fillna(0)

    top_df = df[df["vendor_id"].isin(top_ids["vendor_id"].tolist())].reset_index(drop=True)
    X_top  = top_df[RISK_FEATURES].fillna(0).values

    print(f"  Computing SHAP values for {len(top_df)} vendors...")
    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X_top)

    # For multi-class RF, shap_values is a list — one array per class.
    # We use the 'high' risk class to show what drives high-risk predictions.
    classes  = list(model.classes_)
    high_idx = classes.index("high") if "high" in classes else 0
    high_shap = shap_vals[high_idx] if isinstance(shap_vals, list) else shap_vals

    with engine.connect() as conn:
        for idx, row in top_df.iterrows():
            shap_dict = {
                feat: round(float(high_shap[idx, j]), 6)
                for j, feat in enumerate(RISK_FEATURES)
            }
            conn.execute(text("""
                UPDATE warehouse.vendor_risk_summary
                SET shap_values = :shap::JSONB
                WHERE vendor_id = :vid
            """), {
                "vid":  row["vendor_id"],
                "shap": json.dumps(shap_dict),
            })
        conn.commit()

    print(f"  ✓ SHAP values written for {len(top_df)} vendors")
    print("Explanation complete.")


if __name__ == "__main__":
    main()
