"""Print the service board: what is running, where, and (optionally) how to log in.

Two modes, and the split is deliberate:

  urls   what `make up` prints — addresses only, NO credentials. It scrolls past on every
         start and often ends up pasted into an issue or a screen share.
  full   what `make service_ls` prints — the same inventory WITH credentials, because
         pointing pgAdmin or RedisInsight at a service needs them.

Values come from .env so the board cannot drift from what compose actually published:
change a port in one place and it shows up here immediately.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_env() -> dict[str, str]:
    """Parse .env without python-dotenv — this script must work before `uv sync`."""
    env: dict[str, str] = {}
    path = REPO / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip()
            # Strip a TRAILING comment, the dotenv way: an unquoted value ends at the
            # first " #". Without this, `PORT=5001   # 1. boots first` yields the whole
            # sentence as the port. That is not hypothetical — it is the defect already
            # recorded in this repo for empty values, and it bites non-empty ones too the
            # moment anything other than python-dotenv reads the file.
            if value and not value.startswith(('"', "'")):
                cut = value.find(" #")
                if cut != -1:
                    value = value[:cut].rstrip()
            env[key.strip()] = value.strip('"').strip("'")
    for key, value in os.environ.items():
        if key in env:
            env[key] = value
    return env


@dataclass
class Service:
    name: str
    url: str
    tier: str
    note: str = ""
    creds: list[tuple[str, str]] = field(default_factory=list)


def build(env: dict[str, str]) -> list[Service]:
    def g(key: str, default: str) -> str:
        value = env.get(key, "").strip()
        return value or default

    pg_user = g("POSTGRES_USER", "medbot")
    pg_pass = g("POSTGRES_PASSWORD", "medbot")
    pg_port = g("POSTGRES_PORT", "5001")
    pg_db = g("POSTGRES_DB", "medbot")
    lf_db = g("LANGFUSE_POSTGRES_DB", "langfuse")
    qdrant = g("QDRANT_HTTP_PORT", "5002")
    redis_port = g("REDIS_PORT", "5004")
    localstack = g("LOCALSTACK_PORT", "5005")
    ml_port = g("ML_SERVICE_PORT", "5006")
    api_port = g("API_PORT", "5007")
    web_port = g("WEB_PORT", "5008")
    vllm_port = g("VLLM_LOCAL_PORT", "5009")
    sglang_port = g("SGLANG_LOCAL_PORT", "5010")
    otel_http = g("OTEL_HTTP_PORT", "5011")
    otel_grpc = g("OTEL_GRPC_PORT", "5012")
    prom_port = g("PROMETHEUS_PORT", "5013")
    graf_port = g("GRAFANA_PORT", "5014")
    lf_port = g("LANGFUSE_WEB_PORT", "5015")
    ri_port = g("REDISINSIGHT_PORT", "5022")
    jaeger_port = g("JAEGER_UI_PORT", "5023")
    minio_console = g("LANGFUSE_MINIO_CONSOLE_PORT", "5025")

    return [
        # ---- data ------------------------------------------------------------------
        Service(
            "Postgres (app)", f"localhost:{pg_port}", "data",
            "sessions - chat history - audit  (pgAdmin / psql)",
            [("host", "localhost"), ("port", pg_port), ("database", pg_db),
             ("user", pg_user), ("password", pg_pass),
             ("url", f"postgresql://{pg_user}:{pg_pass}@localhost:{pg_port}/{pg_db}")],
        ),
        Service(
            "Postgres (langfuse)", f"localhost:{pg_port}", "data",
            f"SAME server, database '{lf_db}' - one container, one backup story",
            [("host", "localhost"), ("port", pg_port), ("database", lf_db),
             ("user", pg_user), ("password", pg_pass),
             ("url", f"postgresql://{pg_user}:{pg_pass}@localhost:{pg_port}/{lf_db}")],
        ),
        Service(
            "Qdrant dashboard", f"http://localhost:{qdrant}/dashboard", "data",
            "vector store - collections + the 'gale_live' alias",
            [("rest api", f"http://localhost:{qdrant}"), ("auth", "none (local)")],
        ),
        Service(
            "Redis (app cache)", f"localhost:{redis_port}", "data",
            "response cache - embedding cache - quotas",
            [("host", "localhost"), ("port", redis_port), ("auth", "none (local)"),
             ("cli", f"redis-cli -p {redis_port}")],
        ),
        Service(
            "LocalStack (SQS)", f"http://localhost:{localstack}/_localstack/health", "data",
            "ingestion queue",
            [("endpoint", f"http://localhost:{localstack}"),
             ("access key", g("AWS_ACCESS_KEY_ID", "test")),
             ("secret key", g("AWS_SECRET_ACCESS_KEY", "test")),
             ("region", g("AWS_REGION", "us-east-1"))],
        ),
        # ---- app -------------------------------------------------------------------
        Service(
            "ml-service", f"http://localhost:{ml_port}/readyz", "app",
            "bge-large embeddings + cross-encoder rerank",
            [("embed", f"POST http://localhost:{ml_port}/embed"),
             ("rerank", f"POST http://localhost:{ml_port}/rerank")],
        ),
        Service(
            "API (Swagger)", f"http://localhost:{api_port}/docs", "app",
            "FastAPI  -  /healthz  /readyz  /metrics",
            [("health", f"http://localhost:{api_port}/healthz"),
             ("ready", f"http://localhost:{api_port}/readyz"),
             ("metrics", f"http://localhost:{api_port}/metrics"),
             ("auth", "anonymous signed session cookie")],
        ),
        Service(
            "Web (Next.js)", f"http://localhost:{web_port}", "app",
            "the chat UI a human actually uses", [("auth", "anonymous; Clerk optional")],
        ),
        # ---- inference -------------------------------------------------------------
        Service(
            "vLLM (local GPU)", f"http://localhost:{vllm_port}/v1/models", "inference",
            f"model {g('VLLM_LOCAL_MODEL', 'Qwen/Qwen2.5-7B-Instruct-AWQ')}",
            [("openai base_url", f"http://localhost:{vllm_port}/v1"),
             ("api key", "not required (self-hosted)"),
             ("health", f"http://localhost:{vllm_port}/health")],
        ),
        Service(
            "SGLang (local GPU)", f"http://localhost:{sglang_port}/v1/models", "inference",
            f"model {g('SGLANG_LOCAL_MODEL', 'Qwen/Qwen2.5-7B-Instruct-AWQ')}",
            [("openai base_url", f"http://localhost:{sglang_port}/v1"),
             ("api key", "not required (self-hosted)"),
             ("health", f"http://localhost:{sglang_port}/health")],
        ),
        # ---- observability ---------------------------------------------------------
        Service(
            "Prometheus", f"http://localhost:{prom_port}/targets", "obs",
            "scrape targets + the 15 alert rules", [("auth", "none (local)")],
        ),
        Service(
            "Grafana", f"http://localhost:{graf_port}", "obs",
            "dashboards provisioned; anonymous read - no login needed",
            [("admin user", g("GRAFANA_ADMIN_USER", "admin")),
             ("admin password", g("GRAFANA_ADMIN_PASSWORD", "admin")),
             ("anonymous", "Viewer (read without signing in)")],
        ),
        Service(
            "Langfuse", f"http://localhost:{lf_port}", "obs",
            "LLM traces - prompts, completions, cost  (v3: web + worker + clickhouse)",
            [("email", g("LANGFUSE_INIT_USER_EMAIL", "admin@medbot.local")),
             ("password", g("LANGFUSE_INIT_USER_PASSWORD", "medbot-admin-1234")),
             ("public key", g("LANGFUSE_PUBLIC_KEY", "pk-lf-medbot-local")),
             ("secret key", g("LANGFUSE_SECRET_KEY", "sk-lf-medbot-local"))],
        ),
        Service(
            "Jaeger", f"http://localhost:{jaeger_port}", "obs",
            "distributed traces - where the latency actually went",
            [("auth", "none (local)"), ("otlp in", "via otel-collector")],
        ),
        Service(
            "RedisInsight", f"http://localhost:{ri_port}", "obs",
            "Redis GUI - databases pre-registered, no consent wall",
            [("auth", "none; terms pre-accepted"),
             ("registered", g("REDISINSIGHT_DATABASES", "medbot-cache|redis|6379"))],
        ),
        Service(
            "MinIO (langfuse)", f"http://localhost:{minio_console}", "obs",
            "blob store for raw trace payloads - Langfuse v3 requires it",
            [("user", g("LANGFUSE_MINIO_ROOT_USER", "minioadmin")),
             ("password", g("LANGFUSE_MINIO_ROOT_PASSWORD", "minioadmin")),
             ("bucket", "langfuse")],
        ),
        Service(
            "OTel Collector", f"http://localhost:{otel_http}", "obs",
            "OTLP intake -> tail sampling -> Jaeger",
            [("otlp http", f"http://localhost:{otel_http}"),
             ("otlp grpc", f"localhost:{otel_grpc}")],
        ),
    ]


def running_ports() -> set[str]:
    """Published host ports, so the board can mark what is genuinely up rather than
    listing everything as if it were running."""
    if not shutil.which("docker"):
        return set()
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Ports}}"],
            capture_output=True, text=True, timeout=25, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    ports: set[str] = set()
    for chunk in result.stdout.replace("\n", ",").split(","):
        if "->" in chunk:
            ports.add(chunk.split("->")[0].rsplit(":", 1)[-1].strip())
    return ports


TIERS = (
    ("data", "DATA"),
    ("app", "APPLICATION"),
    ("inference", "INFERENCE (GPU)"),
    ("obs", "OBSERVABILITY"),
)
WIDTH = 74


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("urls", "full"), default="urls")
    args = parser.parse_args()

    env = load_env()
    services = build(env)
    live = running_ports()
    full = args.mode == "full"

    heading = "SERVICE INVENTORY + CREDENTIALS" if full else "SERVICE URLs"
    print("")
    print(f"  P5 Medical RAG Chatbot - {heading}")
    print("  " + "=" * WIDTH)
    if full:
        print("  LOCAL DEV credentials, read from .env. Never reuse these anywhere else.")
        print("  " + "=" * WIDTH)

    for tier_key, tier_label in TIERS:
        rows = [s for s in services if s.tier == tier_key]
        if not rows:
            continue
        print("")
        print(f"  -- {tier_label} " + "-" * max(0, WIDTH - len(tier_label) - 5))
        for svc in rows:
            port = svc.url.rsplit(":", 1)[-1].split("/")[0]
            mark = "UP " if port in live else "  -"
            print(f"  [{mark}] {svc.name:<20} {svc.url}")
            if svc.note:
                print(f"         {'':<20} {svc.note}")
            if full:
                for key, value in svc.creds:
                    print(f"         {'':<20}   {key:<15} {value}")

    print("")
    print("  " + "=" * WIDTH)
    if full:
        print("  Chain in use:      SERVING_CHAIN=" + env.get("SERVING_CHAIN", "groq"))
    else:
        print("  Credentials + connection strings:   make service_ls")
    print("  Verify every component:             docs/VERIFY_STACK.md")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
