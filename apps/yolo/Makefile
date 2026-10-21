test:
	uv sync --frozen && uv run pytest -q

lint:
	uv run ruff check . && uv run ruff format --check .

.PHONY: test lint
