# terraform/modules/unity-catalog/main.tf
# Unity Catalog metastore, catalogs, schemas, and access grants

resource "databricks_metastore" "main" {
  name          = "${var.prefix}-metastore"
  storage_root  = "s3://${var.unity_catalog_bucket}/metastore"
  region        = var.region
  force_destroy = var.environment != "prod"
}

resource "databricks_metastore_assignment" "main" {
  metastore_id = databricks_metastore.main.id
  workspace_id = var.workspace_id
}

# ─── EXTERNAL LOCATIONS (S3 zone access) ───────────────────────────────────
resource "databricks_storage_credential" "s3" {
  name = "${var.prefix}-s3-credential"

  aws_iam_role {
    role_arn = var.unity_catalog_role_arn
  }
}

resource "databricks_external_location" "bronze" {
  name            = "bronze-zone"
  url             = "s3://${var.bronze_bucket}/"
  credential_name = databricks_storage_credential.s3.name
}

resource "databricks_external_location" "silver" {
  name            = "silver-zone"
  url             = "s3://${var.silver_bucket}/"
  credential_name = databricks_storage_credential.s3.name
}

resource "databricks_external_location" "gold" {
  name            = "gold-zone"
  url             = "s3://${var.gold_bucket}/"
  credential_name = databricks_storage_credential.s3.name
}

# ─── CATALOGS ──────────────────────────────────────────────────────────────
resource "databricks_catalog" "bronze" {
  name    = "bronze_catalog"
  comment = "Raw ingested data — immutable, append-only"
  storage_root = "s3://${var.bronze_bucket}/unity-catalog"
}

resource "databricks_catalog" "silver" {
  name    = "silver_catalog"
  comment = "Cleaned and conformed data with schema enforcement"
  storage_root = "s3://${var.silver_bucket}/unity-catalog"
}

resource "databricks_catalog" "gold" {
  name    = "gold_catalog"
  comment = "Business-level aggregations and ML-ready datasets"
  storage_root = "s3://${var.gold_bucket}/unity-catalog"
}

# ─── SCHEMAS ───────────────────────────────────────────────────────────────
resource "databricks_schema" "bronze_events" {
  catalog_name = databricks_catalog.bronze.name
  name         = "events"
  comment      = "Raw event streams from Kinesis and Kafka"
}

resource "databricks_schema" "bronze_operational" {
  catalog_name = databricks_catalog.bronze.name
  name         = "operational"
  comment      = "Raw CDC data from RDS/Aurora"
}

resource "databricks_schema" "silver_events" {
  catalog_name = databricks_catalog.silver.name
  name         = "events"
  comment      = "Cleaned and deduped events"
}

resource "databricks_schema" "silver_operational" {
  catalog_name = databricks_catalog.silver.name
  name         = "operational"
  comment      = "Cleaned operational data with SCD Type 2"
}

resource "databricks_schema" "gold_finance" {
  catalog_name = databricks_catalog.gold.name
  name         = "finance"
  comment      = "Financial KPIs and aggregations"
}

resource "databricks_schema" "gold_features" {
  catalog_name = databricks_catalog.gold.name
  name         = "features"
  comment      = "ML feature tables managed by Databricks Feature Store"
}

# ─── GRANTS ────────────────────────────────────────────────────────────────
resource "databricks_grants" "bronze_catalog" {
  catalog = databricks_catalog.bronze.name

  grant {
    principal  = "data-engineers"
    privileges = ["USE_CATALOG", "USE_SCHEMA", "SELECT", "MODIFY", "CREATE_TABLE"]
  }
}

resource "databricks_grants" "silver_catalog" {
  catalog = databricks_catalog.silver.name

  grant {
    principal  = "data-engineers"
    privileges = ["USE_CATALOG", "USE_SCHEMA", "SELECT", "MODIFY", "CREATE_TABLE"]
  }

  grant {
    principal  = "data-analysts"
    privileges = ["USE_CATALOG", "USE_SCHEMA", "SELECT"]
  }
}

resource "databricks_grants" "gold_catalog" {
  catalog = databricks_catalog.gold.name

  grant {
    principal  = "data-engineers"
    privileges = ["USE_CATALOG", "USE_SCHEMA", "SELECT", "MODIFY", "CREATE_TABLE"]
  }

  grant {
    principal  = "data-analysts"
    privileges = ["USE_CATALOG", "USE_SCHEMA", "SELECT"]
  }

  grant {
    principal  = "ml-engineers"
    privileges = ["USE_CATALOG", "USE_SCHEMA", "SELECT"]
  }
}
