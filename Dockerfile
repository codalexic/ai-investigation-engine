FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.27 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
RUN uv sync --frozen --no-dev && useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data && chown -R appuser:appuser /app
USER appuser
EXPOSE 7860
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "7860"]
