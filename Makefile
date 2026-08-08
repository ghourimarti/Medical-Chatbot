# P5 Medical RAG Chatbot — developer entrypoints.
# Every target is a documented, reproducible command (no tribal knowledge).

.DEFAULT_GOAL := help
.PHONY: help sync lint type test check eval-mock baseline validate

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
	uv run medeval validate packages/eval/datasets/golden_core_v1.jsonl

eval-mock:  ## Keyless end-to-end eval smoke (no API key needed)
	uv run medeval run --target mock --dataset packages/eval/datasets/golden_seed_v0.jsonl --skip-ragas

baseline:  ## Re-run the demo/ baseline (needs GROQ_API_KEY in .env; ~$1, ~25 min)
	uv run medeval run --target demo --dataset packages/eval/datasets/golden_core_v1.jsonl
