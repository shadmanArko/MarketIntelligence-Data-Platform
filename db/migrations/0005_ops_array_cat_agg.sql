-- Concatenate arrays across rows (array_agg of arrays would need equal lengths).
CREATE AGGREGATE ops.array_cat_agg(anycompatiblearray) (SFUNC = array_cat, STYPE = anycompatiblearray, INITCOND = '{}');
