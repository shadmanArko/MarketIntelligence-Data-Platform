{% test min_rows(model, min_count) %}
select 1 from (select count(*) n from {{ model }}) x where n < {{ min_count }}
{% endtest %}
