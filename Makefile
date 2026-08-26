# P5 Medical RAG Chatbot — developer entrypoints.
# Every target is a documented, reproducible command (no tribal knowledge).

.DEFAULT_GOAL := help
.PHONY: web web-ci web-a11y web-mobile web-e2e web-shots web-stop web-preview web-design web-build web-verify help sync lint type test check eval-mock baseline validate api reindex smoke         db app obs up upv down downv ps logs migrate seed worker urls \
        eval-pipeline eval-gate eval-delta rescore bench-groq bench-local bench-sglang \
        load-cache load-full load-guard audit chaos backup-drill \
        images kind-up kind-load kind-install kind-smoke kind-down chart-lint \n        service_ls clean-images clean-models clean-all kind-sync gpu gpu-down \n        kind-start kind-stop kind-status vllm-up vllm-down vllm-upv vllm-downv \n        sglang-up sglang-down sglang-upv sglang-downv webui vllm-test sglang-test engine-guide

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
DC_GPU  := docker compose -f docker-compose.gpu.yaml
DC_FULL := docker compose -f docker-compose.data.yaml -f docker-compose.app.yaml -f docker-compose.observability.yaml -f docker-compose.gpu.yaml

# ── GPU tier (vLLM + SGLang) ──────────────────────────────────────────────────────────
# Included only when an NVIDIA GPU is actually present. Without one these containers do
# not fail politely: they pull ~10 GB and then die at device init, minutes later. Detecting
# up front turns that into one printed line.
#   GPU=0 make up   forces it off even on a GPU box (useful when the card is busy).
GPU ?= $(shell nvidia-smi -L >/dev/null 2>&1 && echo 1 || echo 0)
ifeq ($(GPU),1)
  GPU_PROFILE := --profile gpu
else
  GPU_PROFILE :=
endif

# ── kind (local Kubernetes) ───────────────────────────────────────────────────────────
# kind runs its nodes as DOCKER CONTAINERS (medbot-control-plane, medbot-worker,
# medbot-worker2), so without this they survive `make down` and sit there consuming RAM
# while looking like part of the stack. They now follow the same lifecycle as everything
# else, with the same preserve/destroy split the data volumes use:
#
#   make up     cluster exists -> START its nodes (~20s)   |  missing -> CREATE it
#   make down   STOP the nodes. The cluster, its images and its state all survive,
#               exactly as `down` keeps your database volume.
#   make downv  DELETE the cluster. Destructive, and paired with wiping volumes.
#   make upv    delete + recreate, the cold path.
#
# Deploying the APP into the cluster is `make kind-sync` and stays separate: it rebuilds
# and side-loads ~6.6GB of images, which is minutes of work that a routine `make up`
# should not silently do.
#   KIND=0 make up   skip the cluster entirely (pure compose loop)
KIND ?= 1
KIND_CLUSTER := medbot
KIND_NODES   := $(KIND_CLUSTER)-control-plane $(KIND_CLUSTER)-worker $(KIND_CLUSTER)-worker2

db:		## tier 1: DATA only — Postgres + Qdrant + Redis + LocalStack
	$(DC_DATA) up -d --wait
	@$(MAKE) --no-print-directory urls

app:	## tier 2: data + APP (ml-service, api). Builds images on first run.
	$(DC_APP) up --build -d --wait
	@$(MAKE) --no-print-directory urls

obs:	## tier 3: OBSERVABILITY (OTel, Prometheus, Grafana, Langfuse). Needs `make db`:
		## Langfuse stores its traces in the data tier's Postgres.
	$(DC_OBS) up -d
	@$(DC_OBS) --profile seed up -d redisinsight-seed >/dev/null 2>&1 || true
	@$(MAKE) --no-print-directory urls

up:		## EVERYTHING: data + app + observability (+ GPU if present, + kind if KIND=1)
	$(DC_FULL) $(GPU_PROFILE) up --build -d --wait
	@$(DC_OBS) --profile seed up -d redisinsight-seed >/dev/null 2>&1 || true
	@if [ "$(GPU)" = "1" ]; then 	  echo "  GPU detected - vLLM + SGLang started (first run pulls ~10GB and weights)."; 	else 	  echo "  No NVIDIA GPU detected - vLLM/SGLang SKIPPED. The chain falls back to hosted."; 	fi
	@if [ "$(KIND)" = "1" ]; then $(MAKE) --no-print-directory kind-start; fi
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

down:	## Stop every tier (KEEPS all data volumes, images and model weights)
	$(DC_FULL) $(GPU_PROFILE) down
	@if [ "$(KIND)" = "1" ]; then $(MAKE) --no-print-directory kind-stop; fi

# Volume names are prefixed with the compose PROJECT name, which is derived from the repo
# directory — and this repo's path contains spaces and an `&`, which break $(notdir
# $(CURDIR)). So ask compose for the project name at runtime instead of guessing it.
DATA_VOLS  := pg_data qdrant_data localstack_data hf_models prom_data grafana_data redisinsight_data
# NOT wiped by `make downv`, on purpose. `vllm-hf-cache` holds the ~5GB of LLM weights
# shared by vLLM and SGLang. S3b blocker #3: huggingface_hub does not resume across
# process restarts, so replacing this volume costs one uninterrupted download, not a
# resumable one. `make clean-models` removes it when you actually mean to.
KEEP_VOLS  := vllm-hf-cache
PROJECT_CMD = $(DC_DATA) config --format json | python -c "import sys,json;print(json.load(sys.stdin)['name'])"

downv:	## DESTRUCTIVE: stop every tier AND delete DATA volumes. KEEPS images + LLM weights.
	$(DC_FULL) $(GPU_PROFILE) down -v --remove-orphans
	@P=$$($(PROJECT_CMD)); 	  docker volume rm $(foreach v,$(DATA_VOLS),$${P}_$(v)) 2>/dev/null || true; 	  echo "  Wiped: $(DATA_VOLS)"; 	  echo "  KEPT:  $(KEEP_VOLS) - LLM weights (~5GB, and huggingface_hub does NOT"; 	  echo "         resume across restarts, so re-downloading means one uninterrupted run)"; 	  echo "  KEPT:  all docker images. 'make clean-images' removes those, deliberately separate."
	@if [ "$(KIND)" = "1" ]; then $(MAKE) --no-print-directory kind-down; fi

upv:		## FROM SCRATCH in ONE command: wipe volumes, rebuild images, start every tier,
		## create the schema, ingest the corpus. The full cold-start path.
	@echo "  make upv — clean rebuild from scratch (DESTROYS local data volumes)."
	@$(MAKE) --no-print-directory downv
	$(DC_FULL) $(GPU_PROFILE) up --build -d --wait
	@$(DC_OBS) --profile seed up -d redisinsight-seed >/dev/null 2>&1 || true
	@$(MAKE) --no-print-directory migrate
	@$(MAKE) --no-print-directory seed
	@if [ "$(KIND)" = "1" ]; then $(MAKE) --no-print-directory kind-start; fi
	@echo ""
	@echo "  Up from scratch - every tier running, schema created, corpus ingested."
	@$(MAKE) --no-print-directory urls

urls:	## Print every service URL (no credentials)
	@python scripts/service_board.py --mode urls

service_ls:	## FULL inventory WITH credentials: DBs, engines, dashboards, connection strings
	@python scripts/service_board.py --mode full

# ── Images and model weights: destructive, and deliberately NOT part of downv ──────────
clean-images:	## DESTRUCTIVE: remove this project's images (app + vLLM + SGLang). Keeps weights.
	@echo "  Removing medbot images and the inference engine images."
	@echo "  Rebuild: 'make images' (~10-25 min).  Re-pull vLLM/SGLang: ~10GB."
	-docker rmi medbot-api:0.1.0 medbot-ml:0.1.0 medbot-worker:0.1.0 2>/dev/null
	-docker rmi vllm/vllm-openai:latest lmsysorg/sglang:latest 2>/dev/null
	@echo "  Model WEIGHTS were kept. 'make clean-models' removes those."

clean-models:	## DESTRUCTIVE: delete the ~5GB LLM weight cache shared by vLLM and SGLang
	@echo "  Deleting vllm-hf-cache (~5GB of weights)."
	@echo "  Re-downloading needs ONE uninterrupted run: huggingface_hub does not resume"
	@echo "  across process restarts (S3b blocker #3), so a broken pull starts from zero."
	-docker volume rm vllm-hf-cache 2>/dev/null || docker volume rm $$($(PROJECT_CMD))_vllm-hf-cache 2>/dev/null
	@echo "  Weight cache removed."

clean-all: clean-images clean-models	## DESTRUCTIVE: images AND weights. The full reset.
	@echo "  Everything removed. Next 'make upv' is a cold build: expect 30-60 min."

# ── kind: keep the cluster in step with the images you just built ──────────────────────
kind-sync:	## Build -> load -> install into kind so the cluster runs the CURRENT code
	@echo "  syncing kind with the local images (this is the slow part of KIND=1)"
	@kind get clusters 2>/dev/null | grep -qx medbot || $(MAKE) --no-print-directory kind-up
	@$(MAKE) --no-print-directory images
	@$(MAKE) --no-print-directory kind-load
	@$(MAKE) --no-print-directory kind-install
	@echo "  kind ready:  kubectl get pods"

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

web-ci:	## The subset CI runs: everything that does NOT need a live backend
	cd apps/web && pnpm exec playwright test --project=chromium --grep-invert "@live"

web-a11y:	## WCAG 2.2 AA audit: axe on every route + keyboard and screen-reader checks
	cd apps/web && pnpm exec playwright test --project=chromium e2e/a11y.spec.ts

web-mobile:	## Mobile layout checks on a Pixel 7 viewport
	cd apps/web && pnpm exec playwright test --project=mobile e2e/mobile.spec.ts

web-shots:	## Regenerate docs/screenshots in both themes
	cd apps/web && pnpm exec playwright test e2e/screenshots.spec.ts --project=chromium

web-verify:	## PROVE the BFF proxy streams SSE rather than buffering (D23)
	@echo "Start the web server first: (cd apps/web && API_BASE_URL=http://localhost:5099 pnpm start)"
	cd apps/web && node scripts/verify-stream.mjs http://localhost:$${WEB_PORT:-5008}

# ── GPU tier on its own (when you want the engines without the rest) ───────────────────
gpu:	## Start vLLM + SGLang only (needs an NVIDIA GPU; first run pulls ~10GB)
	@nvidia-smi -L >/dev/null 2>&1 || { echo "  No NVIDIA GPU visible to Docker. Aborting."; exit 1; }
	$(DC_GPU) --profile gpu up -d
	@echo "  vLLM   http://localhost:$${VLLM_LOCAL_PORT:-5009}/v1/models"
	@echo "  SGLang http://localhost:$${SGLANG_LOCAL_PORT:-5010}/v1/models"
	@echo "  First boot downloads ~5GB of weights - do NOT interrupt it (S3b blocker #3)."

gpu-down:	## Stop vLLM + SGLang (KEEPS the weight cache)
	$(DC_GPU) --profile gpu down
	@echo "  Engines stopped. Weight cache kept - 'make clean-models' deletes it."

# ── kind node lifecycle: START/STOP (cheap) vs CREATE/DELETE (expensive) ──────────────
# kind has no start/stop of its own — a cluster is created or deleted. But its nodes are
# ordinary containers, so `docker stop` suspends the cluster and `docker start` resumes it
# with all state intact. That is what makes `make down` cheap and `make up` fast.
kind-start:	## Start the kind nodes (creates the cluster if it does not exist yet)
	@if kind get clusters 2>/dev/null | grep -qx "$(KIND_CLUSTER)"; then \
	  echo "  kind: starting nodes ($(KIND_CLUSTER))"; \
	  docker start $(KIND_NODES) >/dev/null 2>&1 || true; \
	  kind export kubeconfig --name $(KIND_CLUSTER) >/dev/null 2>&1 || true; \
	  n=0; \
	  until kubectl get nodes >/dev/null 2>&1 || [ $$n -ge 60 ]; do n=$$((n+1)); sleep 2; done; \
	  kubectl wait --for=condition=Ready nodes --all --timeout=120s >/dev/null 2>&1 \
	    && echo "  kind: nodes Ready" \
	    || echo "  kind: nodes started but NOT Ready - check 'kubectl get nodes'"; \
	else \
	  echo "  kind: no '$(KIND_CLUSTER)' cluster - creating one (~2 min, one time)"; \
	  kind create cluster --config infra/k8s/kind-cluster.yaml --wait 180s; \
	  kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml; \
	  kubectl patch deployment metrics-server -n kube-system --type=json -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'; \
	  echo "  kind: cluster created. Deploy the app with 'make kind-sync'."; \
	fi

kind-stop:	## Stop the kind nodes. Cluster, images and state all survive.
	@if kind get clusters 2>/dev/null | grep -qx "$(KIND_CLUSTER)"; then \
	  echo "  kind: stopping nodes (cluster kept - 'make kind-down' deletes it)"; \
	  docker stop $(KIND_NODES) >/dev/null 2>&1 || true; \
	  echo "  kind: nodes stopped"; \
	else \
	  echo "  kind: no cluster to stop"; \
	fi

kind-status:	## Are the kind nodes up, and is the chart installed?
	@kind get clusters 2>/dev/null | grep -qx "$(KIND_CLUSTER)" \
	  && echo "  cluster: $(KIND_CLUSTER) exists" || echo "  cluster: none"
	@docker ps --filter "name=$(KIND_CLUSTER)-" --format '  node: {{.Names}}  {{.Status}}' 2>/dev/null || true
	@kubectl get pods --no-headers 2>/dev/null | awk '{printf "  pod:  %-34s %s %s\n",$$1,$$2,$$3}' || echo "  pods: (API server unreachable)"

# ── Engines on their own: vLLM and SGLang, independently ──────────────────────────────
# Make targets cannot contain a space, so it is `make vllm-up`, not `make vllm up`.
#
# The -up/-down/-upv/-downv quartet mirrors the whole-stack one exactly:
#   -up     start it, keeping the weight cache
#   -down   stop it, keeping the weight cache
#   -upv    recreate the container from scratch (weights KEPT - see below)
#   -downv  stop it AND delete its ~5GB weight cache
#
# WHY -downv IS SHARED-AWARE: both engines read ONE cache volume, so deleting it from
# either target costs the OTHER engine its weights too. The target says so before acting.
ENGINE_HINT = @echo ""; echo "  Test it:"; echo ""

vllm-up:	## Start vLLM alone, then print how to test it
	@nvidia-smi -L >/dev/null 2>&1 || { echo "  No NVIDIA GPU visible to Docker."; exit 1; }
	$(DC_GPU) --profile gpu up -d vllm
	@$(MAKE) --no-print-directory vllm-test

vllm-down:	## Stop vLLM (weights kept)
	$(DC_GPU) --profile gpu stop vllm
	@echo "  vLLM stopped. Weight cache kept."

vllm-upv:	## Recreate the vLLM container from scratch (weights kept)
	$(DC_GPU) --profile gpu rm -sf vllm
	$(DC_GPU) --profile gpu up -d --force-recreate vllm
	@$(MAKE) --no-print-directory vllm-test

vllm-downv:	## Stop vLLM AND delete the shared ~5GB weight cache
	@echo "  WARNING: the weight cache is SHARED with SGLang - this costs both engines"
	@echo "  their weights, and huggingface_hub does not resume across restarts."
	$(DC_GPU) --profile gpu rm -sf vllm
	-docker volume rm $$($(PROJECT_CMD))_vllm-hf-cache 2>/dev/null || docker volume rm vllm-hf-cache 2>/dev/null
	@echo "  vLLM removed and weight cache deleted."

sglang-up:	## Start SGLang alone, then print how to test it
	@nvidia-smi -L >/dev/null 2>&1 || { echo "  No NVIDIA GPU visible to Docker."; exit 1; }
	$(DC_GPU) --profile gpu-sglang up -d sglang
	@$(MAKE) --no-print-directory sglang-test

sglang-down:	## Stop SGLang (weights kept)
	$(DC_GPU) --profile gpu-sglang stop sglang
	@echo "  SGLang stopped. Weight cache kept."

sglang-upv:	## Recreate the SGLang container from scratch (weights kept)
	$(DC_GPU) --profile gpu-sglang rm -sf sglang
	$(DC_GPU) --profile gpu-sglang up -d --force-recreate sglang
	@$(MAKE) --no-print-directory sglang-test

sglang-downv:	## Stop SGLang AND delete the shared ~5GB weight cache
	@echo "  WARNING: the weight cache is SHARED with vLLM - this costs both engines"
	@echo "  their weights, and huggingface_hub does not resume across restarts."
	$(DC_GPU) --profile gpu-sglang rm -sf sglang
	-docker volume rm $$($(PROJECT_CMD))_vllm-hf-cache 2>/dev/null || docker volume rm vllm-hf-cache 2>/dev/null
	@echo "  SGLang removed and weight cache deleted."

webui:	## Chat UI for BOTH engines (ChatGPT-style, model picker)
	$(DC_GPU) --profile webui up -d open-webui
	@echo ""
	@echo "  Open WebUI   http://localhost:$${OPEN_WEBUI_PORT:-5024}"
	@echo "  No login. Pick the model top-left to switch vLLM <-> SGLang."
	@echo "  This is the RAW engine: no retrieval, no citations, no medical guardrails."
	@echo "  The guarded product UI is http://localhost:$${WEB_PORT:-5008}."

vllm-test:	## How to verify vLLM is really generating (UI + CLI)
	@$(MAKE) --no-print-directory engine-guide ENGINE=vLLM PORT=$${VLLM_LOCAL_PORT:-5009} MODEL=$${VLLM_LOCAL_MODEL:-Qwen/Qwen2.5-7B-Instruct-AWQ}

sglang-test:	## How to verify SGLang is really generating (UI + CLI)
	@$(MAKE) --no-print-directory engine-guide ENGINE=SGLang PORT=$${SGLANG_LOCAL_PORT:-5010} MODEL=$${SGLANG_LOCAL_MODEL:-Qwen/Qwen2.5-7B-Instruct-AWQ}

engine-guide:
	@echo ""
	@echo "  ============================================================"
	@echo "   $(ENGINE) on http://localhost:$(PORT)"
	@echo "  ============================================================"
	@echo ""
	@echo "  FIRST BOOT downloads ~5GB and can take 10-20 min. Do NOT interrupt it:"
	@echo "  huggingface_hub does not resume, so a broken pull restarts from zero."
	@echo "    watch it:   docker logs -f $$(echo $(ENGINE) | tr A-Z a-z)"
	@echo ""
	@echo "  -- 1. is it up? (liveness, NOT capacity) -------------------"
	@echo "    curl -s localhost:$(PORT)/health"
	@echo "    curl -s localhost:$(PORT)/v1/models | python -m json.tool"
	@echo ""
	@echo "  -- 2. does it actually GENERATE? (the real check) ----------"
	@echo "    curl -s localhost:$(PORT)/v1/chat/completions \\"
	@echo "      -H 'content-type: application/json' \\"
	@echo "      -d '{\"model\":\"$(MODEL)\",\"messages\":[{\"role\":\"user\",\"content\":\"Name three symptoms of asthma.\"}],\"max_tokens\":80}'"
	@echo ""
	@echo "  -- 3. chat with it in a browser ----------------------------"
	@echo "    make webui     ->  http://localhost:$${OPEN_WEBUI_PORT:-5024}"
	@echo "    ChatGPT-style. Model picker switches vLLM <-> SGLang on the same prompt."
	@echo "    RAW engine: no retrieval, no citations, no guardrails."
	@echo ""
	@echo "  -- 4. is it on the GPU, and how fast? ----------------------"
	@echo "    nvidia-smi                 # the process and its VRAM"
	@echo "    make bench-local           # vLLM   k6: TTFT, tok/s, p99"
	@echo "    make bench-sglang          # SGLang k6: same harness, same prompts"
	@echo ""
	@echo "  -- 5. is the APP actually using it? -----------------------"
	@echo "    grep '^SERVING_CHAIN=' .env"
	@echo "    docker logs medbot-api 2>&1 | grep -i 'serving chain'"
	@echo "    curl -s -X POST localhost:$${API_PORT:-5007}/api/v1/query \\"
	@echo "      -H 'content-type: application/json' \\"
	@echo "      -d '{\"question\":\"What is chickenpox?\",\"stream\":false}' | grep -o '\"model_id\":\"[^\"]*\"'"
	@echo ""
	@echo "  Full guide: docs/VERIFY_STACK.md"
	@echo ""
