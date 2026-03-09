# Makefile — Developer convenience commands

.PHONY: help install lint test terraform-dev deploy-dev clean

help:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  Databricks + AWS Data Lakehouse — Developer Commands"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  make install       — Install Python dev dependencies"
	@echo "  make lint          — Run ruff + black format check"
	@echo "  make test          — Run unit tests with coverage"
	@echo "  make tf-init       — Initialize Terraform (dev env)"
	@echo "  make tf-plan       — Run Terraform plan (dev env)"
	@echo "  make tf-apply      — Apply Terraform (dev env)"
	@echo "  make bundle-deploy — Deploy Databricks Asset Bundle (dev)"
	@echo "  make bundle-run    — Run the Bronze ingestion job (dev)"
	@echo "  make clean         — Remove build artifacts"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

install:
	pip install -r requirements-dev.txt
	npm install -g @databricks/cli || true

lint:
	ruff check src/ databricks/ mlflow/ tests/
	black --check src/ databricks/ mlflow/ tests/
	terraform fmt -check -recursive terraform/

format:
	ruff check --fix src/ databricks/ mlflow/ tests/
	black src/ databricks/ mlflow/ tests/
	terraform fmt -recursive terraform/

test:
	pytest tests/unit/ \
		--cov=src \
		--cov-report=term-missing \
		--cov-fail-under=70 \
		-v

tf-init:
	cd terraform/environments/dev && terraform init

tf-plan:
	cd terraform/environments/dev && terraform plan

tf-apply:
	cd terraform/environments/dev && terraform apply

tf-destroy:
	@echo "⚠️  This will DESTROY the dev environment. Are you sure? (Ctrl+C to cancel)"
	@sleep 5
	cd terraform/environments/dev && terraform destroy

bundle-validate:
	databricks bundle validate --target dev

bundle-deploy:
	databricks bundle deploy --target dev

bundle-run:
	databricks bundle run ingest_bronze_job --target dev

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf dist/ build/ .eggs/ *.egg-info/
	rm -rf .pytest_cache/ htmlcov/ coverage.xml .coverage
