.PHONY: install test lint clean

install:
	uv sync --extra dev

test:
	uv run pytest

lint:
	uv run ruff check src tests examples tools main.py

clean:
	rm -rf .pytest_cache .ruff_cache build dist src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
