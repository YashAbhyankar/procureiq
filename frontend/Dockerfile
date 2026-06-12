FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir streamlit==1.32.2 sqlalchemy==1.4.52 psycopg2-binary==2.9.9 pandas==2.1.4 plotly==5.20.0

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
