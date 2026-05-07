# SentinelAI
# Autonomous AI Reliability Engineer for distributed cloud-native systems

# Build, test, and development commands
.PHONY: help install dev test lint format clean build docker-build docker-up docker-down

# Default target
help:
	@echo "SentinelAI - Makefile Commands"
	@echo "================================"
	@echo "install       Install dependencies"
	@echo "dev           Run development server"
	@echo "test          Run tests"
	@echo "lint          Run linters"
	@echo "format        Format code"
	@echo "clean         Clean build artifacts"
	@echo "build         Build Docker images"
	@echo "docker-up     Start Docker services"
	@echo "docker-down   Stop Docker services"

# Install dependencies
install:
	pip install -e ".[dev]"
	pre-commit install

# Run development server
dev:
	uvicorn sentinelai.api_gateway.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
test:
	pytest tests/ -v --cov=sentinelai --cov-report=html

# Run linters
lint:
	ruff check sentinelai/
	mypy sentinelai/

# Format code
format:
	ruff format sentinelai/
	isort sentinelai/

# Clean build artifacts
clean:
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +

# Build Docker images
docker-build:
	docker-compose -f infrastructure/docker-compose.yml build

# Start Docker services
docker-up:
	docker-compose -f infrastructure/docker-compose.yml up -d

# Stop Docker services
docker-down:
	docker-compose -f infrastructure/docker-compose.yml down

# Run specific service
dev-gateway:
	uvicorn sentinelai.api_gateway.main:app --reload --port 8000

dev-auth:
	uvicorn sentinelai.auth_service.main:app --reload --port 8001

dev-incident:
	uvicorn sentinelai.incident_intelligence.main:app --reload --port 8002

dev-logs:
	uvicorn sentinelai.log_processing.main:app --reload --port 8003

dev-metrics:
	uvicorn sentinelai.metrics_processing.main:app --reload --port 8004

dev-traces:
	uvicorn sentinelai.trace_correlation.main:app --reload --port 8005

dev-ai:
	uvicorn sentinelai.ai_orchestration.main:app --reload --port 8006

# Database migrations
migrate:
	alembic upgrade head

migration-create:
	alembic revision --autogenerate -m "$(NAME)"

# Run Celery worker
celery-worker:
	celery -A sentinelai.workers worker --loglevel=info

# Run Celery beat
celery-beat:
	celery -A sentinelai.workers beat --loglevel=info

# Generate proto files
proto:
	cd proto && protoc --python_out=../backend -I. *.proto

# Type check
typecheck:
	mypy sentinelai/

# Security audit
security:
	bandit -r sentinelai/
	safety check

# Check dependencies
deps-check:
	pip-audit

# Release
release:
	git tag -a v$(VERSION) -m "Release v$(VERSION)"
	git push origin v$(VERSION)
	git push origin main
