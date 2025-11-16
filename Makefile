# Makefile for gryag development

.PHONY: help venv install install-dev test test-unit test-integration test-cov lint format type-check clean run docker-build docker-up docker-down ci docker-logs docker-test db-migrate db-version db-rollback

help:  ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

venv:  ## Create virtualenv and install base dependencies
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip
	. .venv/bin/activate && pip install -r requirements.txt

install: venv ## Install production dependencies
	. .venv/bin/activate && pip install -r requirements.txt

install-dev: venv ## Install development dependencies
	. .venv/bin/activate && pip install -r requirements.txt
	. .venv/bin/activate && pip install -r requirements-dev.txt

test:  ## Run all tests
	. .venv/bin/activate && pytest tests/ -v

test-unit:  ## Run unit tests only
	. .venv/bin/activate && pytest tests/unit/ -v

test-integration:  ## Run integration tests only
	. .venv/bin/activate && pytest tests/integration/ -v

test-cov:  ## Run tests with coverage report
	. .venv/bin/activate && pytest tests/ -v --cov=app --cov-report=html --cov-report=term
	@echo "Coverage report generated in htmlcov/index.html"

lint:  ## Run linters
	. .venv/bin/activate && black --check app/ tests/
	. .venv/bin/activate && ruff check app/ tests/
	. .venv/bin/activate && isort --check-only app/ tests/

format:  ## Auto-format code
	. .venv/bin/activate && black app/ tests/
	. .venv/bin/activate && isort app/ tests/
	. .venv/bin/activate && ruff check --fix app/ tests/

type-check:  ## Run type checker
	. .venv/bin/activate && mypy app/ --ignore-missing-imports

clean:  ## Clean up generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.xml
	rm -f gryag.db

db-migrate:  ## Run database migrations
	. .venv/bin/activate && python -m app.infrastructure.database.cli migrate

db-version:  ## Show current database version
	. .venv/bin/activate && python -m app.infrastructure.database.cli version

db-rollback:  ## Rollback database (specify VERSION=N)
	. .venv/bin/activate && python -m app.infrastructure.database.cli rollback $(VERSION)

run:  ## Run the bot locally
	. .venv/bin/activate && python -m app.main

docker-build:  ## Build Docker image
	docker compose build

docker-up:  ## Start Docker containers
	docker compose up -d

docker-down:  ## Stop Docker containers
	docker compose down

docker-logs:  ## Show Docker logs
	docker compose logs -f bot

docker-test:  ## Run tests in Docker
	docker compose run --rm bot pytest tests/ -v

ci: ## CI entrypoint: lint, type-check, tests with coverage gate
	. .venv/bin/activate && ruff check app/ tests/
	. .venv/bin/activate && black --check app/ tests/
	. .venv/bin/activate && isort --check-only app/ tests/
	. .venv/bin/activate && mypy app/ --ignore-missing-imports
	. .venv/bin/activate && pytest tests/ --cov=app --cov-fail-under=80 -q
