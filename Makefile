# P5 Medical RAG Chatbot — developer entrypoints.
# Every target is a documented, reproducible command (no tribal knowledge).

.DEFAULT_GOAL := help
.PHONY: help sync lint type test check eval-mock baseline validate up down api reindex smoke \
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

bench-local:  ## Engine benchmark against local vLLM (needs the container running on :1110)
	k6 run -e BASE_URL=http://localhost:1110/v1 -e MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ \
	  -e LABEL=local-vllm tests/load/engine_benchmark.js

bench-sglang:  ## Engine benchmark against local SGLang (needs the container running on :1111)
	k6 run -e BASE_URL=http://localhost:1111/v1 -e MODEL=Qwen/Qwen2.5-7B-Instruct-AWQ \
	  -e LABEL=local-sglang tests/load/engine_benchmark.js

rescore:  ## Recompute deterministic metrics on the latest pipeline report (no model calls)
	uv run medeval rescore $$(ls -t eval-reports/pipeline-*.json | head -1)

up:  ## Start local infra (Qdrant)
	docker compose up -d

down:  ## Stop local infra (keeps volumes)
	docker compose down

api:  ## Run the query service on $$API_PORT (default 1107)
	uv run uvicorn medapi.main:app --host 127.0.0.1 --port $${API_PORT:-1107}

reindex:  ## Ingest corpus -> new collection -> atomic alias swap (D11). LIMIT=N for dev only
	uv run medworker-ingest --direct $${LIMIT:+--limit $$LIMIT}

load-cache:  ## P5.2 tier A: cache-hit path — HTTP/async/Redis ceiling (no LLM)
	k6 run -e TIER=cache -e PEAK_RATE=$${PEAK_RATE:-200} tests/load/system_load.js

load-full:  ## P5.2 tier B: full pipeline, every request a cache miss (needs vLLM)
	k6 run -e TIER=full -e PEAK_RATE=$${PEAK_RATE:-8} tests/load/system_load.js

load-guard:  ## P5.2 tier C: abuse traffic — cost of refusing before retrieval
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
	@curl -s -X POST localhost:$${API_PORT:-1107}/api/v1/query \
		-H 'content-type: application/json' \
		--data-binary '{"question":"What is an abscess?","stream":false}'
	@echo "\n--- out-of-corpus (expect kind=no_answer, 0 citations) ---"
	@curl -s -X POST localhost:$${API_PORT:-1107}/api/v1/query \
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

tf-validate:  ## terraform fmt + validate — proves the HCL is correct OFFLINE
	terraform -chdir=infra/terraform/aws fmt -check -recursive
	terraform -chdir=infra/terraform/aws validate

tf-plan:  ## terraform plan — NEEDS AWS credentials (Track D); never applies
	terraform -chdir=infra/terraform/aws plan -input=false
