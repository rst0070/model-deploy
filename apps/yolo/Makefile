test:
	uv sync --frozen --extra cpu && uv run --no-sync pytest -q

lint:
	uv run --no-sync ruff check . && uv run --no-sync ruff format --check .

.PHONY: test lint
