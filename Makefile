SHELL := /bin/bash

# Every command in RUN.md is one of these targets, so the documented path and
# the tested path cannot drift apart.

# Pick an interpreter. Prefer an explicit PY=..., then the newest known-good
# version present, then whatever `python3` is. Reported on every install so a
# failure is traceable to the interpreter that caused it.
PY ?= $(shell for v in python3.13 python3.12 python3.11 python3.14 python3; do \
	command -v $$v >/dev/null 2>&1 && { $$v -c 'import sys;raise SystemExit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null && echo $$v && break; }; \
	done)

VENV := .venv
BIN := $(VENV)/bin

# The demo's port. Overridable so a busy 8000 needs no edit: PORT=8001 make serve
PORT ?= 8000

.DEFAULT_GOAL := help

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  interpreter: $(PY) ($(shell $(PY) --version 2>&1))"

$(BIN)/python:
	@test -n "$(PY)" || { echo "no Python 3.11+ found. Install one, or run: make install PY=/path/to/python3"; exit 1; }
	@echo "using $(PY) ($$($(PY) --version 2>&1))"
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip

install: $(BIN)/python ## Create the venv and install dependencies
	$(BIN)/pip install --quiet -r requirements-dev.txt
	$(BIN)/pip install --quiet -e .
	@$(BIN)/python -c "import sys;print('installed on Python %d.%d.%d'%sys.version_info[:3])"

check-wheels: ## Prove every dependency has a wheel on Python 3.11-3.14
	@for v in 311 312 313 314; do \
		printf "cp%s ... " $$v; \
		$(BIN)/pip download -q -d /tmp/psm-wheelcheck-$$v -r requirements.txt \
			--only-binary=:all: --python-version $$v --implementation cp --abi cp$$v \
			>/dev/null 2>&1 && echo "ok" || echo "FAILED - a dependency has no wheel for cp$$v"; \
		rm -rf /tmp/psm-wheelcheck-$$v; \
	done

migrate: ## Create and migrate the database
	@mkdir -p data
	$(BIN)/alembic upgrade head

seed: migrate ## Load the reproducible seed persona
	$(BIN)/python -m psm.cli seed --from evals/data/persona_seed.json

inspect: ## Print the current memory state
	$(BIN)/python -m psm.cli inspect

reset: ## Destroy all state and return to a freshly seeded system
	rm -rf data
	$(MAKE) seed

test: ## Run the test suite (includes fixture integrity)
	$(BIN)/pytest

lint:
	$(BIN)/ruff check src tests

eval: ## Run the full evaluation offline (no API key required)
	$(BIN)/python -m psm.cli eval --out evals/results --label baseline

eval-live: ## Run the evaluation against the live model (requires SARVAM_API_KEY)
	$(BIN)/python -m psm.cli eval --live --out evals/results --label live

eval-generated: ## Run the ~1,800-case derived tier; reports where it fails, not whether
	$(BIN)/python -m psm.cli eval-generated

generate: ## Rebuild the generated tier from committed inputs (deterministic)
	$(BIN)/python -m evals.gen.build

explore: ## Build the case explorer - every case, its decision, and the memory behind it
	$(BIN)/python -m psm.cli explore

stress: ## Run the stress suite (real prose, unseen personas, threshold sweeps)
	$(BIN)/python evals/stress/run.py

ablations: ## Reproduce every committed ablation
	@P="suppression,verbatim,already_canonical,script_fit,scope_fit,exact_variant,phonetic,common_word_guard,cooccurrence,conflict,recency"; \
	set -e; \
	$(BIN)/python -m psm.cli eval --out evals/results --label ablation-no-cooccurrence --policies "$${P/,cooccurrence/}"; \
	$(BIN)/python -m psm.cli eval --out evals/results --label ablation-no-conflict --policies "$${P/,conflict/}"; \
	$(BIN)/python -m psm.cli eval --out evals/results --label ablation-no-phonetic-scoring --policies "$${P/,phonetic,/,}"; \
	$(BIN)/python -m psm.cli eval --out evals/results --label ablation-no-guards --policies "$${P/,common_word_guard/}"; \
	$(BIN)/python -m psm.cli eval --out evals/results --label ablation-no-phonetics --phonetics phonetics.null; \
	$(BIN)/python -m psm.cli eval --out evals/results --label ablation-exact-only --policies "suppression,verbatim,already_canonical,exact_variant"

serve: ## Start the demo (PORT=8001 make serve if 8000 is taken)
	@echo "  open http://127.0.0.1:$(PORT)"
	$(BIN)/uvicorn psm.api.app:app --port $(PORT)

.PHONY: help install check-wheels migrate seed inspect reset test lint eval eval-generated generate eval-live explore stress ablations serve
