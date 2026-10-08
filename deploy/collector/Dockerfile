# mip collector: the same platform code, run on the VPS for the light official-API sources (no browsers installed).
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
COPY db ./db
RUN uv sync --frozen --no-dev && useradd --uid 10002 --create-home mip && mkdir -p /app/data && chown mip /app/data
USER mip
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["mip"]
