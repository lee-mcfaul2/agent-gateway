.PHONY: install build test test-unit test-integration test-conformance lint format run-local clean

install:
	uv sync --dev

build:
	uv build

test: test-unit

test-unit:
	uv run pytest tests/unit -v

test-integration:
	uv run pytest tests/integration -v --integration

test-conformance:
	uv run pytest tests/conformance -v --integration

lint:
	uv run ruff check src tests
	uv run mypy --strict src
	uv run bandit -r src

format:
	uv run ruff format src tests

run-local:
	docker compose -f deploy/dev/compose.yaml up --build

clean:
	rm -rf dist/ build/ .pytest_cache/ .mypy_cache/ .ruff_cache/ .coverage coverage.xml htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
