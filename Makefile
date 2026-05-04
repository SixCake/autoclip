.PHONY: help install test test-unit test-integration lint format type-check clean run

help:
	@echo "AutoClip - Available targets:"
	@echo "  install         Install dependencies via Poetry"
	@echo "  test            Run all tests with coverage"
	@echo "  test-unit       Run unit tests only (fast)"
	@echo "  test-integration Run integration tests (requires services)"
	@echo "  lint            Run ruff linter"
	@echo "  format          Run ruff formatter"
	@echo "  type-check      Run mypy type checker"
	@echo "  clean           Remove caches and build artifacts"
	@echo "  run             Start FastAPI dev server"

install:
	poetry install

test:
	poetry run pytest --cov=src/autoclip --cov-report=term-missing

test-unit:
	poetry run pytest tests/unit -v

test-integration:
	poetry run pytest tests/integration -v -m integration

lint:
	poetry run ruff check src tests

format:
	poetry run ruff format src tests

type-check:
	poetry run mypy src

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name '*.egg-info' -exec rm -rf {} +

run:
	poetry run uvicorn autoclip.main:app --reload --host 0.0.0.0 --port 8000
