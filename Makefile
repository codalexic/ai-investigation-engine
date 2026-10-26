.PHONY: install lint format test run

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

test:
	uv run pytest -q

run:
	uv run uvicorn app.api.main:app --reload --port 7860
