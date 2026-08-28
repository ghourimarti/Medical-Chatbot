# P5 Medical RAG Chatbot — developer entrypoints.
# Every target is a documented, reproducible command (no tribal knowledge).

.DEFAULT_GOAL := help
.PHONY: web web-ci web-a11y web-mobile web-e2e web-shots web-stop web-preview web-design web-build web-verify help sync lint type test check eval-mock baseline validate api reindex smoke         db app obs up upv down downv ps logs migrate seed worker urls langfuse cache-clear cache-flush cache-ls kill-on kill-off kill-status up-vllm up-sglang up-vllm-sglang which-engine \
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

# ── WHICH ENGINE SERVES ───────────────────────────────────────────────────────────────
# ENGINE picks the local inference engine AND the failover chain together, deliberately.
# They are one decision: starting vLLM without putting it in SERVING_CHAIN (or listing it
# in the chain without starting it) is the single most common way to believe you are
# benchmarking a self-hosted engine while Groq quietly answers every request. Splitting
# them across two files is what makes that mistake easy, so this couples them.
#
#   ENGINE=sglang  (default)  chain: local-sglang,groq
#   ENGINE=vllm               chain: local-vllm,groq
#   ENGINE=both               chain: local-vllm,local-sglang,groq
#   ENGINE=none               chain: groq            (hosted only, no GPU needed)
#
# Edit the default below, or override per invocation:  make up ENGINE=sglang
# The named shortcuts (up-vllm / up-sglang / up-vllm-sglang) just set it for you.
empty :=
space := $(empty) $(empty)
ENGINE ?= sglang

# Every engine profile, used by `down`/`downv` REGARDLESS of the current ENGINE. Tearing
# down only the selected profile is how you end up with a stale sglang container holding
# 5 GB of VRAM after switching to vLLM — invisible until the next start fails to allocate.
ALL_ENGINE_PROFILES := --profile gpu --profile gpu-sglang --profile webui

ifeq ($(GPU),1)
  ifeq ($(ENGINE),vllm)
    ENGINE_PROFILE := --profile gpu
    ENGINE_CHAIN   := local-vllm,groq
    ENGINE_VLLM_FRAC   := 0.80
    ENGINE_SGLANG_FRAC := 0.45
    ENGINE_CTX     := 8192
    ENGINE_STOP    := sglang
  else ifeq ($(ENGINE),sglang)
    ENGINE_PROFILE := --profile gpu-sglang
    ENGINE_CHAIN   := local-sglang,groq
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
    ENGINE_CHAIN   := local-vllm,local-sglang,groq
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
    ENGINE_CHAIN   := groq
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
  ENGINE_CHAIN   := groq
  ENGINE_VLLM_FRAC   := 0.80
  ENGINE_SGLANG_FRAC := 0.45
  ENGINE_CTX     := 8192
  ENGINE_STOP    :=
endif

# Kept as an alias so nothing that referenced GPU_PROFILE silently starts doing nothing.
GPU_PROFILE := $(ENGINE_PROFILE)

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

# SERVING_CHAIN is exported so docker compose interpolates it into the api container,
# overriding the value in .env for this invocation only. The engine fractions ride along
# for ENGINE=both, where the .env defaults would oversubscribe the card.
up upv up-vllm up-sglang up-vllm-sglang: export SERVING_CHAIN := $(ENGINE_CHAIN)
up upv up-vllm up-sglang up-vllm-sglang: export VLLM_GPU_MEMORY_UTILIZATION := $(ENGINE_VLLM_FRAC)
up upv up-vllm up-sglang up-vllm-sglang: export SGLANG_MEM_FRACTION := $(ENGINE_SGLANG_FRAC)
up upv up-vllm up-sglang up-vllm-sglang: export VLLM_MAX_MODEL_LEN := $(ENGINE_CTX)
up upv up-vllm up-sglang up-vllm-sglang: export SGLANG_MAX_MODEL_LEN := $(ENGINE_CTX)

up:		## EVERYTHING: data + app + observability (+ engine per ENGINE=, + kind if KIND=1)
	@# Stop the engine we are NOT using. `docker compose up` with a different profile does
	@# not stop containers outside it, so switching vllm->sglang would leave both running
	@# and oversubscribe the card — the exact deadlock ENGINE=both is tuned to avoid.
	@if [ -n "$(ENGINE_STOP)" ]; then 	  docker rm -f $$(docker ps -q --filter "name=$(subst $(space),|,$(ENGINE_STOP))") >/dev/null 2>&1 || true; 	  $(DC_GPU) $(ALL_ENGINE_PROFILES) rm -sf $(ENGINE_STOP) >/dev/null 2>&1 || true; 	fi
	$(DC_FULL) $(ENGINE_PROFILE) up --build -d --wait
	@$(DC_OBS) --profile seed up -d redisinsight-seed >/dev/null 2>&1 || true
	@echo ""
	@echo "  ENGINE=$(ENGINE)   SERVING_CHAIN=$(ENGINE_CHAIN)"
	@if [ "$(GPU)" = "0" ]; then 	  echo "  No NVIDIA GPU detected - local engines SKIPPED, hosted only."; 	elif [ "$(ENGINE)" = "both" ]; then 	  echo "  Both engines share one card: $(ENGINE_VLLM_FRAC) + $(ENGINE_SGLANG_FRAC) VRAM, $(ENGINE_CTX) ctx."; 	  echo "  This is a FAILOVER REHEARSAL, not the steady state. For benchmarking one"; 	  echo "  engine at full context use 'make up-vllm' or 'make up-sglang'."; 	fi
	@if [ "$(KIND)" = "1" ]; then $(MAKE) --no-print-directory kind-start; fi
	@$(MAKE) --no-print-directory urls
	@echo "  Which engine actually answered:  make which-engine"

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
	$(DC_FULL) $(ALL_ENGINE_PROFILES) down
	@if [ "$(KIND)" = "1" ]; then $(MAKE) --no-print-directory kind-stop; fi

# Volume names are prefixed with the compose PROJECT name, which is derived from the repo
# directory — and this repo's path contains spaces and an `&`, which break $(notdir
# $(CURDIR)). So ask compose for the project name at runtime instead of guessing it.
# langfuse_clickhouse and langfuse_minio belong here with pg_data specifically because
# Langfuse's state is SPLIT across all three: Postgres holds the org/project/keys,
# ClickHouse holds the spans, MinIO holds the raw payloads. Wiping Postgres alone
# re-runs the headless bootstrap into a fresh project while ClickHouse still holds
# traces pointing at the old one - a UI that shows nothing and a store that is full.
DATA_VOLS  := pg_data qdrant_data localstack_data hf_models prom_data grafana_data \n              redisinsight_data langfuse_clickhouse langfuse_minio
# NOT wiped by `make downv`, on purpose. `vllm-hf-cache` holds the ~5GB of LLM weights
# shared by vLLM and SGLang. S3b blocker #3: huggingface_hub does not resume across
# process restarts, so replacing this volume costs one uninterrupted download, not a
# resumable one. `make clean-models` removes it when you actually mean to.
KEEP_VOLS  := vllm-hf-cache
PROJECT_CMD = $(DC_DATA) config --format json | python -c "import sys,json;print(json.load(sys.stdin)['name'])"

downv:	## DESTRUCTIVE: stop every tier AND delete DATA volumes. KEEPS images + LLM weights.
	$(DC_FULL) $(ALL_ENGINE_PROFILES) down -v --remove-orphans
	@P=$$($(PROJECT_CMD)); 	  docker volume rm $(foreach v,$(DATA_VOLS),$${P}_$(v)) 2>/dev/null || true; 	  echo "  Wiped: $(DATA_VOLS)"; 	  echo "  KEPT:  $(KEEP_VOLS) - LLM weights (~5GB, and huggingface_hub does NOT"; 	  echo "         resume across restarts, so re-downloading means one uninterrupted run)"; 	  echo "  KEPT:  all docker images. 'make clean-images' removes those, deliberately separate."
	@if [ "$(KIND)" = "1" ]; then $(MAKE) --no-print-directory kind-down; fi

upv:		## FROM SCRATCH in ONE command: wipe volumes, rebuild images, start every tier,
		## create the schema, ingest the corpus. The full cold-start path.
	@echo "  make upv — clean rebuild from scratch (DESTROYS local data volumes)."
	@$(MAKE) --no-print-directory downv
	$(DC_FULL) $(ENGINE_PROFILE) up --build -d --wait
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

# ── Cache and kill switch: NEVER hand-type these keys ──────────────────────────────────
# The namespace is composite - prompt version, corpus version, index version, collection
# and a digest of every model that could serve - so the literal `medbot:killswitch:...`
# does NOT exist and setting it silently does nothing. These targets ask the API for its
# own namespace, which is the only value guaranteed to be the one it reads.
NS = docker exec $(API_CTR) python -c "from medcore.config import get_settings;print(get_settings().cache_namespace)"
API_CTR := p5-medical-chatbot-api-1
REDIS_CTR := p5-medical-chatbot-redis-1

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
