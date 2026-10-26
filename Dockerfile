FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.27 /uv /uvx /bin/
RUN useradd --create-home --uid 1000 appuser && mkdir -p /app && chown appuser:appuser /app
WORKDIR /app
USER appuser
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1 PATH="/app/.venv/bin:$PATH" \
    APP_ENV=prod MODEL_CACHE_DIR=/app/.cache/models
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser scripts/download_models.py ./scripts/download_models.py
RUN uv sync --frozen --no-dev && python -m scripts.download_models && mkdir -p /app/data
ENV HF_HUB_OFFLINE=1
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:7860/health', timeout=4)"]
CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "7860"]
