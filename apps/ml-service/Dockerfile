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


# P6.1.5 — drop pip from the RUNTIME layer. Nothing installs packages here (uv resolves
# and installs in the builder stage), and pip ships vendored copies of msgpack and
# setuptools that account for 2 of the 3 Python CVEs Trivy reports against this image.
# Removing the tool removes the finding and the capability at once: a runtime container
# that cannot fetch and install packages is a smaller target than one that merely
# should not. Our own venv keeps setuptools 83.0.0, which is already past the fix.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip            /usr/local/lib/python3.13/site-packages/pip-*.dist-info            /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13

USER appuser
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=20 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8001/readyz')"

CMD ["uvicorn", "medml.main:app", "--host", "0.0.0.0", "--port", "8001"]
