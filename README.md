# Databricks + AWS Enterprise Data Lakehouse

> Production-grade Data Lakehouse architecture using Databricks on AWS with the Medallion Design Pattern (Bronze → Silver → Gold).

![Architecture](docs/architecture_overview.png)

## 📋 Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Deployment](#deployment)
- [Pipelines](#pipelines)
- [Security](#security)
- [Contributing](#contributing)

---

## Overview

This repository contains the **complete infrastructure-as-code, pipeline definitions, and data transformation logic** for an enterprise-grade Data Lakehouse on AWS using Databricks.

| Component | Technology |
|---|---|
| Cloud Provider | Amazon Web Services (AWS) |
| Analytics Platform | Databricks |
| Storage Layer | Amazon S3 + Delta Lake |
| Governance | Unity Catalog |
| ML Platform | MLflow + Databricks Feature Store |
| IaC | Terraform |
| CI/CD | GitHub Actions + Databricks Asset Bundles |
| Orchestration | Databricks Workflows |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  DATA SOURCES & INGESTION                   │
│  RDS/Aurora · Kinesis · MSK (Kafka) · S3 · SaaS · IoT Core  │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              S3 DATA LAKE — DELTA FORMAT                    │
│   🥉 Bronze (Raw)  →  🥈 Silver (Clean)  →  🥇 Gold (BI)  │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│            DATABRICKS COMPUTE PLATFORM (AWS EC2)            │
│  Job Clusters · SQL Warehouses · Streaming · Photon Engine  │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│         DATA PROCESSING, ENGINEERING & ML                   │
│  Delta Live Tables · MLflow · Feature Store · AutoML        │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│         GOVERNANCE — UNITY CATALOG                          │
│  RBAC · Lineage · Data Quality · Audit · Compliance         │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              DATA SERVING & CONSUMPTION                     │
│  Databricks SQL · Redshift · Athena · BI Tools · APIs       │
└─────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
databricks-aws-lakehouse/
├── terraform/                    # Infrastructure as Code
│   ├── modules/
│   │   ├── networking/           # VPC, subnets, endpoints
│   │   ├── workspace/            # Databricks workspace
│   │   ├── unity-catalog/        # Metastore, catalogs, grants
│   │   ├── s3-data-lake/         # S3 buckets, lifecycle, encryption
│   │   └── iam-roles/            # Instance profiles, cross-account roles
│   └── environments/
│       ├── dev/
│       ├── staging/
│       └── prod/
├── databricks/
│   ├── pipelines/                # Delta Live Tables pipeline definitions
│   ├── notebooks/                # Exploration and analysis notebooks
│   ├── workflows/                # Databricks Workflow DAG definitions
│   └── feature-store/            # Feature table definitions
├── src/
│   ├── ingestion/                # Auto Loader & streaming ingest
│   ├── transformations/          # Bronze→Silver→Gold logic
│   ├── gold/                     # Business aggregation layer
│   └── utils/                    # Shared helpers & schema registry
├── mlflow/                       # MLflow training & deployment scripts
├── tests/
│   ├── unit/
│   └── integration/
├── .github/workflows/            # CI/CD pipelines
└── docs/                         # Architecture diagrams & runbooks
```

---

## Prerequisites

- AWS Account with admin permissions
- Databricks Account (Premium or Enterprise tier)
- Terraform >= 1.6
- Databricks CLI >= 0.210 (with Asset Bundles support)
- Python >= 3.11
- Docker (for local testing)

---

## Quick Start

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_ORG/databricks-aws-lakehouse.git
cd databricks-aws-lakehouse
```

### 2. Set up environment variables
```bash
cp .env.example .env
# Edit .env with your AWS and Databricks credentials
```

### 3. Deploy infrastructure (dev)
```bash
cd terraform/environments/dev
terraform init
terraform plan
terraform apply
```

### 4. Deploy Databricks assets
```bash
databricks bundle deploy --target dev
```

### 5. Run the Bronze ingestion pipeline
```bash
databricks bundle run ingest_bronze_job --target dev
```

---

## Deployment

See [docs/deployment.md](docs/deployment.md) for the full deployment guide including:
- First-time setup checklist
- Unity Catalog metastore configuration
- Secret scope setup
- Environment promotion process

---

## Pipelines

| Pipeline | Description | Schedule |
|---|---|---|
| `ingest_bronze` | Raw data ingestion via Auto Loader | Continuous |
| `transform_silver` | Clean & deduplicate → Silver zone | Every 30 min |
| `aggregate_gold` | Business KPIs → Gold zone | Hourly |
| `feature_engineering` | ML feature computation | Daily |
| `ml_training` | Model training & registration | Daily |

---

## Security

- All data encrypted at rest with AWS KMS (CMK)
- Databricks deployed in customer VPC with private subnets
- Unity Catalog row/column-level security
- Secrets managed via AWS Secrets Manager + Databricks Secret Scopes
- Full audit trail via CloudTrail + Databricks system tables

---

## Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make changes, add tests
4. Run `make test` to validate
5. Open a Pull Request — CI will validate automatically

---

## License

MIT License — see [LICENSE](LICENSE)
