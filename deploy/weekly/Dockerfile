# mip weekly refresh for the homelab server: crawl (curl_cffi) + collector import + resolve + dbt + report + ML export.
# Build context is the repo root:  docker compose -f deploy/weekly/compose.yaml build
# amd64 only (the server); never reuse this image or its data on the arm64 Mac.
FROM python:3.13.9-slim-bookworm

# Chromium is only needed by google_maps (playwright), which the weekly job does not run. Build with
# --build-arg WITH_CHROMIUM=1 if a weekly source ever needs a browser.
ARG WITH_CHROMIUM=0
ARG GIT_COMMIT=unknown

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright TZ=UTC

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

# openssh-client: `mip collector import` opens its own tunnel-only forward to the VPS collector database.
# tini: PID 1 that forwards SIGTERM (systemd stop / timeout) to the job and reaps the crawl workers.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates openssh-client tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
# the dev group carries dbt-core + dbt-postgres (the transform steps need them)
RUN uv sync --frozen --group dev --no-install-project
COPY src ./src
COPY config ./config
# market boundaries + district/postcode polygons (lieferando/wolt discovery grid, geo enrichment)
COPY geo ./geo
COPY db ./db
COPY dbt ./dbt
COPY scripts/weekly_refresh.sh ./scripts/weekly_refresh.sh
COPY deploy/weekly/entrypoint.sh deploy/weekly/healthcheck.py /usr/local/lib/mip-weekly/
RUN uv sync --frozen --group dev \
 && if [ "$WITH_CHROMIUM" = "1" ]; then /app/.venv/bin/playwright install --with-deps chromium; fi \
 && useradd --uid 10003 --create-home --shell /usr/sbin/nologin mip \
 && mkdir -p /app/data /app/dbt/target /app/dbt/logs /home/mip/.ssh \
 && chown -R mip:mip /app/data /app/dbt /home/mip \
 && chmod 700 /home/mip/.ssh \
 && chmod 755 /usr/local/lib/mip-weekly/entrypoint.sh

USER mip
ENV PATH="/app/.venv/bin:$PATH" HOME=/home/mip \
    # absolute: weekly_refresh.sh prepends /usr/local/bin (the base image's bare python) to PATH
    MIP_CMD=/app/.venv/bin/mip DBT_CMD=/app/.venv/bin/dbt PY_CMD=/app/.venv/bin/python \
    MIP_DATA_DIR=/app/data MIP_LOG_DIR=/app/data/logs \
    MIP_GIT_COMMIT=${GIT_COMMIT} DBT_SEND_ANONYMOUS_USAGE_STATS=false DBT_LOG_PATH=/app/dbt/logs
# `mip ml export` attaches Postgres through DuckDB: install the extension now so runs need no download.
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL postgres')"

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/lib/mip-weekly/entrypoint.sh"]
CMD ["/bin/bash", "scripts/weekly_refresh.sh"]
