FROM apache/airflow:2.8.0-python3.11

# Install system deps needed by psycopg2 and some ML libs
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Pin versions that are known-compatible with Airflow 2.8 + Python 3.11
RUN pip install --no-cache-dir \
    dbt-postgres==1.7.4 \
    scikit-learn==1.4.2 \
    mlflow==2.12.2 \
    shap==0.45.1 \
    anthropic==0.25.3 \
    openai==1.23.2 \
    faker==24.3.0 \
    pandas==2.1.4 \
    sqlalchemy==1.4.52 \
    psycopg2-binary==2.9.9 \
    python-dotenv==1.0.1
