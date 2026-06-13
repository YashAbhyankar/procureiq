"""
ProcureIQ — Synthetic Data Generator
Produces 4 CSVs to /opt/data/raw/ that mimic a real procurement system.

Run via:
    docker-compose exec airflow-scheduler python /opt/ingestion/generate_data.py
"""
import os
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from faker import Faker

fake = Faker("en_IN")   # Indian locale for realistic company/contact names
Faker.seed(42)
random.seed(42)         # Fixed seed → same data every run (reproducible ML experiments)

DATA_DIR = Path(os.getenv("DATA_DIR", "/opt/data/raw"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

CATEGORIES = [
    "Logistics", "IT Services", "Raw Materials", "Marketing",
    "Facilities", "Consulting", "Manufacturing", "Healthcare",
]
DEPARTMENTS = ["Finance", "Operations", "HR", "IT", "Procurement", "Legal"]


def rand_date(start: date, end: date) -> date:
    return start + timedelta(days=random.randint(0, (end - start).days))


# ─── Vendors ──────────────────────────────────────────────────────────────────

def generate_vendors(n: int = 500) -> pd.DataFrame:
    # Credit tier distribution: 40% A, 40% B, 20% C
    tiers = ["A"] * 200 + ["B"] * 200 + ["C"] * 100
    random.shuffle(tiers)

    rows = [
        {
            "vendor_id":          f"VND-{i+1:04d}",
            "vendor_name":        fake.company(),
            "category":           random.choice(CATEGORIES),
            "credit_tier":        tiers[i],
            "registration_date":  rand_date(date(2018, 1, 1), date(2022, 12, 31)),
            "is_active":          random.random() > 0.10,   # 90% active
            "contact_email":      fake.company_email(),
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows)


# ─── Purchase Orders ──────────────────────────────────────────────────────────

def generate_purchase_orders(vendors_df: pd.DataFrame, n: int = 10_000) -> pd.DataFrame:
    vendor_ids = vendors_df["vendor_id"].tolist()

    rows = [
        {
            "po_id":          f"PO-{i+1:05d}",
            "vendor_id":      random.choice(vendor_ids),
            "po_date":        rand_date(date(2022, 1, 1), date(2024, 6, 30)),
            "total_amount":   round(random.uniform(10_000, 500_000), 2),
            "status":         random.choices(
                                  ["closed", "open", "cancelled"],
                                  weights=[60, 30, 10]
                              )[0],
            "department":     random.choice(DEPARTMENTS),
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows)


# ─── Invoices ─────────────────────────────────────────────────────────────────

def generate_invoices(pos_df: pd.DataFrame, n: int = 12_000) -> pd.DataFrame:
    # Sample POs with replacement so we can have multiple invoices per PO
    sampled = pos_df.sample(n, replace=True).reset_index(drop=True)

    rows = []
    for i, po in sampled.iterrows():
        invoice_date = po["po_date"] + timedelta(days=random.randint(1, 30))
        rows.append(
            {
                "invoice_id":   f"INV-{i+1:06d}",
                "po_id":        po["po_id"],
                "vendor_id":    po["vendor_id"],    # denormalised for query convenience
                "invoice_date": invoice_date,
                "amount":       round(po["total_amount"] * random.uniform(0.10, 0.90), 2),
                "due_date":     invoice_date + timedelta(days=30),  # standard net-30
                "status":       random.choices(
                                    ["paid", "pending", "overdue"],
                                    weights=[70, 20, 10]
                                )[0],
            }
        )
    return pd.DataFrame(rows)


# ─── Payments ─────────────────────────────────────────────────────────────────
# Normal payments: ≤2 payments per vendor per day, amount = invoice amount.
# Anomalies are injected separately in three distinct patterns so the ML model
# has real signal to learn from.

def generate_payments(invoices_df: pd.DataFrame, n: int = 11_000) -> pd.DataFrame:
    # Only paid/overdue invoices realistically have payments
    payable = invoices_df[invoices_df["status"].isin(["paid", "overdue"])].copy()

    normal_rows = []
    anomaly_rows = []

    # ── Normal payments (95 % of n) ───────────────────────────────────────────
    normal_n = int(n * 0.95)
    sample = payable.sample(min(normal_n, len(payable)), replace=True)
    for _, inv in sample.iterrows():
        normal_rows.append(
            {
                "invoice_id":   inv["invoice_id"],
                "vendor_id":    inv["vendor_id"],
                "payment_date": inv["due_date"] + timedelta(days=random.randint(-5, 30)),
                "amount":       inv["amount"],
                "is_disputed":  random.random() < 0.04,     # 4 % baseline dispute rate
            }
        )

    # ── Anomaly 1: Velocity spike ─────────────────────────────────────────────
    # 15 vendors each make 10-12 payments on a single day (normal cap is ~2/day).
    # Signal: high payment_frequency on a specific date.
    spike_vendors = (
        payable["vendor_id"].drop_duplicates().sample(15).tolist()
    )
    for vendor_id in spike_vendors:
        vendor_inv = payable[payable["vendor_id"] == vendor_id]
        if len(vendor_inv) < 10:
            continue
        spike_date = rand_date(date(2023, 6, 1), date(2024, 3, 31))
        for _, inv in vendor_inv.sample(min(12, len(vendor_inv))).iterrows():
            anomaly_rows.append(
                {
                    "invoice_id":   inv["invoice_id"],
                    "vendor_id":    vendor_id,
                    "payment_date": spike_date,
                    "amount":       inv["amount"],
                    "is_disputed":  False,
                }
            )

    # ── Anomaly 2: Round-number fraud ─────────────────────────────────────────
    # ~180 payments with amounts exactly divisible by 1,000 and > 50,000.
    # Common in invoice fraud (fabricated invoices use round numbers).
    for _, inv in payable.sample(min(180, len(payable))).iterrows():
        anomaly_rows.append(
            {
                "invoice_id":   inv["invoice_id"],
                "vendor_id":    inv["vendor_id"],
                "payment_date": inv["due_date"] + timedelta(days=random.randint(0, 5)),
                "amount":       float(random.randint(50, 500) * 1_000),
                "is_disputed":  False,
            }
        )

    # ── Anomaly 3: Dormant-then-burst ─────────────────────────────────────────
    # 20 vendors go silent for 60+ days then make 5 payments within 3 days.
    # Signal: days_since_last_payment spike followed by high frequency.
    burst_vendors = (
        payable["vendor_id"].drop_duplicates().sample(20).tolist()
    )
    for vendor_id in burst_vendors:
        vendor_inv = payable[payable["vendor_id"] == vendor_id]
        if len(vendor_inv) < 5:
            continue
        burst_date = rand_date(date(2024, 1, 1), date(2024, 5, 31))
        for _, inv in vendor_inv.sample(min(5, len(vendor_inv))).iterrows():
            anomaly_rows.append(
                {
                    "invoice_id":   inv["invoice_id"],
                    "vendor_id":    vendor_id,
                    "payment_date": burst_date + timedelta(days=random.randint(0, 2)),
                    "amount":       inv["amount"],
                    "is_disputed":  False,
                }
            )

    # Combine and assign sequential IDs
    all_rows = normal_rows + anomaly_rows
    df = pd.DataFrame(all_rows)
    df.insert(0, "payment_id", [f"PAY-{i+1:06d}" for i in range(len(df))])
    return df


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Generating vendors...")
    vendors = generate_vendors(500)
    vendors.to_csv(DATA_DIR / "vendors.csv", index=False)
    print(f"  ✓ {len(vendors):,} rows → vendors.csv")

    print("Generating purchase orders...")
    pos = generate_purchase_orders(vendors, 10_000)
    pos.to_csv(DATA_DIR / "purchase_orders.csv", index=False)
    print(f"  ✓ {len(pos):,} rows → purchase_orders.csv")

    print("Generating invoices...")
    invoices = generate_invoices(pos, 12_000)
    invoices.to_csv(DATA_DIR / "invoices.csv", index=False)
    print(f"  ✓ {len(invoices):,} rows → invoices.csv")

    print("Generating payments (with injected anomalies)...")
    payments = generate_payments(invoices, 11_000)
    payments.to_csv(DATA_DIR / "payments.csv", index=False)
    print(f"  ✓ {len(payments):,} rows → payments.csv")

    total_anomalies = len(payments) - int(len(payments) * 0.95)
    print(f"\nSummary:")
    print(f"  vendors:         {len(vendors):,}")
    print(f"  purchase_orders: {len(pos):,}")
    print(f"  invoices:        {len(invoices):,}")
    print(f"  payments:        {len(payments):,}  (~{total_anomalies} anomalous)")
    print(f"\nFiles written to {DATA_DIR}")


if __name__ == "__main__":
    main()
