-- Creates the Airflow metadata database.
-- This file runs first (00_) before init_db.sql (01_).
-- Airflow uses this DB to track DAG runs, task states, and logs.
CREATE DATABASE airflow;
