# Makefile for gryag development

.PHONY: help install install-dev test test-unit test-integration test-cov lint format type-check clean run docker-build docker-up docker-down

help:  ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Install production dependencies
	pip install -r requirements.txt

install-dev:  ## Install development dependencies
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

test:  ## Run all tests
	pytest tests/ -v

test-unit:  ## Run unit tests only
	pytest tests/unit/ -v

test-integration:  ## Run integration tests only
	pytest tests/integration/ -v

test-cov:  ## Run tests with coverage report
	pytest tests/ -v --cov=app --cov-report=html --cov-report=term
	@echo "Coverage report generated in htmlcov/index.html"

lint:  ## Run linters
	black --check app/ tests/
	ruff check app/ tests/
	isort --check-only app/ tests/

format:  ## Auto-format code
	black app/ tests/
	isort app/ tests/
	ruff check --fix app/ tests/

type-check:  ## Run type checker
	mypy app/ --ignore-missing-imports

clean:  ## Clean up generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ .coverage coverage.xml
	rm -f gryag.db

db-migrate:  ## Run database migrations
	python -m app.infrastructure.database.cli migrate

db-version:  ## Show current database version
	python -m app.infrastructure.database.cli version

db-rollback:  ## Rollback database (specify VERSION=N)
	python -m app.infrastructure.database.cli rollback $(VERSION)

run:  ## Run the bot locally
	python -m app.main

docker-build:  ## Build Docker image
	docker-compose build

docker-up:  ## Start Docker containers
	docker-compose up -d

docker-down:  ## Stop Docker containers
	docker-compose down

docker-logs:  ## Show Docker logs
	docker-compose logs -f bot

docker-test:  ## Run tests in Docker
	docker-compose run --rm bot pytest tests/ -v
