# ml-service: CPU inference (bge-large + cross-encoder reranker).
# Multi-stage + non-root + no build tools in the runtime layer.
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /build

COPY pyproject.toml uv.lock ./
COPY packages/core ./packages/core
COPY apps/ml-service ./apps/ml-service
RUN uv sync --frozen --no-dev --package medml

FROM python:3.13-slim AS runtime

# Torch pulls CPU BLAS at runtime; no compilers needed in this layer.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/build/.venv/bin:$PATH" \
    HF_HOME=/models

RUN useradd --create-home --uid 10001 appuser && mkdir -p /models && chown appuser /models
COPY --from=builder --chown=appuser /build /build
WORKDIR /build

USER appuser
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=20 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8001/readyz')"

CMD ["uvicorn", "medml.main:app", "--host", "0.0.0.0", "--port", "8001"]
