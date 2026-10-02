-- Small immutable helpers used by dbt models.
CREATE OR REPLACE FUNCTION ops.url_decode(input text) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
  bin bytea := '';
  i int := 1;
  ch text;
BEGIN
  WHILE i <= length(input) LOOP
    ch := substr(input, i, 1);
    IF ch = '%' AND substr(input, i + 1, 2) ~ '^[0-9A-Fa-f]{2}$' THEN
      bin := bin || decode(substr(input, i + 1, 2), 'hex');
      i := i + 3;
    ELSE
      bin := bin || convert_to(CASE WHEN ch = '+' THEN ' ' ELSE ch END, 'UTF8');
      i := i + 1;
    END IF;
  END LOOP;
  RETURN convert_from(bin, 'UTF8');
EXCEPTION WHEN others THEN
  RETURN input;
END $$;

-- Google redirect wrapper "/url?q=<target>&..." -> target
CREATE OR REPLACE FUNCTION ops.unwrap_redirect(url text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT CASE WHEN url ~ '^(https?://www\.google\.[a-z.]+)?/url\?' THEN ops.url_decode(substring(url from '[?&]q=([^&]+)'))
              ELSE url END
$$;
