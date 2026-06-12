import streamlit as st

st.set_page_config(page_title="ProcureIQ", page_icon="🔍", layout="wide")

st.title("ProcureIQ — Vendor Payment Risk Intelligence")
st.info("Frontend coming in Phase 7. Infrastructure is live if you can see this page.")
st.markdown("""
**Services running:**
- Postgres: `localhost:5432`
- Airflow: [localhost:8080](http://localhost:8080) (admin / admin)
- MLflow: [localhost:5000](http://localhost:5000)
- Streamlit: here
""")
