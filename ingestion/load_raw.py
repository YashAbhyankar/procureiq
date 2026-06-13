"""
ProcureIQ — Raw Layer Loader
Truncates and bulk-loads raw.* tables from CSVs in /opt/data/raw/.
Idempotent: safe to run multiple times — always produces a clean load.

Run via:
    docker-compose exec airflow-scheduler python /opt/ingestion/load_raw.py
"""
import os
from io import StringIO
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import psycopg2

DB_URL  = os.getenv("PROCUREIQ_DB_URL", "postgresql+psycopg2://procureiq:procureiq_dev_password@postgres/procureiq")
DATA_DIR = Path(os.getenv("DATA_DIR", "/opt/data/raw"))

# Tables in FK dependency order — insert order; reverse for truncation.
# Each entry: (csv_filename_stem, schema.table, [columns to load])
TABLES = [
    (
        "vendors",
        "raw.vendors",
        ["vendor_id", "vendor_name", "category", "credit_tier",
         "registration_date", "is_active", "contact_email"],
    ),
    (
        "purchase_orders",
        "raw.purchase_orders",
        ["po_id", "vendor_id", "po_date", "total_amount", "status", "department"],
    ),
    (
        "invoices",
        "raw.invoices",
        ["invoice_id", "po_id", "vendor_id", "invoice_date",
         "amount", "due_date", "status"],
    ),
    (
        "payments",
        "raw.payments",
        ["payment_id", "invoice_id", "vendor_id",
         "payment_date", "amount", "is_disputed"],
    ),
]


def get_connection() -> psycopg2.extensions.connection:
    url = DB_URL.replace("postgresql+psycopg2://", "postgresql://")
    parsed = urlparse(url)
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        dbname=parsed.path.lstrip("/"),
    )


def bulk_copy(cur, df: pd.DataFrame, qualified_table: str, columns: list) -> None:
    """
    Streams a DataFrame into Postgres via COPY — much faster than executemany/INSERT.
    COPY reads a CSV from stdin; no SQL parsing overhead per row.
    """
    buffer = StringIO()
    df[columns].to_csv(buffer, index=False, header=False, na_rep="")
    buffer.seek(0)
    col_list = ", ".join(columns)
    cur.copy_expert(
        f"COPY {qualified_table} ({col_list}) FROM STDIN WITH CSV NULL ''",
        buffer,
    )


def main():
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # Truncate in REVERSE FK order: payments → invoices → POs → vendors.
        # CASCADE handles any remaining FK references automatically.
        print("Truncating existing data...")
        tables_to_truncate = ", ".join(t[1] for t in reversed(TABLES))
        cur.execute(f"TRUNCATE {tables_to_truncate} RESTART IDENTITY CASCADE")
        print("  ✓ All raw tables cleared")

        # Insert in FORWARD FK order: vendors → POs → invoices → payments.
        print("\nLoading CSVs...")
        for csv_stem, qualified_table, columns in TABLES:
            csv_path = DATA_DIR / f"{csv_stem}.csv"
            if not csv_path.exists():
                raise FileNotFoundError(
                    f"{csv_path} not found — run generate_data.py first"
                )
            df = pd.read_csv(csv_path)
            bulk_copy(cur, df, qualified_table, columns)
            print(f"  ✓ {len(df):>7,} rows → {qualified_table}")

        conn.commit()
        print("\nLoad complete. All raw tables populated.")

    except Exception as exc:
        conn.rollback()
        print(f"\nERROR — transaction rolled back: {exc}")
        raise

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
