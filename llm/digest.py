"""
ProcureIQ — LLM Risk Digest  (Phase 6)
Pulls top vendors by risk score + their SHAP values, builds a prompt,
calls the configured LLM provider, and writes the narrative to
warehouse.llm_risk_digest.

Provider is controlled by LLM_PROVIDER env var:
    groq (default) → llama-3.3-70b-versatile  (free tier, 128k context)
    claude         → claude-sonnet-4-20250514
    openrouter     → meta-llama/llama-3.3-70b-instruct

Run via:
    docker-compose exec airflow-scheduler python /opt/llm/digest.py
"""

import json
import os
from datetime import date

import pandas as pd
from sqlalchemy import create_engine, text

DB_URL = os.getenv(
    "PROCUREIQ_DB_URL",
    "postgresql+psycopg2://procureiq:procureiq_dev_password@postgres/procureiq",
)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
TOP_N = 5


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_context(engine) -> dict:
    top_vendors = pd.read_sql(f"""
        SELECT vendor_id, vendor_name, category, risk_score, risk_label,
               anomaly_score, avg_days_late, payment_count, dispute_rate,
               shap_values
        FROM warehouse.vendor_risk_summary
        WHERE risk_label = 'high'
        ORDER BY risk_score DESC
        LIMIT {TOP_N}
    """, engine)

    risk_summary = pd.read_sql("""
        SELECT risk_label, COUNT(*) AS vendor_count
        FROM warehouse.vendor_risk_summary
        GROUP BY risk_label
        ORDER BY risk_label
    """, engine)

    anomaly_counts = pd.read_sql("""
        SELECT anomaly_type, COUNT(*) AS count
        FROM warehouse.payment_anomaly_flags
        GROUP BY anomaly_type
        ORDER BY count DESC
    """, engine)

    total_flagged = int(pd.read_sql(
        "SELECT COUNT(*) AS n FROM warehouse.payment_anomaly_flags", engine
    )["n"].iloc[0])

    return {
        "top_vendors": top_vendors,
        "risk_summary": risk_summary,
        "anomaly_counts": anomaly_counts,
        "total_flagged": total_flagged,
    }


# ── Prompt construction ───────────────────────────────────────────────────────

def build_prompt(ctx: dict) -> str:
    risk_lines = [
        f"  {row['risk_label']}: {row['vendor_count']} vendors"
        for _, row in ctx["risk_summary"].iterrows()
    ]

    anomaly_lines = [
        f"  {row['anomaly_type']}: {row['count']} payments"
        for _, row in ctx["anomaly_counts"].iterrows()
    ] or ["  none"]

    vendor_blocks = []
    for _, v in ctx["top_vendors"].iterrows():
        shap = v["shap_values"] or {}
        if isinstance(shap, str):
            shap = json.loads(shap)
        top_drivers = ", ".join(
            f"{k}={float(val):+.3f}" for k, val in list(shap.items())[:3]
        )
        vendor_blocks.append(
            f"- {v['vendor_name']} ({v['category']}): "
            f"risk_score={float(v['risk_score']):.3f}, "
            f"avg_days_late={float(v['avg_days_late']):.1f}, "
            f"dispute_rate={float(v['dispute_rate']):.1%}, "
            f"payment_count={int(v['payment_count'])}, "
            f"top_shap_drivers=[{top_drivers}]"
        )

    return f"""You are a procurement risk analyst at an Indian fintech company. Write a concise daily risk digest (180-220 words) for the finance team based on today's pipeline results.

VENDOR RISK BREAKDOWN (total 500 vendors):
{chr(10).join(risk_lines)}

FLAGGED PAYMENTS: {ctx['total_flagged']} total
{chr(10).join(anomaly_lines)}

TOP {len(vendor_blocks)} HIGH-RISK VENDORS (ranked by risk score):
{chr(10).join(vendor_blocks)}

SHAP driver interpretation: positive values increase the risk prediction, negative values decrease it. Key features: avg_days_late (payment delays), dispute_rate (invoice disputes), payment_count (transaction volume), days_since_last_payment (recency), stddev_payment_amount (payment variability).

Write flowing prose only — no bullet points, no headers. Structure:
1. Open with the overall picture (high-risk count, flagged payments).
2. Name the most critical 2-3 vendors and explain WHY they are risky using their SHAP drivers.
3. Note any notable anomaly patterns (e.g., a cluster of round-number fraud).
4. Close with a single, specific recommended action for the finance team.
"""


# ── LLM provider dispatch ─────────────────────────────────────────────────────

def call_groq(prompt: str) -> tuple:
    from openai import OpenAI
    client = OpenAI(
        api_key=os.getenv("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1",
    )
    model = "llama-3.3-70b-versatile"
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=450,
    )
    return resp.choices[0].message.content.strip(), model


def call_claude(prompt: str) -> tuple:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
    model = "claude-sonnet-4-20250514"
    msg = client.messages.create(
        model=model,
        max_tokens=450,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip(), model


def call_openrouter(prompt: str) -> tuple:
    from openai import OpenAI
    client = OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )
    model = "meta-llama/llama-3.3-70b-instruct"
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=450,
    )
    return resp.choices[0].message.content.strip(), model


def call_llm(prompt: str) -> tuple:
    if LLM_PROVIDER == "groq":
        return call_groq(prompt)
    elif LLM_PROVIDER == "claude":
        return call_claude(prompt)
    elif LLM_PROVIDER == "openrouter":
        return call_openrouter(prompt)
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {LLM_PROVIDER!r}. Valid options: groq | claude | openrouter"
        )


# ── DB write ──────────────────────────────────────────────────────────────────

def write_digest(engine, narrative: str, model_version: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO warehouse.llm_risk_digest
                (narrative, run_date, model_version, provider)
            VALUES
                (:narrative, :run_date, :model_version, :provider)
        """), {
            "narrative":     narrative,
            "run_date":      str(date.today()),
            "model_version": model_version,
            "provider":      LLM_PROVIDER,
        })


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"LLM Digest — provider: {LLM_PROVIDER}")
    engine = create_engine(DB_URL)

    print("Fetching risk context from warehouse...")
    ctx = fetch_context(engine)

    high_df = ctx["top_vendors"]
    print(f"  {len(high_df)} high-risk vendor(s) available (capped at {TOP_N})")

    if len(high_df) == 0:
        print("  No high-risk vendors found — skipping digest.")
        return

    prompt = build_prompt(ctx)

    print(f"\nCalling {LLM_PROVIDER}...")
    print("─" * 60)
    narrative, model_version = call_llm(prompt)
    print(narrative)
    print("─" * 60)

    print(f"\nWriting digest to warehouse.llm_risk_digest...")
    write_digest(engine, narrative, model_version)
    print(f"  ✓ Saved  (provider={LLM_PROVIDER}, model={model_version})")
    print("\nDigest complete.")


if __name__ == "__main__":
    main()
