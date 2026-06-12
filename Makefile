# ProcureIQ — convenience commands
# Run via Git Bash or WSL on Windows (PowerShell doesn't include make).
# Install make on Windows: choco install make
#
# Usage:
#   make up      → start all services
#   make down    → stop all services
#   make seed    → generate synthetic data + load into raw tables
#   make test    → run dbt tests
#   make reset   → wipe everything and start fresh
#   make demo    → full end-to-end pipeline from cold start

.PHONY: up down logs seed test reset demo

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

seed:
	docker-compose exec airflow-scheduler python /opt/ingestion/generate_data.py
	docker-compose exec airflow-scheduler python /opt/ingestion/load_raw.py

test:
	docker-compose exec airflow-scheduler dbt test --project-dir /opt/dbt --profiles-dir /opt/dbt

demo:
	docker-compose up -d
	@echo "Waiting 45s for services to initialise..."
	sleep 45
	docker-compose exec airflow-scheduler python /opt/ingestion/generate_data.py
	docker-compose exec airflow-scheduler python /opt/ingestion/load_raw.py
	docker-compose exec airflow-scheduler dbt run --project-dir /opt/dbt --profiles-dir /opt/dbt
	docker-compose exec airflow-scheduler dbt test --project-dir /opt/dbt --profiles-dir /opt/dbt
	@echo ""
	@echo "Demo pipeline complete! Open these URLs:"
	@echo "  Airflow:   http://localhost:8080  (admin / admin)"
	@echo "  MLflow:    http://localhost:5000"
	@echo "  Streamlit: http://localhost:8501"

reset:
	docker-compose down -v
	@echo "All volumes wiped. Run 'make up' to start fresh."
