.PHONY: install lint format test run

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

test:
	UV_CACHE_DIR=.uv-cache uv run python -m pytest -q -p no:cacheprovider --basetemp=.pytest_tmp

run:
	uv run uvicorn app.api.main:app --reload --port 7860

.PHONY: data index index-fixed
data:
	uv run --group data python scripts/build_hotpotqa.py
	uv run --group data python scripts/build_postmortems.py
	uv run --group data python scripts/generate_synthetic.py

index:
	uv run python scripts/index_corpus.py --sources hotpotqa,postmortems,synthetic

index-fixed:
	uv run python scripts/index_corpus.py --sources synthetic,postmortems --collection documents_fixed --chunk-strategy fixed
