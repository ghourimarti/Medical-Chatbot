# Ingestion worker: SQS consumer that loads, chunks, embeds, upserts, and swaps the
# index alias (D11). Multi-stage + non-root, mirroring the api/ml-service images.
#
# It depends on medapi (for the embedder and vector-store adapters) and therefore carries
# the same ML stack as ml-service. That is deliberate: ingestion embeds documents, so the
# alternative would be calling ml-service over HTTP for every chunk in a 7,000-chunk batch.
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /build

COPY pyproject.toml uv.lock ./
COPY packages/core ./packages/core
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
RUN uv sync --frozen --no-dev --package medworker

FROM python:3.13-slim AS runtime

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

# No EXPOSE and no HEALTHCHECK: the worker serves no port. Its liveness IS the process —
# if it exits, the Deployment controller restarts it and any unacked SQS message returns
# to the queue after the visibility timeout. Adding an HTTP endpoint purely so a probe has
# something to hit would create a surface that exists only for the orchestrator's benefit.
CMD ["medworker"]
