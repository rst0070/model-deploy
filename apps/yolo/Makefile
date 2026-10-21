# Every target runs with --no-sync after this, so a plain `uv run` cannot swap in PyPI's torch.
sync:
	uv sync --frozen --extra cpu

test: sync
	uv run --no-sync pytest -q

lint: sync
	uv run --no-sync ruff check . && uv run --no-sync ruff format --check .

.PHONY: sync test lint
