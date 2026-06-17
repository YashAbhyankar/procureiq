"""
ProcureIQ — Scoring
Loads production models from MLflow registry and writes scores back to warehouse.

IsolationForest → flags anomalous payments → INSERT into warehouse.payment_anomaly_flags
RandomForest    → vendor risk scores       → UPDATE warehouse.vendor_risk_summary

Run via:
    docker-compose exec airflow-scheduler python /opt/ml/score.py
"""
import os

import mlflow
import mlflow.sklearn
import pandas as pd
from sqlalchemy import create_engine, text

DB_URL     = os.getenv("PROCUREIQ_DB_URL", "postgresql+psycopg2://procureiq:procureiq_dev_password@postgres/procureiq")
MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")

ANOMALY_FEATURES = [
    "amount", "days_late", "is_disputed_int",
    "payment_to_invoice_ratio", "amount_zscore", "daily_payment_count",
]
RISK_FEATURES = [
    "avg_days_late", "payment_count", "dispute_rate",
    "days_since_last_payment", "po_to_payment_ratio", "stddev_payment_amount",
    "credit_tier_encoded", "category_encoded",
]
CREDIT_TIER_MAP = {"A": 0, "B": 1, "C": 2}


# ── Feature engineering (must match train_*.py exactly) ───────────────────────

def engineer_anomaly_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["is_disputed_int"]          = df["is_disputed"].astype(int)
    df["days_late"]                = df["days_late"].fillna(0)
    df["payment_to_invoice_ratio"] = df["payment_to_invoice_ratio"].fillna(1.0)
    df["daily_payment_count"] = (
        df.groupby(["vendor_id", "payment_date"])["payment_id"].transform("count")
    )
    vendor_stats = (
        df.groupby("vendor_id")["amount"]
        .agg(["mean", "std"])
        .rename(columns={"mean": "v_mean", "std": "v_std"})
    )
    df = df.join(vendor_stats, on="vendor_id")
    df["amount_zscore"] = (df["amount"] - df["v_mean"]) / df["v_std"].replace(0, 1).fillna(1)
    return df


def engineer_risk_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["credit_tier_encoded"] = df["credit_tier"].map(CREDIT_TIER_MAP).fillna(1)
    categories = sorted(df["category"].dropna().unique())
    cat_map = {c: i for i, c in enumerate(categories)}
    df["category_encoded"] = df["category"].map(cat_map).fillna(0)
    return df


def classify_anomaly_type(row) -> str:
    """Heuristic label for flagged payments — used for display in Streamlit."""
    if row["daily_payment_count"] >= 8:
        return "velocity_spike"
    if row["amount"] >= 50_000 and row["amount"] % 1_000 == 0:
        return "round_number"
    return "dormant_burst"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    mlflow.set_tracking_uri(MLFLOW_URI)
    engine = create_engine(DB_URL)

    print("Loading production models from MLflow...")
    anomaly_model = mlflow.sklearn.load_model("models:/anomaly_detector/Production")
    risk_model    = mlflow.sklearn.load_model("models:/vendor_risk_scorer/Production")
    print("  ✓ anomaly_detector loaded")
    print("  ✓ vendor_risk_scorer loaded")

    # ── Payment scoring ───────────────────────────────────────────────────────
    print("\nScoring payments...")
    pay_df = pd.read_sql("SELECT * FROM warehouse.int_vendor_payment_joined", engine)
    pay_df = engineer_anomaly_features(pay_df)

    X_pay        = pay_df[ANOMALY_FEATURES].fillna(0).values
    preds        = anomaly_model.predict(X_pay)
    raw_scores   = anomaly_model.decision_function(X_pay)

    # Normalise to [0, 1]: higher = more anomalous
    norm_scores = 1 - (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min())

    pay_df["anomaly_prediction"] = preds
    pay_df["anomaly_score"]      = norm_scores

    flagged = pay_df[pay_df["anomaly_prediction"] == -1].copy()
    flagged["anomaly_type"] = flagged.apply(classify_anomaly_type, axis=1)
    print(f"  Flagged {len(flagged):,} / {len(pay_df):,} payments")
    print(f"  Anomaly types: {flagged['anomaly_type'].value_counts().to_dict()}")

    # Per-vendor anomaly score = worst payment score for that vendor
    vendor_anomaly = (
        pay_df.groupby("vendor_id")["anomaly_score"]
        .max()
        .reset_index()
        .rename(columns={"anomaly_score": "vendor_anomaly_score"})
    )

    # Bulk-insert flagged rows (dbt already cleared the table this run)
    with engine.connect() as conn:
        for _, row in flagged.iterrows():
            conn.execute(text("""
                INSERT INTO warehouse.payment_anomaly_flags
                    (payment_id, vendor_id, payment_date, amount, anomaly_score, anomaly_type)
                VALUES (:pid, :vid, :pdate, :amt, :score, :atype)
                ON CONFLICT (payment_id) DO UPDATE SET
                    anomaly_score = EXCLUDED.anomaly_score,
                    anomaly_type  = EXCLUDED.anomaly_type,
                    flagged_at    = NOW()
            """), {
                "pid":   row["payment_id"],
                "vid":   row["vendor_id"],
                "pdate": str(row["payment_date"]),
                "amt":   float(row["amount"]),
                "score": float(row["anomaly_score"]),
                "atype": row["anomaly_type"],
            })
        conn.commit()
    print(f"  ✓ {len(flagged):,} rows → warehouse.payment_anomaly_flags")

    # ── Vendor risk scoring ───────────────────────────────────────────────────
    print("\nScoring vendors...")
    stats_df   = pd.read_sql("SELECT * FROM warehouse.int_vendor_payment_stats", engine)
    vendors_df = pd.read_sql("SELECT vendor_id, credit_tier, category FROM warehouse.stg_vendors", engine)
    vend_df    = stats_df.merge(vendors_df, on="vendor_id", how="left")
    vend_df    = engineer_risk_features(vend_df)
    vend_df    = vend_df.merge(vendor_anomaly, on="vendor_id", how="left")
    vend_df["vendor_anomaly_score"] = vend_df["vendor_anomaly_score"].fillna(0)
    vend_df = vend_df.reset_index(drop=True)

    X_vend      = vend_df[RISK_FEATURES].fillna(0).values
    risk_labels = risk_model.predict(X_vend)
    risk_probs  = risk_model.predict_proba(X_vend)

    classes  = list(risk_model.classes_)
    high_idx = classes.index("high") if "high" in classes else 0
    risk_scores = risk_probs[:, high_idx]

    print(f"  Risk distribution: {pd.Series(risk_labels).value_counts().to_dict()}")

    with engine.connect() as conn:
        for idx, row in vend_df.iterrows():
            conn.execute(text("""
                UPDATE warehouse.vendor_risk_summary SET
                    risk_score    = :rs,
                    risk_label    = :rl,
                    anomaly_score = :as_,
                    scored_at     = NOW()
                WHERE vendor_id = :vid
            """), {
                "vid": row["vendor_id"],
                "rs":  float(risk_scores[idx]),
                "rl":  str(risk_labels[idx]),
                "as_": float(row["vendor_anomaly_score"]),
            })
        conn.commit()
    print(f"  ✓ {len(vend_df):,} vendors updated in warehouse.vendor_risk_summary")
    print("\nScoring complete.")


if __name__ == "__main__":
    main()
