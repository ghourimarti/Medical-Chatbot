# ==========================================================================================
#  P5 MEDICAL RAG CHATBOT
# ==========================================================================================
#
#  Every section below has the same shape:
#      boxed title  ->  documentation  ->  the commands themselves
#
#  COMPOSITION RULE: a target that needs another tier CALLS THAT TIER'S TARGET.
#  `up` is up-data + up-app + up-obs + the engine + kind, not five copies of a
#  docker compose line. Change how the data tier starts in ONE place and every
#  caller follows.
#
#  Quick start:
#      make up            everything, engine chosen by ENGINE= below
#      make urls          where each service lives
#      make audit         is the whole application actually correct
#      make help          every target
# ==========================================================================================

.PHONY: api app audit audit-chaos audit-fresh backup-drill baseline bench-groq \
        bench-local bench-sglang cache-clear cache-flush cache-ls chaos chart-lint check \
        clean-all clean-images clean-models db down downv engine-guide eval-delta \
        eval-gate eval-mock eval-pipeline gpu gpu-down help images kill-off kill-on \
        kill-status kind-down kind-install kind-load kind-smoke kind-start kind-status \
        kind-stop kind-sync kind-up langfuse lint load-cache load-full load-guard logs \
        migrate obs ps reindex rescore seed service_ls sglang-down sglang-downv \
        sglang-test sglang-up sglang-upv smoke sync test tf-init tf-plan tf-validate \
        type up up-sglang up-vllm up-vllm-sglang upv urls validate vllm-down vllm-downv \
        vllm-test vllm-up vllm-upv web web-a11y web-build web-ci web-design web-e2e \
        web-mobile web-preview web-shots web-stop web-verify webui which-engine worker

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'


# ==========================================================================================
#  1. VARIABLES
# ==========================================================================================
#  Every variable in this file is declared HERE and nowhere else.
#
#  DC_* are docker compose invocations. DC_APP deliberately includes the DATA compose
#  file: docker-compose.app.yaml has `depends_on: postgres/qdrant/redis` and shares
#  their network, so compose must be given that file to resolve the references. The
#  separation you want lives at the SERVICE level instead - `up-app` names only the app
#  services, so it never starts a database.
#
#  DATA_VOLS is what `make downv` wipes. langfuse_clickhouse and langfuse_minio belong
#  with pg_data because Langfuse state is SPLIT across all three: Postgres holds the
#  org/project/keys, ClickHouse the spans, MinIO the raw payloads. Wiping one alone
#  re-runs the headless bootstrap into a fresh project while the others still hold
#  traces pointing at the old one.
# ------------------------------------------------------------------------------------------

DC_DATA := docker compose -f docker-compose.data.yaml
DC_APP  := docker compose -f docker-compose.data.yaml -f docker-compose.app.yaml
DC_OBS  := docker compose -f docker-compose.observability.yaml
DC_GPU  := docker compose -f docker-compose.gpu.yaml
DC_FULL := docker compose -f docker-compose.data.yaml -f docker-compose.app.yaml -f docker-compose.observability.yaml -f docker-compose.gpu.yaml
GPU ?= $(shell nvidia-smi -L >/dev/null 2>&1 && echo 1 || echo 0)
empty :=
space := $(empty) $(empty)
ENGINE ?= sglang
ALL_ENGINE_PROFILES := --profile gpu --profile gpu-sglang --profile webui
GPU_PROFILE := $(ENGINE_PROFILE)
ENGINE_HINT = @echo ""; echo "  Test it:"; echo ""
KIND ?= 1
KIND_CLUSTER := medbot
KIND_NODES   := $(KIND_CLUSTER)-control-plane $(KIND_CLUSTER)-worker $(KIND_CLUSTER)-worker2
DATA_VOLS  := pg_data qdrant_data localstack_data hf_models prom_data grafana_data \
              redisinsight_data langfuse_clickhouse langfuse_minio
KEEP_VOLS  := vllm-hf-cache
PROJECT_CMD = $(DC_DATA) config --format json | python -c "import sys,json;print(json.load(sys.stdin)['name'])"
NS = docker exec $(API_CTR) python -c "from medcore.config import get_settings;print(get_settings().cache_namespace)"
API_CTR := p5-medical-chatbot-api-1
REDIS_CTR := p5-medical-chatbot-redis-1


# ==========================================================================================
#  2. ENGINE / GPU PROFILE
# ==========================================================================================
#  ENGINE picks the local inference engine AND the failover chain together, because
#  they are one decision. Starting vLLM without naming it in SERVING_CHAIN - or naming
#  it without starting it - is the commonest way to believe you are benchmarking a
#  self-hosted engine while a hosted one quietly answers every request.
#
#      ENGINE=sglang  (default)   local-sglang,groq,openai
#      ENGINE=vllm                local-vllm,groq,openai
#      ENGINE=both                local-vllm,local-sglang,groq,openai
#      ENGINE=none                groq,openai
#
#  Every chain ends at OPENAI on purpose: it is the leg you pay for, so it is the one
#  that will answer when everything free is down. The moment it starts serving,
#  medbot_tokens_total{venue="openai"} climbs and medbot_request_cost_usd stops
#  reading $0 - that transition is how you learn a local engine died.
# ------------------------------------------------------------------------------------------

ifeq ($(GPU),1)
  ifeq ($(ENGINE),vllm)
    ENGINE_PROFILE := --profile gpu
    ENGINE_CHAIN   := local-vllm,groq,openai
    ENGINE_VLLM_FRAC   := 0.80
    ENGINE_SGLANG_FRAC := 0.45
    ENGINE_CTX     := 8192
    ENGINE_STOP    := sglang
  else ifeq ($(ENGINE),sglang)
    ENGINE_PROFILE := --profile gpu-sglang
    ENGINE_CHAIN   := local-sglang,groq,openai
    ENGINE_VLLM_FRAC   := 0.80
    # NOT 0.80, and NOT because a second engine is running - it has the card to itself.
    # The two flags are not equivalent and copying vLLM's number here OOM-killed SGLang:
    #
    #   vLLM   --gpu-memory-utilization  measures FREE memory and fits inside it
    #                                    ("Free memory on device (10.98/12.0 GiB)")
    #   SGLang --mem-fraction-static     is a fraction of TOTAL, and ignores whatever
    #                                    is already resident
    #
    # On a DESKTOP GPU that difference is decisive: Chrome, VS Code, Explorer and the
    # NVIDIA overlay were holding ~1.2 GB and fluctuating. 0.80 of 12 GB is 9.8 GB, plus
    # the desktop leaves nothing, and SGLang died with `CUDA error: out of memory` after
    # serving traffic happily for a while - a crash that only arrives when someone opens
    # another browser tab. 0.70 leaves ~3.5 GB of desktop headroom and still gives the
    # 7B AWQ weights (~5.5 GB) room for an 8k KV cache. Raise it only on a headless box.
    ENGINE_SGLANG_FRAC := 0.70
    ENGINE_CTX     := 8192
    ENGINE_STOP    := vllm
  else ifeq ($(ENGINE),both)
    ENGINE_PROFILE := --profile gpu --profile gpu-sglang
    ENGINE_CHAIN   := local-vllm,local-sglang,groq,openai
    # MEASURED, not chosen: 0.80 + 0.45 = 125% of a 12 GB card. vLLM did not error — it
    # wedged for 15 minutes at "Starting to load model" with no message at all, because
    # a CUDA allocator waiting on memory that will never arrive has nothing to report.
    # 0.42 each = 84%, leaving ~1.9 GB for CUDA contexts and fragmentation.
    ENGINE_VLLM_FRAC   := 0.42
    ENGINE_SGLANG_FRAC := 0.42
    # 8k context does not fit alongside a second copy of the weights. ~4.3 GB of AWQ
    # weights out of a 5.0 GB budget leaves well under 1 GB for the KV cache.
    ENGINE_CTX     := 4096
    ENGINE_STOP    :=
  else ifeq ($(ENGINE),none)
    ENGINE_PROFILE :=
    ENGINE_CHAIN   := groq,openai
    ENGINE_VLLM_FRAC   := 0.80
    ENGINE_SGLANG_FRAC := 0.45
    ENGINE_CTX     := 8192
    ENGINE_STOP    := vllm sglang
  else
    $(error ENGINE must be one of: vllm sglang both none  (got '$(ENGINE)'))
  endif
else
  # No GPU: the engines cannot start, so the chain must not claim they can. Listing a
  # dead leg costs every request its connect timeout before failing over.
  ENGINE_PROFILE :=
  ENGINE_CHAIN   := groq,openai
  ENGINE_VLLM_FRAC   := 0.80
  ENGINE_SGLANG_FRAC := 0.45
  ENGINE_CTX     := 8192
  ENGINE_STOP    :=
endif


# ==========================================================================================
#  3. vLLM
# ==========================================================================================
#  vLLM only - nothing here touches the app, data or observability tiers.
#
#  First boot downloads ~5GB of weights and MUST NOT be interrupted: huggingface_hub
#  does not resume across process restarts, so a broken pull starts from byte zero and
#  orphans the partial download.
# ------------------------------------------------------------------------------------------

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

vllm-test:	## How to verify vLLM is really generating (UI + CLI)
	@$(MAKE) --no-print-directory engine-guide ENGINE=vLLM PORT=$${VLLM_LOCAL_PORT:-5009} MODEL=$${VLLM_LOCAL_MODEL:-Qwen/Qwen2.5-7B-Instruct-AWQ}


# ==========================================================================================
#  4. SGLANG
# ==========================================================================================
#  SGLang only, mirroring the vLLM section.
#
#  MEMORY IS NOT INTERCHANGEABLE WITH vLLM. `--gpu-memory-utilization` measures FREE
#  memory and fits inside it; SGLang's `--mem-fraction-static` is a fraction of TOTAL
#  and ignores whatever is already resident. On a desktop GPU where the browser and
#  editor hold ~1.2GB, copying vLLM's 0.80 here OOM-kills SGLang after it has been
#  serving happily for hours.
# ------------------------------------------------------------------------------------------

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

webui:	## Chat UI for BOTH engines (ChatGPT-style, model picker)
	$(DC_GPU) --profile webui up -d open-webui
	@echo ""
	@echo "  Open WebUI   http://localhost:$${OPEN_WEBUI_PORT:-5024}"
	@echo "  No login. Pick the model top-left to switch vLLM <-> SGLang."
	@echo "  This is the RAW engine: no retrieval, no citations, no medical guardrails."
	@echo "  The guarded product UI is http://localhost:$${WEB_PORT:-5008}."

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


# ==========================================================================================
#  5. DATA TIER
# ==========================================================================================
#  Postgres, Qdrant, Redis, LocalStack - and the jobs that populate them.
#
#  Nothing above this tier can start usefully without it: the API's readiness probe
#  requires a NON-EMPTY vector index, so `up-app` against an unseeded Qdrant gives you
#  a container that never becomes ready.
# ------------------------------------------------------------------------------------------

up-data:	## DATA only: Postgres, Qdrant, Redis, LocalStack
	$(DC_DATA) up -d --wait

down-data:	## Stop the data tier (volumes kept)
	$(DC_DATA) down

db: up-data	## Alias kept for older docs and muscle memory

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

reindex:  ## Ingest corpus -> new collection -> atomic alias swap (D11). LIMIT=N for dev only
	uv run medworker-ingest --direct $${LIMIT:+--limit $$LIMIT}

worker:	## Start the ingestion worker (profile-gated: it needs an SQS queue to exist)
	$(DC_DATA) exec -T localstack awslocal sqs create-queue --queue-name medbot-ingestion || true
	$(DC_APP) --profile worker up -d worker
	@echo "  worker started — tail it with: make logs"


# ==========================================================================================
#  6. APP TIER
# ==========================================================================================
#  ml-service, api, web - and ONLY those. The compose invocation includes the data
#  file so `depends_on` resolves, but the target names app services explicitly, so
#  this never starts a database.
# ------------------------------------------------------------------------------------------

up-app:	## APP only: ml-service, api, web - NEVER a database
	@# The data compose file is passed so `depends_on` and the shared network
	@# resolve, but the SERVICES are named explicitly. That is what keeps this
	@# target from starting Postgres behind your back.
	$(DC_APP) up --build -d --wait ml-service api web

down-app:	## Stop only the app services
	$(DC_APP) stop ml-service api web

app: up-app	## Alias kept for older docs and muscle memory

# ── Native dev (run the API on the host against the containerized data tier) ────────────
api:  ## Run the query service on $$API_PORT (default 5007)
	uv run uvicorn medapi.main:app --host 127.0.0.1 --port $${API_PORT:-5007}

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


# ==========================================================================================
#  7. OBSERVABILITY TIER
# ==========================================================================================
#  OTel Collector, Prometheus, Grafana, Langfuse (+ClickHouse/MinIO/worker), Jaeger,
#  RedisInsight.
#
#  Grafana needs no login (anonymous Viewer). Langfuse needs exactly one - it has no
#  anonymous mode - and `make langfuse` prints the bootstrapped credentials rather
#  than making you hunt for them.
# ------------------------------------------------------------------------------------------

up-obs:	## OBSERVABILITY only: OTel, Prometheus, Grafana, Langfuse, Jaeger
	@# Needs the data tier: Langfuse keeps its org/project/keys in that Postgres.
	$(DC_OBS) up -d
	@$(DC_OBS) --profile seed up -d redisinsight-seed >/dev/null 2>&1 || true

down-obs:	## Stop the observability tier
	$(DC_OBS) down

obs: up-obs	## Alias kept for older docs and muscle memory

urls:	## Print every service URL (no credentials)
	@python scripts/service_board.py --mode urls

service_ls:	## FULL inventory WITH credentials: DBs, engines, dashboards, connection strings
	@python scripts/service_board.py --mode full

langfuse:	## Open Langfuse and print the ONE login it needs (no anonymous mode exists)
	@echo ""
	@echo "  Langfuse   http://localhost:$${LANGFUSE_WEB_PORT:-5015}"
	@echo ""
	@echo "  Sign in ONCE - Langfuse has no anonymous/viewer mode the way Grafana does,"
	@echo "  so this is the one dashboard that cannot be made login-free. The session"
	@echo "  then persists in the browser."
	@echo ""
	@echo "    email     $${LANGFUSE_INIT_USER_EMAIL:-admin@medbot.local}"
	@echo "    password  $${LANGFUSE_INIT_USER_PASSWORD:-medbot-admin-1234}"
	@echo ""
	@echo "  You do NOT create a project and you do NOT copy any API keys: the org,"
	@echo "  project and BOTH keys are bootstrapped from .env on first boot, and the API"
	@echo "  already sends with the same pair. Traces are there when you land."
	@echo ""
	@python -c "import webbrowser,os;webbrowser.open('http://localhost:'+os.environ.get('LANGFUSE_WEB_PORT','5015'))" 2>/dev/null || true


# ==========================================================================================
#  8. KIND (local Kubernetes)
# ==========================================================================================
#  kind runs its nodes as ORDINARY DOCKER CONTAINERS, so without these targets they
#  survive `make down` and sit there holding RAM while looking like part of the stack.
#
#      make down   stops the nodes, cluster and state PRESERVED
#      make downv  deletes the cluster
#      KIND=0      ignores kind entirely
#
#  kind-start always re-exports the kubeconfig: a restarted control-plane gets a new
#  API-server port, and the stale config then fails with "current-context is not set"
#  - which reads like a broken cluster rather than a stale pointer at a healthy one.
# ------------------------------------------------------------------------------------------

kind-start:	## Start (or create) the kind cluster and refresh kubeconfig
	@if ! kind get clusters 2>/dev/null | grep -qx "$(KIND_CLUSTER)"; then \
	  echo "  creating kind cluster '$(KIND_CLUSTER)' (~2 min)"; \
	  kind create cluster --config infra/k8s/kind-cluster.yaml --wait 180s; \
	else \
	  docker start $(KIND_NODES) >/dev/null 2>&1 || true; \
	  echo "  kind cluster '$(KIND_CLUSTER)' nodes started"; \
	fi
	@# ALWAYS re-export: a restarted control-plane gets a new API-server port, and the
	@# stale kubeconfig then fails with "current-context is not set" - which reads like a
	@# broken cluster rather than a stale pointer at a healthy one.
	@kind export kubeconfig --name $(KIND_CLUSTER) >/dev/null 2>&1 || true

kind-stop:	## Stop the kind nodes, PRESERVING the cluster and its state
	@docker stop $(KIND_NODES) >/dev/null 2>&1 || true
	@echo "  kind nodes stopped (cluster preserved - 'make downv' deletes it)"

kind-status:	## Nodes and pods, or a clear reason why not
	@if ! kind get clusters 2>/dev/null | grep -qx "$(KIND_CLUSTER)"; then \
	  echo "  no kind cluster '$(KIND_CLUSTER)' - 'make kind-start' creates one"; \
	else \
	  kubectl get nodes 2>/dev/null || echo "  nodes unreachable; try 'make kind-start'"; \
	  kubectl get pods 2>/dev/null || true; \
	fi

kind-down:	## DESTRUCTIVE: delete the kind cluster entirely
	@helm uninstall medbot >/dev/null 2>&1 || true
	@kind delete cluster --name $(KIND_CLUSTER) >/dev/null 2>&1 || true
	@echo "  kind cluster '$(KIND_CLUSTER)' deleted"

kind-load:	## Side-load images into kind (nodes cannot see the host daemon)
	kind load docker-image medbot-api:0.1.0    --name $(KIND_CLUSTER)
	kind load docker-image medbot-ml:0.1.0     --name $(KIND_CLUSTER)
	kind load docker-image medbot-worker:0.1.0 --name $(KIND_CLUSTER)

kind-install:	## helm install into kind (needs GROQ_API_KEY exported)
	helm upgrade --install medbot infra/k8s/medbot -f infra/k8s/medbot/values-kind.yaml --set secrets.groqApiKey="$$GROQ_API_KEY" --set secrets.sessionSecret="kind-dev-session-secret-not-for-prod"
	kubectl get pods

kind-sync:	## Rebuild images, side-load them, and roll the deployments
	@$(MAKE) --no-print-directory kind-load
	kubectl rollout restart deployment/medbot-api deployment/medbot-ml 2>/dev/null || true

kind-smoke:	## Port-forward + health check (run kind-install first)
	@echo "  kubectl port-forward svc/medbot-api 8000:80"
	@echo "  curl -s localhost:8000/healthz"

kind-up: kind-start	## Alias for kind-start (kept: older docs and scripts call it)


# ==========================================================================================
#  9. COMPOSITE LIFECYCLE
# ==========================================================================================
#  up / upv / down / downv - COMPOSED FROM THE SECTIONS ABOVE, never from raw compose
#  lines. That is the whole point: change how the data tier starts in section 5 and
#  every one of these follows automatically.
#
#  Sequenced with explicit $(MAKE) calls rather than prerequisites, because make gives
#  prerequisites no guaranteed order under -j and the app tier genuinely needs the data
#  tier healthy first.
#
#  The cost of composing: four sequential --wait calls instead of one combined start,
#  so `make up` is ~30-60s slower than it was. Bought deliberately, for a file you can
#  read.
#
#      up     start everything          down   stop everything, DATA KEPT
#      upv    wipe + rebuild + seed     downv  stop everything, DATA DESTROYED
# ------------------------------------------------------------------------------------------

up-engine:	## Start the local engine named by ENGINE= (nothing when GPU=0)
	@if [ -z "$(ENGINE_PROFILE)" ]; then \
	  echo "  no local engine (GPU=0 or ENGINE=none) - chain is hosted-only"; \
	else \
	  if [ -n "$(ENGINE_STOP)" ]; then \
	    $(DC_GPU) $(ALL_ENGINE_PROFILES) rm -sf $(ENGINE_STOP) >/dev/null 2>&1 || true; \
	  fi; \
	  $(DC_GPU) $(ENGINE_PROFILE) up -d; \
	  echo "  engine started: ENGINE=$(ENGINE)"; \
	fi

down-engine:	## Stop EVERY engine, whichever one is currently selected
	@$(DC_GPU) $(ALL_ENGINE_PROFILES) down >/dev/null 2>&1 || true
	@echo "  engines stopped"

up:		## EVERYTHING - composed from the tier targets above
	@$(MAKE) --no-print-directory up-data
	@$(MAKE) --no-print-directory up-app
	@$(MAKE) --no-print-directory up-obs
	@$(MAKE) --no-print-directory up-engine
	@if [ "$(KIND)" = "1" ]; then $(MAKE) --no-print-directory kind-start; fi
	@echo ""
	@echo "  ENGINE=$(ENGINE)   SERVING_CHAIN=$(ENGINE_CHAIN)"
	@$(MAKE) --no-print-directory urls
	@echo "  Which engine actually answered:  make which-engine"

upv:		## FROM SCRATCH: wipe volumes, rebuild, start every tier, migrate, ingest.
	@echo "  make upv - clean rebuild from scratch (DESTROYS local data volumes)."
	@$(MAKE) --no-print-directory downv
	@$(MAKE) --no-print-directory up-data
	@$(MAKE) --no-print-directory migrate
	@# Seed BEFORE the app tier: the API's readiness probe requires a NON-EMPTY vector
	@# index, so an app started against an unseeded Qdrant never becomes ready.
	@$(MAKE) --no-print-directory seed
	@$(MAKE) --no-print-directory up-app
	@$(MAKE) --no-print-directory up-obs
	@$(MAKE) --no-print-directory up-engine
	@if [ "$(KIND)" = "1" ]; then $(MAKE) --no-print-directory kind-start; fi
	@echo ""
	@echo "  Up from scratch - every tier running, schema created, corpus ingested."
	@$(MAKE) --no-print-directory urls

down:		## Stop every tier. DATA VOLUMES ARE KEPT.
	@$(MAKE) --no-print-directory down-engine
	@$(MAKE) --no-print-directory down-obs
	@$(MAKE) --no-print-directory down-app
	@$(MAKE) --no-print-directory down-data
	@if [ "$(KIND)" = "1" ]; then $(MAKE) --no-print-directory kind-stop; fi
	@echo "  stopped. data volumes kept - 'make downv' destroys them."

downv:	## DESTRUCTIVE: stop every tier AND delete DATA volumes. Images + weights kept.
	@$(MAKE) --no-print-directory down-engine
	@$(MAKE) --no-print-directory down-obs
	@$(MAKE) --no-print-directory down-app
	$(DC_FULL) $(ALL_ENGINE_PROFILES) down -v --remove-orphans
	@P=$$($(PROJECT_CMD)); \
	  docker volume rm $(foreach v,$(DATA_VOLS),$${P}_$(v)) 2>/dev/null || true; \
	  echo "  Wiped: $(DATA_VOLS)"; \
	  echo "  KEPT:  $(KEEP_VOLS) - LLM weights (~5GB, and huggingface_hub does NOT"; \
	  echo "         resume across restarts, so re-downloading means one uninterrupted run)"; \
	  echo "  KEPT:  all docker images. 'make clean-images' removes those, deliberately separate."
	@if [ "$(KIND)" = "1" ]; then $(MAKE) --no-print-directory kind-down; fi

ps:		## Status of every container in the stack
	$(DC_FULL) ps

logs:	## Tail logs for the whole stack (Ctrl-C to stop)
	$(DC_FULL) logs -f --tail=100

up-vllm:	## Whole app served by vLLM        (SERVING_CHAIN=local-vllm,groq)
	@$(MAKE) --no-print-directory up ENGINE=vllm

up-sglang:	## Whole app served by SGLang      (SERVING_CHAIN=local-sglang,groq)
	@$(MAKE) --no-print-directory up ENGINE=sglang

up-vllm-sglang:	## Whole app, BOTH engines        (SERVING_CHAIN=local-vllm,local-sglang,groq)
	@$(MAKE) --no-print-directory up ENGINE=both

which-engine:	## Prove which venue served the last answer (guessing is not verification)
	@echo "  configured : $$(docker exec p5-medical-chatbot-api-1 printenv SERVING_CHAIN 2>/dev/null || grep ^SERVING_CHAIN= .env | cut -d= -f2)"
	@echo "  resolved   : $$(docker logs p5-medical-chatbot-api-1 2>&1 | grep -i 'serving chain' | tail -1 | sed 's/.*serving chain: //')"
	@printf "  engine has : "
	@curl -s --max-time 5 http://localhost:$${VLLM_LOCAL_PORT:-5009}/v1/models 2>/dev/null 	  | python -c "import sys,json;print(','.join(m['id'] for m in json.load(sys.stdin)['data']))" 2>/dev/null 	  || curl -s --max-time 5 http://localhost:$${SGLANG_LOCAL_PORT:-5010}/v1/models 2>/dev/null 	  | python -c "import sys,json;print(','.join(m['id'] for m in json.load(sys.stdin)['data']))" 2>/dev/null 	  || echo "(no local engine reachable)"
	@printf "  answering  : "
	@curl -s -X POST localhost:$${API_PORT:-5007}/api/v1/query -H 'content-type: application/json' 	  -d '{"question":"What is asthma?","stream":false}' --max-time 180 	  | python -c "import sys,json;print(json.load(sys.stdin).get('model_id','(no answer)'))" 2>/dev/null || echo "(query failed)"


# ==========================================================================================
#  10. QUALITY GATES
# ==========================================================================================
#  Lint, types, tests, and the evaluation harness.
#
#  `make audit` is the deep one: it asks whether the product is CORRECT, not merely
#  alive - are citations on topic, are refusals excluded from the cache, does the
#  engine serve the model the API names, is every declared metric actually written.
# ------------------------------------------------------------------------------------------

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

baseline:  ## Re-run the demo/ baseline (needs GROQ_API_KEY in .env; ~$1, ~25 min)
	uv run medeval run --target demo --dataset packages/eval/datasets/golden_core_v2.jsonl

audit:	## BRUTAL full-application audit, one command. Restores anything it changes.
	@python scripts/audit.py $(ARGS)

audit-fresh:	## Same, but clear the answer cache first so nothing is served from cache
	@python scripts/audit.py --fresh

audit-chaos:	## Same, plus stop/start dependencies to prove degradation (restarts them)
	@python scripts/audit.py --fresh --chaos

eval-mock:  ## Keyless end-to-end eval smoke (no API key needed)
	uv run medeval run --target mock --dataset packages/eval/datasets/golden_seed_v0.jsonl --skip-ragas

eval-pipeline:  ## Evaluate the CURRENT pipeline (needs Qdrant + full index; ~35 min)
	uv run medeval run --target pipeline --dataset packages/eval/datasets/golden_core_v2.jsonl

eval-gate:  ## BLOCKING quality gate: exits 1 if any D19 threshold is unmet (S6.11)
	uv run medeval compare --before demo --after pipeline --out eval-reports/delta.md --gate

eval-delta:  ## Print the before/after delta table without gating
	uv run medeval compare --before demo --after pipeline

rescore:  ## Recompute deterministic metrics on the latest pipeline report (no model calls)
	uv run medeval rescore $$(ls -t eval-reports/pipeline-*.json | head -1)

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


# ==========================================================================================
#  11. WEB TIER
# ==========================================================================================
#  The Next.js frontend: dev server, CI checks, accessibility, e2e, screenshots.
# ------------------------------------------------------------------------------------------

# --- S10 web tier -------------------------------------------------------------
# apps/web is Node, deliberately EXCLUDED from the uv workspace (see pyproject.toml):
# the `apps/*` glob would claim it as a Python member and break `uv run` repo-wide.
web:	## Run the Next.js dev server on $$WEB_PORT (default 5008); needs `make app`
	cd apps/web && pnpm install --silent && pnpm dev

web-a11y:	## WCAG 2.2 AA audit: axe on every route + keyboard and screen-reader checks
	cd apps/web && pnpm exec playwright test --project=chromium e2e/a11y.spec.ts

web-build:	## Web gate: contrast + contract drift + typecheck + build
	cd apps/web && pnpm install --silent && pnpm check

web-ci:	## The subset CI runs: everything that does NOT need a live backend
	cd apps/web && pnpm exec playwright test --project=chromium --grep-invert "@live"

web-design:	## Open the design-system gallery (needs `make web`)
	@echo "http://localhost:$${WEB_PORT:-5008}/design

web-e2e:	## Browser verification of the four answer kinds (needs the full stack up)
	cd apps/web && pnpm exec playwright test --project=chromium e2e/answer-kinds.spec.ts

web-mobile:	## Mobile layout checks on a Pixel 7 viewport
	cd apps/web && pnpm exec playwright test --project=mobile e2e/mobile.spec.ts

web-preview: web-stop	## Build AND serve the production web tier (always builds first)
	@echo 'note: plain next-start fails when .next is missing or a build was interrupted;'
	@echo 'this target always builds first, and web-stop frees the port before binding.'
	cd apps/web && pnpm install --silent && API_BASE_URL=$${API_BASE_URL:-http://localhost:5007} pnpm preview

web-shots:	## Regenerate docs/screenshots in both themes
	cd apps/web && pnpm exec playwright test e2e/screenshots.spec.ts --project=chromium

web-stop:	## Free $$WEB_PORT by stopping whatever is listening on it
	@PORT=$${WEB_PORT:-5008}; 	PID=$$(netstat -ano 2>/dev/null | grep ":$$PORT " | grep -i LISTENING | head -1 | awk '{print $$NF}'); 	if [ -n "$$PID" ]; then 		echo "stopping PID $$PID on :$$PORT"; 		taskkill //PID $$PID //F >/dev/null 2>&1 || kill -9 $$PID 2>/dev/null || true; 	else echo "nothing listening on :$$PORT"; fi

web-verify:	## PROVE the BFF proxy streams SSE rather than buffering (D23)
	@echo "Start the web server first: (cd apps/web && API_BASE_URL=http://localhost:5099 pnpm start)"
	cd apps/web && node scripts/verify-stream.mjs http://localhost:$${WEB_PORT:-5008}


# ==========================================================================================
#  12. OPERATIONS
# ==========================================================================================
#  Cache, kill switch, images, Terraform, Helm.
#
#  NEVER hand-type a Redis key. The cache namespace is COMPUTED - prompt/corpus/index
#  version, collection, and a digest of every model that could serve - so the literal
#  `medbot:killswitch:llm_enabled` does not exist and setting it silently does nothing.
#  These targets ask the API for its own namespace.
# ------------------------------------------------------------------------------------------

cache-clear:	## Delete cached ANSWERS so a repeated question is re-generated (keeps rate limits)
	@N=$$($(NS)); K=$$(docker exec $(REDIS_CTR) redis-cli --scan --pattern "$$N:ans:*"); C=$$(echo "$$K" | grep -c . || true); if [ -n "$$K" ]; then echo "$$K" | xargs -r docker exec -i $(REDIS_CTR) redis-cli del >/dev/null; fi; echo "  cleared $${C:-0} cached answers"
	@echo "  Rate-limit counters kept. 'make cache-flush' wipes the whole Redis db."

cache-flush:	## DESTRUCTIVE: wipe ALL of Redis (answers, embeddings, rate limits, kill switch)
	@docker exec $(REDIS_CTR) redis-cli flushdb >/dev/null && echo "  Redis db flushed."

cache-ls:	## Show what is cached right now, grouped by kind
	@N=$$($(NS)); echo "  namespace: $$N"; docker exec $(REDIS_CTR) redis-cli --scan --pattern "$$N:*" | sed "s|$$N:||; s|:.*||" | sort | uniq -c | sed "s/^/  /"

kill-on:	## Kill switch ON = generation DISABLED (cache-only, degraded answers)
	@N=$$($(NS)); docker exec $(REDIS_CTR) redis-cli set "$$N:killswitch:llm_enabled" 0 >/dev/null; echo "  Generation DISABLED. Queries now return kind=degraded."

kill-off:	## Kill switch OFF = generation ENABLED (the normal state)
	@N=$$($(NS)); docker exec $(REDIS_CTR) redis-cli del "$$N:killswitch:llm_enabled" >/dev/null; echo "  Generation ENABLED."
	@echo "  NOTE: LLM_ENABLED=false in .env is a FLOOR - no Redis value can lift it."

kill-status:	## Is generation currently enabled?
	@N=$$($(NS)); V=$$(docker exec $(REDIS_CTR) redis-cli get "$$N:killswitch:llm_enabled"); if [ "$$V" = "0" ]; then echo "  DISABLED (kill switch set)"; else echo "  ENABLED"; fi

# ── S15 / Phase 6: kind ───────────────────────────────────────────────────────────────
images:  ## Build all three service images (heavy: torch; first run 10-25 min)
	docker build -f apps/api/Dockerfile        -t medbot-api:0.1.0    .
	docker build -f apps/ml-service/Dockerfile -t medbot-ml:0.1.0     .
	docker build -f apps/worker/Dockerfile     -t medbot-worker:0.1.0 .
	docker images --filter=reference='medbot-*'

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
