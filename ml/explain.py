"""
ProcureIQ — SHAP Explanation
Loads the production RandomForest from MLflow and computes per-feature SHAP
values for every high-risk vendor. Results are written to the shap_values JSONB
column in warehouse.vendor_risk_summary so Streamlit can display them.

A global summary plot is also saved as an MLflow artifact.

Run via:
    docker-compose exec airflow-scheduler python /opt/ml/explain.py
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
import shap
from sqlalchemy import create_engine, text

DB_URL     = os.getenv("PROCUREIQ_DB_URL", "postgresql+psycopg2://procureiq:procureiq_dev_password@postgres/procureiq")
MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")

FEATURES = [
    "avg_days_late",
    "payment_count",
    "dispute_rate",
    "days_since_last_payment",
    "po_to_payment_ratio",
    "stddev_payment_amount",
    "credit_tier_encoded",
    "category_encoded",
]
CREDIT_TIER_MAP = {"A": 0, "B": 1, "C": 2}


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["credit_tier_encoded"] = df["credit_tier"].map(CREDIT_TIER_MAP).fillna(1)
    categories = sorted(df["category"].dropna().unique())
    cat_map = {c: i for i, c in enumerate(categories)}
    df["category_encoded"] = df["category"].map(cat_map).fillna(0)
    return df


def main():
    mlflow.set_tracking_uri(MLFLOW_URI)
    engine = create_engine(DB_URL)

    print("Loading production model from MLflow...")
    model = mlflow.sklearn.load_model("models:/vendor_risk_scorer/Production")
    print("  ✓ vendor_risk_scorer loaded")

    print("\nLoading vendor data...")
    stats   = pd.read_sql("SELECT * FROM warehouse.int_vendor_payment_stats", engine)
    vendors = pd.read_sql("SELECT vendor_id, credit_tier, category FROM warehouse.stg_vendors", engine)
    df = stats.merge(vendors, on="vendor_id", how="left")
    df = engineer_features(df)

    risk_df = pd.read_sql("""
        SELECT vendor_id FROM warehouse.vendor_risk_summary
        WHERE risk_label = 'high'
        ORDER BY risk_score DESC
    """, engine)
    high_risk_ids = set(risk_df["vendor_id"].tolist())
    explain_df = df[df["vendor_id"].isin(high_risk_ids)].copy().reset_index(drop=True)
    print(f"  {len(explain_df)} high-risk vendors to explain")

    X = explain_df[FEATURES].fillna(0).values

    print("\nComputing SHAP values (TreeExplainer)...")
    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X)

    classes  = list(model.classes_)
    high_idx = classes.index("high") if "high" in classes else 0

    # Older SHAP: list of (n_samples, n_features) arrays, one per class
    # Newer SHAP: single ndarray of shape (n_samples, n_features, n_classes)
    if isinstance(shap_vals, list):
        shap_high = shap_vals[high_idx]
    else:
        shap_high = shap_vals[:, :, high_idx]   # shape: (n_vendors, n_features)

    print(f"  ✓ SHAP computed — classes: {classes}, explaining index {high_idx} ('high')")

    print("\nWriting SHAP values to warehouse.vendor_risk_summary...")
    with engine.begin() as conn:
        for pos, (_, row) in enumerate(explain_df.iterrows()):
            shap_dict = {
                feat: round(float(shap_high[pos][j]), 6)
                for j, feat in enumerate(FEATURES)
            }
            # Sort by absolute value so Streamlit renders most influential feature first
            shap_sorted = dict(
                sorted(shap_dict.items(), key=lambda kv: abs(kv[1]), reverse=True)
            )
            conn.execute(text("""
                UPDATE warehouse.vendor_risk_summary
                SET shap_values = :sv
                WHERE vendor_id = :vid
            """), {
                "vid": row["vendor_id"],
                "sv":  json.dumps(shap_sorted),
            })
    print(f"  ✓ {len(explain_df)} vendors updated")

    print("\nLogging SHAP summary plot to MLflow...")
    with mlflow.start_run(run_name="shap_explanation"):
        shap.summary_plot(shap_high, explain_df[FEATURES], show=False)
        plt.title("SHAP Feature Importance — High-Risk Vendors")
        plt.tight_layout()
        plt.savefig("/tmp/shap_summary.png", bbox_inches="tight", dpi=150)
        mlflow.log_artifact("/tmp/shap_summary.png")
        plt.close()

        mean_shap = np.abs(shap_high).mean(axis=0)
        for feat, val in zip(FEATURES, mean_shap):
            mlflow.log_metric(f"mean_shap_{feat}", round(float(val), 6))

    print("  ✓ shap_summary.png → MLflow artifacts")
    print("\nExplanation complete.")


if __name__ == "__main__":
    main()
