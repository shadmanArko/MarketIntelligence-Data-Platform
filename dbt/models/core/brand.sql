-- Chains: brand_id -> name, number of Berlin locations.
select brand_id, min(brand_name) as brand_name, count(*) as locations
from ops.brand_assignment group by 1
