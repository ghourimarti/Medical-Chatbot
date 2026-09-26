# Multi-stage, non-root (D15 image discipline). Fixes demo's `COPY . .` + root + fat image.
# ---- builder ----
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
# TWO syncs, and the split is the whole point of the layer order.
#
# Dependencies first, from the manifests ALONE. This layer is keyed only on pyproject.toml
# and uv.lock, so it survives every source edit and the ~128 packages (torch alone is
# 183 MB) are downloaded once instead of on every build.
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/
COPY apps/api/pyproject.toml apps/api/
RUN uv sync --frozen --no-dev --package medapi --no-install-project
# Source second, then install only the local workspace packages against the deps above.
# Previously the source COPY came BEFORE the single sync, so changing one line of Python
# invalidated the dependency layer: `make reload` re-resolved and re-downloaded everything
# and took ~6 minutes, measured, for a one-character edit. A cache key that includes the
# files you edit most is a cache that never hits.
COPY packages/core/ packages/core/
COPY apps/api/ apps/api/
RUN uv sync --frozen --no-dev --package medapi

# ---- runtime ----
FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app /app

# P6.1.5 — drop pip from the RUNTIME layer. Nothing installs packages here (uv resolves
# and installs in the builder stage), and pip ships vendored copies of msgpack and
# setuptools that account for 2 of the 3 Python CVEs Trivy reports against this image.
# Removing the tool removes the finding and the capability at once: a runtime container
# that cannot fetch and install packages is a smaller target than one that merely
# should not. Our own venv keeps setuptools 83.0.0, which is already past the fix.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip            /usr/local/lib/python3.13/site-packages/pip-*.dist-info            /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13

USER appuser
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"
CMD ["uvicorn", "medapi.main:app", "--host", "0.0.0.0", "--port", "8000"]
