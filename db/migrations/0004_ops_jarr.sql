-- JSON value -> array, or [] for null / scalar / object. Lets models unnest safely.
CREATE OR REPLACE FUNCTION ops.jarr(j jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN jsonb_typeof(j) = 'array' THEN j ELSE '[]'::jsonb END
$$;
