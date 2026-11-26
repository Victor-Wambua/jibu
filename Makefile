.PHONY: install test lint typecheck check kb-check eval run
install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check .

typecheck:
	uv run mypy

check: lint typecheck test

kb-check:
	uv run jibu kb check kb

eval:
	uv run jibu eval

run:
	uv run jibu serve --port 4110
