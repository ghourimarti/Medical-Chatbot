# P5 Medical RAG Chatbot — developer entrypoints.
# Every target is a documented, reproducible command (no tribal knowledge).

.DEFAULT_GOAL := help
.PHONY: web web-e2e web-shots web-stop web-preview web-design web-build web-verify help sync lint type test check eval-mock baseline validate api reindex smoke         db app obs up upv down downv ps logs migrate seed worker urls \
        eval-pipeline eval-gate eval-delta rescore bench-groq bench-local bench-sglang \
        load-cache load-full load-guard audit chaos backup-drill \
        images kind-up kind-load kind-install kind-smoke kind-down chart-lint

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

sync:  ## Install/refresh the uv workspace
	uv sync

lint:  ## Ruff lint (matches CI)
	uv run ruff check .

type:  ## Mypy type-check both packages (matches CI)
	uv run mypy packages/core/src/medcore packages/eval/src/medeval

test:  ## Run the unit suite (matches CI)
	uv run pytest -q

check: lint type test  ## The full local gate = what CI runs on every PR

validate:  ## Validate the golden dataset schema
	uv run medeval validate packages/eval/datasets/golden_core_v2.jsonl

eval-mock:  ## Keyless end-to-end eval smoke (no API key needed)
	uv run medeval run --target mock --dataset packages/eval/datasets/golden_seed_v0.jsonl --skip-ragas

baseline:  ## Re-run the demo/ baseline (needs GROQ_API_KEY in .env; ~$1, ~25 min)
	uv run medeval run --target demo --dataset packages/eval/datasets/golden_core_v2.jsonl

eval-pipeline:  ## Evaluate the CURRENT pipeline (needs Qdrant + full index; ~35 min)
	uv run medeval run --target pipeline --dataset packages/eval/datasets/golden_core_v2.jsonl

eval-gate:  ## BLOCKING quality gate: exits 1 if any D19 threshold is unmet (S6.11)
	uv run medeval compare --before demo --after pipeline --out eval-reports/delta.md --gate

eval-delta:  ## Print the before/after delta table without gating
	uv run medeval compare --before demo --after pipeline

bench-groq:  ## Engine benchmark against hosted Groq (needs GROQ_API_KEY)
	k6 run -e BASE_URL=https://api.groq.com/openai/v1 -e MODEL=llama-3.1-8b-instant \
	  -e API_KEY=$$(grep '^GROQ_API_KEY=' .env | cut -d= -f2 | tr -d '"') \
	  -e LABEL=groq tests/load/engine_benchmark.js

bench-local:  ## Engine benchmark against local vLLM (needs the container running on :5009)
	k6 run -e BASE_URL=http://localhost:5009/v1 -e MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ \
	  -e LABEL=local-vllm tests/load/engine_benchmark.js

bench-sglang:  ## Engine benchmark against local SGLang (needs the container running on :5010)
	k6 run -e BASE_URL=http://localhost:5010/v1 -e MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ \
	  -e LABEL=local-sglang tests/load/engine_benchmark.js

rescore:  ## Recompute deterministic metrics on the latest pipeline report (no model calls)
	uv run medeval rescore $$(ls -t eval-reports/pipeline-*.json | head -1)

# ── Layered local stack: db | app | obs | up ─────────────────────────────────────────
# Three compose files, one per tier, each overlaying the previous. They share the compose
# PROJECT (same directory), so every tier lands on one network and services resolve each
# other by name whichever combination is running.
# NOTE ON "Found orphan containers": running a SUBSET of the tiers makes compose report
# the other tiers' containers as orphans, because they belong to the same project but are
# not in the file set you passed. It is expected and harmless. Do NOT add
# --remove-orphans to these targets: `make app` would then delete your running
# observability stack, which is the opposite of what a tiered layout is for.
DC_DATA := docker compose -f docker-compose.data.yaml
DC_APP  := docker compose -f docker-compose.data.yaml -f docker-compose.app.yaml
DC_OBS  := docker compose -f docker-compose.observability.yaml
DC_FULL := docker compose -f docker-compose.data.yaml -f docker-compose.app.yaml -f docker-compose.observability.yaml

db:		## tier 1: DATA only — Postgres + Qdrant + Redis + LocalStack
	$(DC_DATA) up -d --wait
	@$(MAKE) --no-print-directory urls

app:	## tier 2: data + APP (ml-service, api). Builds images on first run.
	$(DC_APP) up --build -d --wait
	@$(MAKE) --no-print-directory urls

obs:	## tier 3: OBSERVABILITY (OTel, Prometheus, Grafana, Langfuse). Needs `make db`:
		## Langfuse stores its traces in the data tier's Postgres.
	$(DC_OBS) up -d
	@$(MAKE) --no-print-directory urls

up:		## EVERYTHING: data + app + observability
	$(DC_FULL) up --build -d --wait
	@$(MAKE) --no-print-directory urls

worker:	## Start the ingestion worker (profile-gated: it needs an SQS queue to exist)
	$(DC_DATA) exec -T localstack awslocal sqs create-queue --queue-name medbot-ingestion || true
	$(DC_APP) --profile worker up -d worker
	@echo "  worker started — tail it with: make logs"

ps:		## Status of every container in the stack
	$(DC_FULL) ps

logs:	## Tail logs for the whole stack (Ctrl-C to stop)
	$(DC_FULL) logs -f --tail=100

migrate:	## Create/upgrade the Postgres schema + partitions (idempotent; needs the app tier)
	# The API also does this on boot; this target makes it explicit and re-runnable.
	# The script is PIPED IN over stdin rather than baked into the image: `scripts/` is
	# not part of the runtime layer (P6.1 keeps images to what actually serves traffic),
	# and `python -` reads a program from stdin perfectly well.
	$(DC_APP) exec -T api python - < scripts/migrate.py

seed:	## Ingest the corpus -> new collection -> atomic alias swap. LIMIT=N for a fast dev index.
	# Runs on the HOST: the corpus lives in demo/data, which is gitignored and therefore not
	# inside any image. ⚠ NEVER evaluate against a --limit index (S6.6) — it produces false
	# abstentions and a meaningless score.
	uv run medworker-ingest --direct $${LIMIT:+--limit $$LIMIT}

down:	## Stop every tier (KEEPS all data volumes)
	$(DC_FULL) down

# Volume names are prefixed with the compose PROJECT name, which is derived from the repo
# directory — and this repo's path contains spaces and an `&`, which break $(notdir
# $(CURDIR)). So ask compose for the project name at runtime instead of guessing it.
DATA_VOLS  := pg_data qdrant_data localstack_data hf_models prom_data grafana_data
PROJECT_CMD = $(DC_DATA) config --format json | python -c "import sys,json;print(json.load(sys.stdin)['name'])"

downv:	## DESTRUCTIVE: stop every tier AND delete all data volumes (DB, index, weights)
	$(DC_FULL) down -v --remove-orphans
	@P=$$($(PROJECT_CMD)); 	  docker volume rm $(foreach v,$(DATA_VOLS),$${P}_$(v)) 2>/dev/null || true; 	  echo "  Wiped: $(DATA_VOLS)"; 	  echo "  Next 'make upv' re-downloads ~2.4GB of model weights and re-ingests the corpus."

upv:		## FROM SCRATCH in ONE command: wipe volumes, rebuild images, start every tier,
		## create the schema, ingest the corpus. The full cold-start path.
	@echo "  make upv — clean rebuild from scratch (DESTROYS local data volumes)."
	@$(MAKE) --no-print-directory downv
	$(DC_FULL) up --build -d --wait
	@$(MAKE) --no-print-directory migrate
	@$(MAKE) --no-print-directory seed
	@echo ""
	@echo "  Up from scratch — every tier running, schema created, corpus ingested."
	@$(MAKE) --no-print-directory urls

urls:	## Print which URL opens which UI (ports come from .env)
	@set -a; . ./.env 2>/dev/null || true; set +a; 	echo ""; 	echo "  P5 Medical RAG Chatbot - local URLs   (ports sequenced by startup order in .env)"; 	echo "  ---------------------------------------------------------------------------"; 	echo "  -- data tier (starts 1st) ----"; 	echo "  Postgres             localhost:$${POSTGRES_PORT:-5001}          (user/db = $${POSTGRES_USER:-medbot})"; 	echo "  Qdrant dashboard     http://localhost:$${QDRANT_HTTP_PORT:-5002}/dashboard"; 	echo "  Redis                localhost:$${REDIS_PORT:-5004}          (redis-cli / RedisInsight)"; 	echo "  LocalStack (SQS)     http://localhost:$${LOCALSTACK_PORT:-5005}/_localstack/health"; 	echo "  -- app tier (starts 2nd) ----"; 	echo "  ml-service           http://localhost:$${ML_SERVICE_PORT:-5006}/readyz"; 	echo "  API docs (Swagger)   http://localhost:$${API_PORT:-5007}/docs"; 	echo "  API metrics (raw)    http://localhost:$${API_PORT:-5007}/metrics"; 	echo "  Web (Next.js)        http://localhost:$${WEB_PORT:-5008}          (S10 deferred - not running)"; 	echo "  -- observability tier (starts 3rd) ----"; 	echo "  Prometheus           http://localhost:$${PROMETHEUS_PORT:-5013}          Status > Targets"; 	echo "  Grafana              http://localhost:$${GRAFANA_PORT:-5014}          login $${GRAFANA_ADMIN_USER:-admin}/$${GRAFANA_ADMIN_PASSWORD:-admin}"; 	echo "  Langfuse (LLM trace) http://localhost:$${LANGFUSE_WEB_PORT:-5015}"; 	echo "  ---------------------------------------------------------------------------"; 	echo ""

# ── Native dev (run the API on the host against the containerized data tier) ────────────
api:  ## Run the query service on $$API_PORT (default 5007)
	uv run uvicorn medapi.main:app --host 127.0.0.1 --port $${API_PORT:-5007}

reindex:  ## Ingest corpus -> new collection -> atomic alias swap (D11). LIMIT=N for dev only
	uv run medworker-ingest --direct $${LIMIT:+--limit $$LIMIT}

load-cache:  ## P5.2 tier A: cache-hit path - HTTP/async/Redis ceiling (no LLM)
	k6 run -e TIER=cache -e PEAK_RATE=$${PEAK_RATE:-200} tests/load/system_load.js

load-full:  ## P5.2 tier B: full pipeline, every request a cache miss (needs vLLM)
	k6 run -e TIER=full -e PEAK_RATE=$${PEAK_RATE:-8} tests/load/system_load.js

load-guard:  ## P5.2 tier C: abuse traffic - cost of refusing before retrieval
	k6 run -e TIER=guard -e PEAK_RATE=$${PEAK_RATE:-200} tests/load/system_load.js

chaos:  ## P5.3 chaos drills: stop/start each dependency (NEVER deletes volumes)
	uv run python tests/chaos/drill.py --targets $${TARGETS:-redis,qdrant,postgres,provider}

backup-drill:  ## P5.4 backup/restore drill with measured RTO (restores to PARALLEL targets)
	uv run python tests/chaos/backup_restore.py

audit:  ## P5.1 security audit: dependency CVEs + secret scan
	uv run --with pip-audit pip-audit --progress-spinner off || true
	@git grep -nE "(gsk_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})" \
		-- ':!*.md' ':!.env.example' || echo "no hardcoded secrets found"

smoke:  ## Query the running API (shell-quoting-proof; needs `make api` in another shell)
	@echo "--- in-corpus (expect kind=grounded, citations) ---"
	@curl -s -X POST localhost:$${API_PORT:-5007}/api/v1/query \
		-H 'content-type: application/json' \
		--data-binary '{"question":"What is an abscess?","stream":false}'
	@echo "\n--- out-of-corpus (expect kind=no_answer, 0 citations) ---"
	@curl -s -X POST localhost:$${API_PORT:-5007}/api/v1/query \
		-H 'content-type: application/json' \
		--data-binary '{"question":"How does CRISPR gene editing work?","stream":false}'
	@echo ""

# ── S15 / Phase 6: kind ───────────────────────────────────────────────────────────────
images:  ## Build all three service images (heavy: torch; first run 10-25 min)
	docker build -f apps/api/Dockerfile        -t medbot-api:0.1.0    .
	docker build -f apps/ml-service/Dockerfile -t medbot-ml:0.1.0     .
	docker build -f apps/worker/Dockerfile     -t medbot-worker:0.1.0 .
	docker images --filter=reference='medbot-*'

kind-up:  ## Create the 3-node kind cluster + metrics-server
	kind create cluster --config infra/k8s/kind-cluster.yaml --wait 180s
	kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
	kubectl patch deployment metrics-server -n kube-system --type=json -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

kind-load:  ## Side-load images into kind (nodes cannot see the host daemon)
	kind load docker-image medbot-api:0.1.0    --name medbot
	kind load docker-image medbot-ml:0.1.0     --name medbot
	kind load docker-image medbot-worker:0.1.0 --name medbot

kind-install:  ## helm install into kind (needs GROQ_API_KEY exported)
	helm upgrade --install medbot infra/k8s/medbot -f infra/k8s/medbot/values-kind.yaml --set secrets.groqApiKey="$$GROQ_API_KEY" --set secrets.sessionSecret="kind-dev-session-secret-not-for-prod"
	kubectl get pods

kind-smoke:  ## Port-forward + health check (run kind-install first)
	@echo "run: kubectl port-forward svc/medbot-api 8000:80"
	@echo "then: curl -s localhost:8000/healthz"

kind-down:  ## Delete the kind cluster
	helm uninstall medbot || true
	kind delete cluster --name medbot

chart-lint:  ## helm lint + render object census (no cluster needed)
	helm lint infra/k8s/medbot -f infra/k8s/medbot/values-kind.yaml
	helm template medbot infra/k8s/medbot -f infra/k8s/medbot/values-kind.yaml --set secrets.groqApiKey=test --set secrets.sessionSecret=test-secret | grep '^kind:' | sort | uniq -c

# ── S16: Terraform ────────────────────────────────────────────────────────────────────
tf-init:  ## terraform init (providers only; no backend, no credentials needed)
	terraform -chdir=infra/terraform/aws init -backend=false -input=false

tf-validate:  ## terraform fmt + validate - proves the HCL is correct OFFLINE
	terraform -chdir=infra/terraform/aws fmt -check -recursive
	terraform -chdir=infra/terraform/aws validate

tf-plan:  ## terraform plan - NEEDS AWS credentials (Track D); never applies
	terraform -chdir=infra/terraform/aws plan -input=false

# --- S10 web tier -------------------------------------------------------------
# apps/web is Node, deliberately EXCLUDED from the uv workspace (see pyproject.toml):
# the `apps/*` glob would claim it as a Python member and break `uv run` repo-wide.
web:	## Run the Next.js dev server on $$WEB_PORT (default 5008); needs `make app`
	cd apps/web && pnpm install --silent && pnpm dev

web-build:	## Web gate: contrast + contract drift + typecheck + build
	cd apps/web && pnpm install --silent && pnpm check

web-stop:	## Free $$WEB_PORT by stopping whatever is listening on it
	@PORT=$${WEB_PORT:-5008}; 	PID=$$(netstat -ano 2>/dev/null | grep ":$$PORT " | grep -i LISTENING | head -1 | awk '{print $$NF}'); 	if [ -n "$$PID" ]; then 		echo "stopping PID $$PID on :$$PORT"; 		taskkill //PID $$PID //F >/dev/null 2>&1 || kill -9 $$PID 2>/dev/null || true; 	else echo "nothing listening on :$$PORT"; fi

web-preview: web-stop	## Build AND serve the production web tier (always builds first)
	@echo 'note: plain next-start fails when .next is missing or a build was interrupted;'
	@echo 'this target always builds first, and web-stop frees the port before binding.'
	cd apps/web && pnpm install --silent && API_BASE_URL=$${API_BASE_URL:-http://localhost:5007} pnpm preview

web-design:	## Open the design-system gallery (needs `make web`)
	@echo "http://localhost:$${WEB_PORT:-5008}/design

web-e2e:	## Browser verification of the four answer kinds (needs the full stack up)
	cd apps/web && pnpm exec playwright test --project=chromium e2e/answer-kinds.spec.ts

web-shots:	## Regenerate docs/screenshots in both themes
	cd apps/web && pnpm exec playwright test e2e/screenshots.spec.ts --project=chromium

web-verify:	## PROVE the BFF proxy streams SSE rather than buffering (D23)
	@echo "Start the web server first: (cd apps/web && API_BASE_URL=http://localhost:5099 pnpm start)"
	cd apps/web && node scripts/verify-stream.mjs http://localhost:$${WEB_PORT:-5008}
