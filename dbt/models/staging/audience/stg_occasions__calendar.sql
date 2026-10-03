select day, community_id, country, occasion_type, holiday_name, holiday_name_native, is_estimated, source, rule_kind,
       {{ dataset_version('occasion_calendar') }} as calendar_version
from {{ dataset_table('occasion_calendar') }}
