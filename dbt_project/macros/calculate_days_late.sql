{% macro calculate_days_late(payment_date_col, due_date_col) %}
    ({{ payment_date_col }}::DATE - {{ due_date_col }}::DATE)
{% endmacro %}
