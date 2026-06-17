"""
ProcureIQ — Vendor Risk Scorer Training
Trains a RandomForestClassifier to score vendors as low / medium / high risk.

Since we generated the data ourselves (no historical ground truth), we create
synthetic risk labels using business rules first, then train the model on those.
The model then generalises the rules to new, unseen vendor profiles.

Features: per-vendor aggregates from int_vendor_payment_stats + credit_tier/category.
Labels:   derived from avg_days_late, dispute_rate, days_since_last_payment, credit_tier.

Run via:
    docker-compose exec airflow-scheduler python /opt/ml/train_risk.py
"""
import json
import os

import matplotlib
matplotlib.use("Agg")   # non-interactive backend for Docker
import matplotlib.pyplot as plt
import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.tracking import MlflowClient
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import ConfusionMatrixDisplay, classification_report, f1_score
from sklearn.model_selection import cross_val_score
from sqlalchemy import create_engine

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


def encode_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["credit_tier_encoded"] = df["credit_tier"].map(CREDIT_TIER_MAP).fillna(1)
    # Sort alphabetically so encoding is deterministic across train + score runs
    categories = sorted(df["category"].dropna().unique())
    cat_map = {c: i for i, c in enumerate(categories)}
    df["category_encoded"] = df["category"].map(cat_map).fillna(0)
    return df


def label_risk(row) -> str:
    """
    Business-rule label generator. Combines four risk signals into a score,
    then buckets into low/medium/high. The RandomForest learns to generalise
    this rule to new vendor profiles it hasn't seen.
    """
    score = 0
    if row["avg_days_late"] > 30:            score += 2
    elif row["avg_days_late"] > 15:          score += 1
    if row["dispute_rate"] > 0.08:           score += 2
    elif row["dispute_rate"] > 0.04:         score += 1
    if row["days_since_last_payment"] > 90:  score += 1
    if row["credit_tier_encoded"] == 2:      score += 1   # tier C = highest credit risk

    if score >= 4:   return "high"
    elif score >= 2: return "medium"
    else:            return "low"


def main():
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment("vendor_risk_scoring")

    engine = create_engine(DB_URL)

    print("Loading vendor data from warehouse...")
    stats   = pd.read_sql("SELECT * FROM warehouse.int_vendor_payment_stats", engine)
    vendors = pd.read_sql("SELECT vendor_id, credit_tier, category FROM warehouse.stg_vendors", engine)
    df = stats.merge(vendors, on="vendor_id", how="left")
    df = encode_features(df)
    df["risk_label"] = df.apply(label_risk, axis=1)

    label_counts = df["risk_label"].value_counts().to_dict()
    print(f"  {len(df):,} vendors — label distribution: {label_counts}")

    X = df[FEATURES].fillna(0).values
    y = df["risk_label"].values

    with mlflow.start_run(run_name="random_forest"):
        mlflow.log_params({
            "model":              "RandomForestClassifier",
            "n_estimators":       200,
            "max_depth":          8,
            "class_weight":       "balanced",
            "random_state":       42,
            "features":           json.dumps(FEATURES),
            "n_samples":          len(X),
            "label_distribution": json.dumps(label_counts),
        })

        clf = RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            random_state=42,
            class_weight="balanced",   # handles class imbalance without oversampling
        )

        print("Training RandomForest...")
        clf.fit(X, y)

        y_pred = clf.predict(X)
        f1     = f1_score(y, y_pred, average="macro")
        cv_f1  = cross_val_score(clf, X, y, cv=5, scoring="f1_macro").mean()

        mlflow.log_metrics({
            "train_f1_macro": round(f1, 4),
            "cv_f1_macro":    round(cv_f1, 4),
        })

        print(f"  Train F1 (macro): {f1:.4f}")
        print(f"  CV F1 (macro):    {cv_f1:.4f}")
        print(classification_report(y, y_pred))

        # Confusion matrix → MLflow artifact (visible in the UI)
        fig, ax = plt.subplots(figsize=(6, 5))
        ConfusionMatrixDisplay.from_predictions(y, y_pred, ax=ax, colorbar=False)
        ax.set_title("Vendor Risk — Confusion Matrix")
        fig.savefig("/tmp/confusion_matrix.png", bbox_inches="tight")
        mlflow.log_artifact("/tmp/confusion_matrix.png")
        plt.close()

        # Feature importances → artifact
        feat_imp = (
            pd.Series(clf.feature_importances_, index=FEATURES)
            .sort_values(ascending=False)
        )
        feat_imp.to_csv("/tmp/feature_importance.csv")
        mlflow.log_artifact("/tmp/feature_importance.csv")
        print("Feature importances:")
        print(feat_imp.to_string())

        mlflow.sklearn.log_model(
            clf,
            "model",
            registered_model_name="vendor_risk_scorer",
        )

    client = MlflowClient()
    latest = client.get_latest_versions("vendor_risk_scorer", stages=["None"])[0]
    client.transition_model_version_stage(
        name="vendor_risk_scorer", version=latest.version, stage="Production"
    )
    print(f"  Model v{latest.version} → Production")
    print("Done.")


if __name__ == "__main__":
    main()
