{# Cleaning rules (gate 2). Every macro is NULL-safe: missing stays NULL, never becomes 0 or ''. #}

{% macro generate_schema_name(custom_schema_name, node) -%}
  {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}

{# raw rows for one source/entity: observation lineage + payload #}
{% macro raw_entity(source, entity_type, ok_only=true) -%}
  (
    select o.observation_id, o.market_id, o.source, o.entity_type, o.natural_key, o.run_id, o.task_id,
           o.connector_ver, o.request_meta, o.http_status, o.fetched_at, o.payload_sha256, p.payload
    from raw.observations o
    join raw.payloads p using (payload_sha256)
    where o.source = '{{ source }}' and o.entity_type = '{{ entity_type }}'
      {% if ok_only %} and o.http_status between 200 and 299 {% endif %}
  )
{%- endmacro %}

{# Text: NFC, zero-width removed, common HTML entities unescaped, whitespace collapsed, trimmed; '' -> NULL #}
{% macro clean_text(expr) -%}
  nullif(btrim(regexp_replace(
    replace(replace(replace(replace(replace(replace(
      regexp_replace(normalize(({{ expr }})::text, NFC), '[​-‍⁠﻿]', '', 'g'),
      '&amp;', '&'), '&quot;', '"'), '&#39;', ''''), '&lt;', '<'), '&gt;', '>'), '&nbsp;', ' '),
    '\s+', ' ', 'g')), '')
{%- endmacro %}

{# German-aware fold: lowercase, umlauts transliterated (ä->ae), other accents stripped #}
{% macro fold(expr) -%}
  unaccent(replace(replace(replace(replace(lower({{ clean_text(expr) }}), 'ä', 'ae'), 'ö', 'oe'), 'ü', 'ue'), 'ß', 'ss'))
{%- endmacro %}

{# Matching key for business names: folded, emoji/punctuation stripped, legal forms and filler words removed #}
{% macro name_key(expr) -%}
  nullif(btrim(regexp_replace(regexp_replace(regexp_replace(
    {{ fold(expr) }},
    '[^a-z0-9 ]', ' ', 'g'),
    '\m(gmbh|ug|haftungsbeschraenkt|e ?k|ohg|kg|gbr|ag|co|mbh|ltd|inc|restaurant|ristorante|restaurante|berlin|lieferservice|lieferdienst|delivery|imbiss|bistro|cafe|bar|grill|the|und|and|am|an|der|die|das|zum|zur|im|in|by|de|la|le|il|da)\M',
    ' ', 'g'),
    '\s+', ' ', 'g')), '')
{%- endmacro %}

{# "12,90 €", "€12.90", "12.90", "1.234,50" -> 12.90 / 1234.50 #}
{% macro parse_money(expr) -%}
  case
    when ({{ expr }}) is null then null
    when regexp_replace(({{ expr }})::text, '[^0-9,.\-]', '', 'g') ~ '^-?\d{1,3}(\.\d{3})+(,\d+)?$'
      then replace(replace(regexp_replace(({{ expr }})::text, '[^0-9,.\-]', '', 'g'), '.', ''), ',', '.')::numeric(10,2)
    when regexp_replace(({{ expr }})::text, '[^0-9,.\-]', '', 'g') ~ '^-?\d+,\d+$'
      then replace(regexp_replace(({{ expr }})::text, '[^0-9,.\-]', '', 'g'), ',', '.')::numeric(10,2)
    when regexp_replace(({{ expr }})::text, '[^0-9.\-]', '', 'g') ~ '^-?\d+(\.\d+)?$'
      then regexp_replace(({{ expr }})::text, '[^0-9.\-]', '', 'g')::numeric(10,2)
  end
{%- endmacro %}

{% macro cents(expr) -%}
  (({{ expr }})::numeric / 100)::numeric(10,2)
{%- endmacro %}

{# "1.2K", "1,2 Tsd.", "3 Mio", "1.234" -> integer; hidden/unknown -> NULL #}
{% macro parse_count(expr) -%}
  case
    when ({{ expr }}) is null then null
    when lower(({{ expr }})::text) ~ '^\s*[\d.,]+\s*(k|tsd\.?|tausend)\s*$'
      then round(replace(regexp_replace(lower(({{ expr }})::text), '[^0-9.,]', '', 'g'), ',', '.')::numeric * 1000)::bigint
    when lower(({{ expr }})::text) ~ '^\s*[\d.,]+\s*(m|mio\.?|million(en)?)\s*$'
      then round(replace(regexp_replace(lower(({{ expr }})::text), '[^0-9.,]', '', 'g'), ',', '.')::numeric * 1000000)::bigint
    when ({{ expr }})::text ~ '^\s*\d{1,3}([.,]\d{3})+\s*$'
      then regexp_replace(({{ expr }})::text, '[^0-9]', '', 'g')::bigint
    when ({{ expr }})::text ~ '^\s*\d+\s*$' then btrim(({{ expr }})::text)::bigint
  end
{%- endmacro %}

{# Original value kept elsewhere; this maps any scale to 0..1 #}
{% macro rating_norm(expr, lo, hi) -%}
  case when ({{ expr }}) is null then null
       else greatest(0, least(1, ((({{ expr }})::numeric - {{ lo }}) / ({{ hi }} - {{ lo }}))))::numeric(6,4) end
{%- endmacro %}

{# URL -> registrable domain: lowercase host, www. removed, tracking-free #}
{% macro domain(expr) -%}
  nullif(regexp_replace(regexp_replace(lower(substring(({{ expr }})::text from '^(?:[a-z]+://)?([^/?#:]+)')),
                        '^(www\d?|m)\.', ''), '\.$', ''), '')
{%- endmacro %}

{% macro registrable_domain(expr) -%}
  case
    when {{ domain(expr) }} ~ '\.(co|com|org|net|ac|gov)\.[a-z]{2}$'
      then substring({{ domain(expr) }} from '([^.]+\.[^.]+\.[^.]+)$')
    else substring({{ domain(expr) }} from '([^.]+\.[^.]+)$')
  end
{%- endmacro %}

{# URL without tracking parameters #}
{% macro clean_url(expr) -%}
  nullif(regexp_replace(regexp_replace(regexp_replace(
    ops.unwrap_redirect(btrim(({{ expr }})::text)),
    '([?&])(utm_[a-z_]+|fbclid|gclid|dclid|msclkid|mc_[a-z_]+|igshid|_ga|ref_src|opi|ved|usg|sa)=[^&#]*', '\1', 'gi'),
    '([?&])&+', '\1', 'g'),
    '[?&]+(#|$)', '\1'), '')
{%- endmacro %}

{# German phone -> E.164-ish digits (+49...) #}
{% macro phone_e164(expr) -%}
  case
    when ({{ expr }}) is null then null
    when regexp_replace(({{ expr }})::text, '[^0-9+]', '', 'g') ~ '^\+' then regexp_replace(({{ expr }})::text, '[^0-9+]', '', 'g')
    when regexp_replace(({{ expr }})::text, '[^0-9]', '', 'g') ~ '^00' then '+' || substr(regexp_replace(({{ expr }})::text, '[^0-9]', '', 'g'), 3)
    when regexp_replace(({{ expr }})::text, '[^0-9]', '', 'g') ~ '^0' then '+49' || substr(regexp_replace(({{ expr }})::text, '[^0-9]', '', 'g'), 2)
  end
{%- endmacro %}

{% macro h3_r8(lat, lon) -%}
  case when ({{ lat }}) is not null and ({{ lon }}) is not null
       then h3_lat_lng_to_cell(point(({{ lon }})::float8, ({{ lat }})::float8), 8)::text end
{%- endmacro %}

{% macro geog(lat, lon) -%}
  case when ({{ lat }}) is not null and ({{ lon }}) is not null
       then st_setsrid(st_makepoint(({{ lon }})::float8, ({{ lat }})::float8), 4326)::geography end
{%- endmacro %}

{# German postcode out of free text #}
{% macro postcode(expr) -%}
  substring(({{ expr }})::text from '\m(\d{5})\M')
{%- endmacro %}

{# "Straße 12a" -> street / house number #}
{% macro street(expr) -%}
  nullif(btrim(regexp_replace({{ clean_text(expr) }}, '\s+\d+\s*[a-zA-Z]?(\s*[-/]\s*\d+\s*[a-zA-Z]?)?\s*$', '')), '')
{%- endmacro %}
{% macro house_number(expr) -%}
  nullif(btrim(substring({{ clean_text(expr) }} from '\s(\d+\s*[a-zA-Z]?(?:\s*[-/]\s*\d+\s*[a-zA-Z]?)?)\s*$')), '')
{%- endmacro %}

{% macro jtext(expr) -%}
  nullif(({{ expr }}) #>> '{}', '')
{%- endmacro %}

{# stable hash of a set of columns for SCD2 change detection #}
{% macro attr_hash(cols) -%}
  md5(concat_ws('||', {% for c in cols %}coalesce(({{ c }})::text, '∅'){% if not loop.last %}, {% endif %}{% endfor %}))
{%- endmacro %}

{# latest registered raw table of a bulk dataset (versioned raw.ds_*) #}
{% macro dataset_table(name) -%}
  {%- if execute -%}
    {%- set r = run_query("select raw_table from ops.datasets where name = '" ~ name ~ "' order by release_date desc nulls last, loaded_at desc limit 1") -%}
    {%- if r.rows | length == 0 -%}
      {{ exceptions.raise_compiler_error("dataset " ~ name ~ " is not loaded; run `mip datasets load`") }}
    {%- endif -%}
    {%- set parts = r.rows[0][0].split('.') -%}
    {{ parts[0] }}."{{ parts[1] }}"
  {%- else -%}
    raw.placeholder
  {%- endif -%}
{%- endmacro %}

{% macro dataset_version(name) -%}
  {%- if execute -%}
    {%- set r = run_query("select version from ops.datasets where name = '" ~ name ~ "' order by release_date desc nulls last, loaded_at desc limit 1") -%}
    '{{ r.rows[0][0] if r.rows | length else "none" }}'
  {%- else -%}'none'{%- endif -%}
{%- endmacro %}
