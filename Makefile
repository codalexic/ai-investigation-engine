.PHONY: install lint format test run data index index-chunking eval-retrieval eval-chunking eval-embeddings eval-e2e report

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

test:
	uv run python -m pytest -q

run:
	uv run python -m uvicorn app.api.main:app --reload --port 7860

data:
	uv run --group data python scripts/build_hotpotqa.py
	uv run --group data python scripts/build_postmortems.py
	uv run --group data python scripts/generate_synthetic.py
	uv run python scripts/build_eval_set.py

index:
	uv run python scripts/index_corpus.py --sources hotpotqa,postmortems,synthetic

index-chunking:
	uv run python scripts/index_corpus.py --sources synthetic,postmortems --collection chunk_structure --chunk-strategy structure --recreate
	uv run python scripts/index_corpus.py --sources synthetic,postmortems --collection chunk_fixed --chunk-strategy fixed --recreate

eval-retrieval:
	uv run python scripts/eval_retrieval.py --collection documents --questions eval/data/hotpotqa_questions.jsonl,eval/questions.jsonl --configs dense,sparse,hybrid,hybrid_rerank,hybrid_rerank_mmr

eval-chunking:
	uv run python scripts/eval_chunking.py --collections chunk_structure,chunk_fixed

eval-embeddings:
	uv run python scripts/eval_embeddings.py --models BAAI/bge-small-en-v1.5,sentence-transformers/all-MiniLM-L6-v2 --subset-questions 300

eval-e2e:
	uv run python scripts/eval_e2e.py --config full
	uv run python scripts/eval_e2e.py --config no_agent

report:
	uv run python scripts/make_report.py
