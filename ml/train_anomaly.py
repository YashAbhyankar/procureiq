"""
ProcureIQ — Anomaly Detector Training
Trains an IsolationForest on payment-level features to detect the three
injected fraud patterns: velocity spike, round-number fraud, dormant-then-burst.

IsolationForest is unsupervised — no labels needed. It learns what "normal"
looks like and flags outliers. contamination=0.05 tells it to expect ~5% anomalies.

Run via:
    docker-compose exec airflow-scheduler python /opt/ml/train_anomaly.py
"""
import json
import os

import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.tracking import MlflowClient
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import create_engine

DB_URL    = os.getenv("PROCUREIQ_DB_URL", "postgresql+psycopg2://procureiq:procureiq_dev_password@postgres/procureiq")
MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")

FEATURES = [
    "amount",
    "days_late",
    "is_disputed_int",
    "payment_to_invoice_ratio",
    "amount_zscore",
    "daily_payment_count",
]
CONTAMINATION = 0.05


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["is_disputed_int"]          = df["is_disputed"].astype(int)
    df["days_late"]                = df["days_late"].fillna(0)
    df["payment_to_invoice_ratio"] = df["payment_to_invoice_ratio"].fillna(1.0)

    # How many payments this vendor made on the same day — spike detector
    df["daily_payment_count"] = (
        df.groupby(["vendor_id", "payment_date"])["payment_id"].transform("count")
    )

    # How far this payment's amount deviates from the vendor's typical amount
    vendor_stats = (
        df.groupby("vendor_id")["amount"]
        .agg(["mean", "std"])
        .rename(columns={"mean": "v_mean", "std": "v_std"})
    )
    df = df.join(vendor_stats, on="vendor_id")
    df["amount_zscore"] = (df["amount"] - df["v_mean"]) / df["v_std"].replace(0, 1).fillna(1)

    return df


def main():
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment("anomaly_detection")

    engine = create_engine(DB_URL)

    print("Loading payment data from warehouse...")
    df = pd.read_sql("SELECT * FROM warehouse.int_vendor_payment_joined", engine)
    print(f"  {len(df):,} payments loaded")

    df = engineer_features(df)
    X = df[FEATURES].fillna(0).values

    with mlflow.start_run(run_name="isolation_forest"):
        mlflow.log_params({
            "model":         "IsolationForest",
            "contamination": CONTAMINATION,
            "n_estimators":  100,
            "random_state":  42,
            "features":      json.dumps(FEATURES),
            "n_samples":     len(X),
        })

        # Wrap in pipeline so StandardScaler + model are saved together
        pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("clf",    IsolationForest(
                contamination=CONTAMINATION,
                n_estimators=100,
                random_state=42,
            )),
        ])

        print("Training IsolationForest...")
        pipeline.fit(X)

        preds     = pipeline.predict(X)
        n_flagged = int((preds == -1).sum())
        flag_rate = n_flagged / len(X)

        mlflow.log_metrics({
            "n_flagged": n_flagged,
            "flag_rate": round(flag_rate, 4),
        })

        print(f"  Flagged {n_flagged:,} payments ({flag_rate:.1%})")

        mlflow.sklearn.log_model(
            pipeline,
            "model",
            registered_model_name="anomaly_detector",
        )

    # Promote to Production so score.py can load it by alias
    client  = MlflowClient()
    latest  = client.get_latest_versions("anomaly_detector", stages=["None"])[0]
    client.transition_model_version_stage(
        name="anomaly_detector", version=latest.version, stage="Production"
    )
    print(f"  Model v{latest.version} → Production")
    print("Done.")


if __name__ == "__main__":
    main()
