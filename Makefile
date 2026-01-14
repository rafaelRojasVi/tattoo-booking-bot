.PHONY: help build up down logs test version-bump version-patch version-minor version-major

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

build: ## Build Docker images
	docker compose build

up: ## Start services
	docker compose up -d

down: ## Stop services
	docker compose down

logs: ## Show logs
	docker compose logs -f api

test: ## Run tests locally
	pytest tests/ -v

test-docker: ## Run tests in Docker
	docker compose -f docker-compose.test.yml run --rm test

test-watch: ## Run tests in watch mode
	pytest-watch tests/ -v

version-bump: ## Bump version (usage: make version-bump TYPE=patch)
	@if [ -z "$(TYPE)" ]; then \
		echo "Usage: make version-bump TYPE=[major|minor|patch]"; \
		exit 1; \
	fi
	@bash scripts/bump-version.sh $(TYPE)

version-patch: ## Bump patch version (0.1.0 -> 0.1.1)
	@bash scripts/bump-version.sh patch

version-minor: ## Bump minor version (0.1.0 -> 0.2.0)
	@bash scripts/bump-version.sh minor

version-major: ## Bump major version (0.1.0 -> 1.0.0)
	@bash scripts/bump-version.sh major

migrate: ## Run database migrations
	docker compose exec api alembic upgrade head

migrate-create: ## Create new migration (usage: make migrate-create MSG="migration message")
	@if [ -z "$(MSG)" ]; then \
		echo "Usage: make migrate-create MSG=\"your message\""; \
		exit 1; \
	fi
	docker compose exec api alembic revision --autogenerate -m "$(MSG)"
