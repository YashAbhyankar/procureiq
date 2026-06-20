"""
ProcureIQ — Streamlit Frontend
Pages: Risk Dashboard | Payment Anomalies | LLM Digest
"""
import json
import os

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import create_engine

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ProcureIQ",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_URL        = os.getenv("PROCUREIQ_DB_URL", "postgresql+psycopg2://procureiq:procureiq_dev_password@postgres/procureiq")
LLM_PROVIDER  = os.getenv("LLM_PROVIDER", "groq").lower()

RISK_COLORS = {"high": "#EF4444", "medium": "#F59E0B", "low": "#10B981"}

FEATURE_LABELS = {
    "avg_days_late":           "Avg Days Late",
    "payment_count":           "Payment Count",
    "dispute_rate":            "Dispute Rate",
    "days_since_last_payment": "Days Since Last Payment",
    "po_to_payment_ratio":     "PO to Payment Ratio",
    "stddev_payment_amount":   "Std Dev Payment Amount",
    "credit_tier_encoded":     "Credit Tier",
    "category_encoded":        "Category",
}


# ── DB helpers ────────────────────────────────────────────────────────────────
@st.cache_resource
def get_engine():
    return create_engine(DB_URL)


@st.cache_data(ttl=300)
def load_vendor_risk():
    return pd.read_sql(
        "SELECT * FROM warehouse.vendor_risk_summary ORDER BY risk_score DESC NULLS LAST",
        get_engine(),
    )


@st.cache_data(ttl=300)
def load_anomaly_flags():
    return pd.read_sql("""
        SELECT f.payment_id, f.vendor_id, v.vendor_name, f.payment_date,
               f.amount, f.anomaly_score, f.anomaly_type, f.flagged_at
        FROM warehouse.payment_anomaly_flags f
        LEFT JOIN warehouse.vendor_risk_summary v USING (vendor_id)
        ORDER BY f.anomaly_score DESC
    """, get_engine())


@st.cache_data(ttl=300)
def load_digests():
    return pd.read_sql(
        "SELECT * FROM warehouse.llm_risk_digest ORDER BY created_at DESC",
        get_engine(),
    )


# ── LLM dispatch ─────────────────────────────────────────────────────────────
def call_llm(messages: list) -> str:
    """
    messages: fully-formed [{role, content}] array including system prompt,
    injected DB context, full conversation history, and the current question.
    """
    if LLM_PROVIDER == "groq":
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1")
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.3,
            max_tokens=900,
        )
        return resp.choices[0].message.content.strip()

    elif LLM_PROVIDER == "claude":
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        # Anthropic expects system separate from messages
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        non_system = [m for m in messages if m["role"] != "system"]
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=900,
            system=system,
            messages=non_system,
        )
        return msg.content[0].text.strip()

    elif LLM_PROVIDER == "openrouter":
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENROUTER_API_KEY"), base_url="https://openrouter.ai/api/v1")
        resp = client.chat.completions.create(
            model="meta-llama/llama-3.3-70b-instruct",
            messages=messages,
            temperature=0.3,
            max_tokens=900,
        )
        return resp.choices[0].message.content.strip()

    else:
        return f"Unknown LLM_PROVIDER: {LLM_PROVIDER!r}. Set to groq | claude | openrouter."


def build_messages(context: str, chat_history: list, question: str) -> list:
    """
    Assembles the full message array for a multi-turn conversation:
      [system] → [context injection] → [prior Q&A turns] → [current question]
    The DB context is re-injected every turn so the LLM always has fresh data
    without needing to rely on what was said in prior turns.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Inject live DB snapshot as a synthetic first exchange so the LLM
    # treats it as background knowledge, not as a question to answer.
    messages.append({
        "role": "user",
        "content": f"[LIVE WAREHOUSE SNAPSHOT — refreshed each turn]\n{context}",
    })
    messages.append({
        "role": "assistant",
        "content": (
            "Understood — I have the current warehouse data loaded. "
            "I can answer questions about individual vendors, risk trends, anomaly patterns, "
            "payment behaviour, and how the risk scores and SHAP values are derived."
        ),
    })

    # Full conversation history except the latest user message (handled below)
    for msg in chat_history[:-1]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Current question
    messages.append({"role": "user", "content": question})
    return messages


def _vendor_line(v, flags_df, shap_top_n: int = 3) -> str:
    """Format one vendor row for the context block."""
    shap = v["shap_values"]
    driver = ""
    if shap:
        d = shap if isinstance(shap, dict) else json.loads(shap)
        driver = "; SHAP drivers: " + ", ".join(
            f"{FEATURE_LABELS.get(k, k)}={float(val):+.3f}" for k, val in list(d.items())[:shap_top_n]
        )
    n_flags = int((flags_df["vendor_id"] == v["vendor_id"]).sum())
    return (
        f"  - {v['vendor_name']} ({v['category']}): "
        f"risk={float(v['risk_score']):.3f}, "
        f"dispute_rate={float(v['dispute_rate']):.1%}, "
        f"avg_days_late={float(v['avg_days_late']):.1f}, "
        f"payments={int(v['payment_count'])}, "
        f"flagged_payments={n_flags}"
        f"{driver}"
    )


def build_chat_context(question: str) -> str:
    """
    Builds a rich DB snapshot to ground the LLM on every turn.
    Includes ALL high-risk vendors (for complete ranking/comparison answers),
    top-5 medium (for contrast), top-5 low (for 'best vendor' answers),
    and a full deep-dive block if the question names a specific vendor.
    """
    df    = load_vendor_risk()
    flags = load_anomaly_flags()

    risk_dist = df["risk_label"].value_counts().to_dict()
    flag_dist = flags["anomaly_type"].value_counts().to_dict()

    # All high-risk vendors (ranked by score) — enables full ranking questions
    high_rows  = df[df["risk_label"] == "high"]
    high_lines = [_vendor_line(v, flags) for _, v in high_rows.iterrows()]

    # Top 5 medium-risk — enables comparison questions ("how do medium vendors differ?")
    med_rows  = df[df["risk_label"] == "medium"].head(5)
    med_lines = [_vendor_line(v, flags, shap_top_n=2) for _, v in med_rows.iterrows()]

    # Top 5 low-risk (cleanest vendors) — enables "who should we prefer?" questions
    low_rows  = df[df["risk_label"] == "low"].sort_values("risk_score").head(5)
    low_lines = [
        f"  - {v['vendor_name']} ({v['category']}): risk={float(v['risk_score']):.3f}, "
        f"dispute_rate={float(v['dispute_rate']):.1%}, payments={int(v['payment_count'])}"
        for _, v in low_rows.iterrows()
    ]

    # Vendor-specific deep-dive if the question names a vendor
    specific_block = ""
    question_lower = question.lower()
    matched = df[df["vendor_name"].str.lower().apply(
        lambda n: isinstance(n, str) and any(
            word in question_lower for word in n.lower().split("-") if len(word) > 3
        )
    )]
    if not matched.empty:
        v = matched.iloc[0]
        shap = v["shap_values"]
        shap_str = ""
        if shap:
            d = shap if isinstance(shap, dict) else json.loads(shap)
            shap_str = "\n    All SHAP drivers: " + ", ".join(
                f"{FEATURE_LABELS.get(k, k)}={float(val):+.3f}" for k, val in d.items()
            )
        vend_flags = flags[flags["vendor_id"] == v["vendor_id"]]
        specific_block = f"""
DEEP-DIVE — {v['vendor_name']}:
  risk_score={float(v['risk_score']):.3f} | risk_label={v['risk_label']} | category={v['category']}
  avg_days_late={float(v['avg_days_late']):.1f} | dispute_rate={float(v['dispute_rate']):.1%}
  payment_count={int(v['payment_count'])} | anomaly_score={float(v['anomaly_score']):.3f}
  days_since_last_payment={float(v.get('days_since_last_payment', 0) or 0):.0f}
  po_to_payment_ratio={float(v.get('po_to_payment_ratio', 1) or 1):.2f}
  stddev_payment_amount={float(v.get('stddev_payment_amount', 0) or 0):.0f}{shap_str}
  flagged_payments={len(vend_flags)} — types: {vend_flags['anomaly_type'].value_counts().to_dict()}
"""

    return f"""PROCUREIQ LIVE SNAPSHOT  (vendors: {len(df)} | flagged payments: {len(flags)})

RISK DISTRIBUTION: {risk_dist}
PAYMENT ANOMALY TYPES: {flag_dist}

ALL HIGH-RISK VENDORS ({len(high_rows)} total, ranked by risk score):
{chr(10).join(high_lines)}

SAMPLE MEDIUM-RISK VENDORS (top 5):
{chr(10).join(med_lines)}

LOWEST-RISK VENDORS (top 5 — safest to work with):
{chr(10).join(low_lines)}
{specific_block}"""


SYSTEM_PROMPT = """You are a procurement risk analyst at an Indian fintech company. You have direct access to a vendor payment risk database and full knowledge of how the risk pipeline works.

━━ HOW RISK IS CALCULATED ━━
The ProcureIQ pipeline has two ML models:

1. PAYMENT ANOMALY DETECTION — IsolationForest (unsupervised)
   Trained on payment-level features to detect outliers without labelled fraud data.
   anomaly_score is normalised to [0, 1]; higher = more anomalous.
   Anomaly types flagged:
     • velocity_spike  — ≥8 payments from one vendor in a single day (unusual transaction rate)
     • round_number    — payment ≥₹50,000 and divisible by ₹1,000 (classic fraud signal)
     • dormant_burst   — vendor with historically low activity suddenly resurfaces with high volume

2. VENDOR RISK SCORING — RandomForest classifier (supervised, trained on injected anomaly labels)
   risk_score = predict_proba output for the "high" class, i.e. the model's confidence (0–1) that this vendor belongs in the high-risk category.
   risk_label is then thresholded: high / medium / low.

3. EXPLAINABILITY — SHAP (SHapley Additive exPlanations) via TreeExplainer
   Each SHAP value = that feature's marginal contribution to pushing risk_score up or down vs. the average prediction.
   Positive SHAP → feature is pushing the vendor toward "high" risk.
   Negative SHAP → feature is pulling the vendor away from "high" risk.
   The magnitude tells you how much — e.g. dispute_rate=+0.26 has more impact than avg_days_late=+0.12.

━━ WHAT EACH FEATURE MEANS ━━
   • avg_days_late            — mean days between payment due date and actual payment; higher = chronic late payer
   • dispute_rate             — fraction of invoices disputed; high rate = billing conflicts or deliberate delay tactics
   • payment_count            — total historical payments; very low count can indicate a dormant or shell vendor
   • days_since_last_payment  — recency; very high = vendor was dormant and recently reactivated (dormant-burst risk)
   • po_to_payment_ratio      — POs raised vs payments made; deviation from 1.0 may mean missing or duplicate payments
   • stddev_payment_amount    — variability in payment sizes; high stddev + round numbers = suspicious
   • credit_tier_encoded      — A=0 (best), B=1, C=2 (worst); encodes creditworthiness tier
   • category_encoded         — vendor category as integer; captures category-level baseline risk

━━ HOW TO ANSWER ━━
Use the live database context provided with each question plus the pipeline knowledge above.
Be specific — cite vendor names, scores, percentages, and SHAP drivers.
When explaining risk, always connect the SHAP drivers back to what the feature means in business terms.
If the data doesn't contain enough to answer, say so honestly. Never invent numbers."""


# ── Page 1: Risk Dashboard ────────────────────────────────────────────────────
def page_risk_dashboard():
    st.title("Vendor Risk Dashboard")

    df = load_vendor_risk()

    total     = len(df)
    n_high    = int((df["risk_label"] == "high").sum())
    n_medium  = int((df["risk_label"] == "medium").sum())
    n_low     = int((df["risk_label"] == "low").sum())
    avg_score = float(df["risk_score"].dropna().mean())

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Vendors",  total)
    c2.metric("High Risk",      n_high)
    c3.metric("Medium Risk",    n_medium)
    c4.metric("Low Risk",       n_low)
    c5.metric("Avg Risk Score", f"{avg_score:.3f}")

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        risk_counts = (
            df["risk_label"]
            .value_counts()
            .reindex(["high", "medium", "low"])
            .reset_index()
        )
        risk_counts.columns = ["Label", "Vendors"]
        fig = px.bar(
            risk_counts, x="Label", y="Vendors",
            color="Label",
            color_discrete_map=RISK_COLORS,
            title="Vendor Risk Distribution",
        )
        fig.update_layout(showlegend=False, height=350)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig2 = px.scatter(
            df.dropna(subset=["risk_score", "avg_days_late"]),
            x="avg_days_late",
            y="risk_score",
            color="risk_label",
            color_discrete_map=RISK_COLORS,
            size="payment_count",
            size_max=18,
            hover_name="vendor_name",
            hover_data={
                "dispute_rate":  ":.1%",
                "avg_days_late": ":.1f",
                "risk_label":    False,
            },
            title="Risk Score vs Avg Days Late",
            labels={"avg_days_late": "Avg Days Late", "risk_score": "Risk Score"},
        )
        fig2.update_layout(height=350)
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("High-Risk Vendors")

    high_df = df[df["risk_label"] == "high"].copy()
    vendor_names = high_df["vendor_name"].dropna().tolist()
    selected = st.selectbox("Select vendor to view SHAP feature drivers", vendor_names)

    if selected:
        row = high_df[high_df["vendor_name"] == selected].iloc[0]
        shap_raw = row["shap_values"]

        if shap_raw:
            shap_dict = shap_raw if isinstance(shap_raw, dict) else json.loads(shap_raw)
            shap_df = pd.DataFrame(list(shap_dict.items()), columns=["Feature", "SHAP Value"])
            # Human-readable feature names
            shap_df["Feature"] = shap_df["Feature"].map(FEATURE_LABELS).fillna(shap_df["Feature"])
            shap_df["Direction"] = shap_df["SHAP Value"].apply(
                lambda x: "Increases Risk" if x > 0 else "Decreases Risk"
            )
            shap_df = shap_df.sort_values("SHAP Value")

            fig3 = px.bar(
                shap_df, x="SHAP Value", y="Feature", orientation="h",
                color="Direction",
                color_discrete_map={
                    "Increases Risk": "#EF4444",
                    "Decreases Risk": "#10B981",
                },
                title=f"SHAP Feature Attribution — {selected}",
                labels={"SHAP Value": "Impact on Risk Prediction"},
            )
            fig3.update_layout(height=320)
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("No SHAP data for this vendor — re-run explain.py.")

    st.dataframe(
        high_df[[
            "vendor_name", "category", "risk_score", "risk_label",
            "anomaly_score", "avg_days_late", "dispute_rate", "payment_count",
        ]].rename(columns={
            "vendor_name":   "Vendor",
            "category":      "Category",
            "risk_score":    "Risk Score",
            "risk_label":    "Label",
            "anomaly_score": "Anomaly Score",
            "avg_days_late": "Avg Days Late",
            "dispute_rate":  "Dispute Rate",
            "payment_count": "Payments",
        }).style.format({
            "Risk Score":    "{:.3f}",
            "Anomaly Score": "{:.3f}",
            "Avg Days Late": "{:.1f}",
            "Dispute Rate":  "{:.1%}",
        }),
        use_container_width=True,
        height=420,
    )


# ── Page 2: Payment Anomalies ─────────────────────────────────────────────────
def page_payment_anomalies():
    st.title("Payment Anomaly Flags")

    df = load_anomaly_flags()

    type_counts = df["anomaly_type"].value_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Flagged",      len(df))
    c2.metric("Velocity Spikes",    int(type_counts.get("velocity_spike", 0)))
    c3.metric("Round-Number Fraud", int(type_counts.get("round_number", 0)))
    c4.metric("Dormant Burst",      int(type_counts.get("dormant_burst", 0)))

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        counts = type_counts.reset_index()
        counts.columns = ["Anomaly Type", "Count"]
        fig = px.bar(
            counts, x="Anomaly Type", y="Count",
            color="Anomaly Type",
            color_discrete_sequence=["#EF4444", "#F59E0B", "#8B5CF6"],
            title="Flagged Payments by Anomaly Type",
        )
        fig.update_layout(showlegend=False, height=350)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        daily = (
            df.groupby("payment_date")
            .size()
            .reset_index(name="Count")
        )
        daily["payment_date"] = pd.to_datetime(daily["payment_date"])
        daily = daily.sort_values("payment_date")
        fig2 = px.line(
            daily, x="payment_date", y="Count",
            title="Flagged Payments Over Time",
            labels={"payment_date": "Date"},
        )
        fig2.update_traces(line_color="#EF4444")
        fig2.update_layout(height=350)
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()
    st.subheader("Flagged Payment Details")

    type_filter = st.multiselect(
        "Filter by anomaly type",
        options=sorted(df["anomaly_type"].dropna().unique().tolist()),
        default=sorted(df["anomaly_type"].dropna().unique().tolist()),
    )
    filtered = df[df["anomaly_type"].isin(type_filter)]

    st.dataframe(
        filtered[[
            "payment_id", "vendor_name", "payment_date",
            "amount", "anomaly_score", "anomaly_type",
        ]].rename(columns={
            "payment_id":    "Payment ID",
            "vendor_name":   "Vendor",
            "payment_date":  "Date",
            "amount":        "Amount",
            "anomaly_score": "Anomaly Score",
            "anomaly_type":  "Type",
        }).style.format({
            "Amount":        "₹{:,.0f}",
            "Anomaly Score": "{:.3f}",
        }),
        use_container_width=True,
        height=460,
    )


# ── Page 3: LLM Digest + Chat ─────────────────────────────────────────────────
def page_llm_digest():
    st.title("LLM Risk Digest")

    # ── Latest digest card ────────────────────────────────────────────────────
    df = load_digests()

    if df.empty:
        st.warning(
            "No digest found. Run the `llm_digest` DAG task or:\n\n"
            "```\ndocker-compose exec airflow-scheduler python /opt/llm/digest.py\n```"
        )
    else:
        latest = df.iloc[0]
        st.markdown(
            f"""
            <div style="
                background:#1E293B;border-left:4px solid #6366F1;
                padding:1.25rem 1.5rem;border-radius:6px;margin-bottom:1rem;
            ">
                <p style="color:#94A3B8;font-size:0.78rem;margin:0 0 0.6rem;letter-spacing:0.05em;">
                    {latest['run_date']} &nbsp;·&nbsp;
                    {str(latest['provider']).upper()} &nbsp;·&nbsp;
                    {latest['model_version']}
                </p>
                <p style="color:#E2E8F0;font-size:1rem;line-height:1.75;margin:0;">
                    {latest['narrative']}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if len(df) > 1:
            with st.expander(f"Previous digests ({len(df) - 1})"):
                for _, row in df.iloc[1:].iterrows():
                    st.markdown(
                        f"**{row['run_date']}** &nbsp;·&nbsp; "
                        f"{str(row['provider']).upper()} / {row['model_version']}"
                    )
                    st.markdown(row["narrative"])
                    st.divider()

    # ── Vendor Query Chat ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("Ask about your vendors")
    st.caption(
        "Multi-turn chat — the LLM reads live warehouse data and remembers your conversation. "
        "Ask follow-ups, drill into specific vendors, or explore patterns across the pipeline."
    )

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None

    # Starter question chips — shown only when chat is empty
    if not st.session_state.chat_history:
        starters = [
            "Which 3 vendors should we avoid and why?",
            "How is the risk score calculated?",
            "What's driving the dormant-burst anomalies?",
            "Compare the safest and riskiest vendors.",
            "Which vendor categories have the most disputes?",
            "Walk me through the SHAP values for the top vendor.",
        ]
        st.markdown("**Try asking:**")
        cols = st.columns(3)
        for i, q in enumerate(starters):
            if cols[i % 3].button(q, use_container_width=True, key=f"starter_{i}"):
                st.session_state.pending_question = q
                st.rerun()

    # Render existing chat history
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Clear button
    if st.session_state.chat_history:
        if st.button("Clear chat", key="clear_chat"):
            st.session_state.chat_history = []
            st.session_state.pending_question = None
            st.rerun()

    # Resolve question — either from chat_input or a starter chip
    typed = st.chat_input("Ask anything about vendor risk, anomalies, SHAP drivers, or payment patterns…")
    question = typed or st.session_state.pop("pending_question", None)

    if question:
        st.session_state.chat_history.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Reading warehouse data and thinking…"):
                context  = build_chat_context(question)
                messages = build_messages(context, st.session_state.chat_history, question)
                answer   = call_llm(messages)
            st.markdown(answer)

        st.session_state.chat_history.append({"role": "assistant", "content": answer})


# ── Sidebar + routing ─────────────────────────────────────────────────────────
def main():
    with st.sidebar:
        st.markdown("## 🔍 ProcureIQ")
        st.caption("Vendor Payment Risk Intelligence")
        st.divider()

        page = st.radio(
            "Navigate",
            ["Risk Dashboard", "Payment Anomalies", "LLM Digest"],
            label_visibility="collapsed",
        )

        st.divider()
        st.markdown(
            "**Stack:** PostgreSQL · dbt · Airflow · MLflow · SHAP · Groq\n\n"
            "**Links:** [Airflow](http://localhost:8080) · [MLflow](http://localhost:5000)"
        )

    if page == "Risk Dashboard":
        page_risk_dashboard()
    elif page == "Payment Anomalies":
        page_payment_anomalies()
    else:
        page_llm_digest()


if __name__ == "__main__":
    main()
