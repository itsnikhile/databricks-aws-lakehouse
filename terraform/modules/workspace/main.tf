# terraform/modules/workspace/main.tf
# Databricks workspace deployed in customer VPC

terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.40"
    }
  }
}

# ─── DATABRICKS WORKSPACE ──────────────────────────────────────────────────
resource "databricks_mws_networks" "main" {
  account_id         = var.databricks_account_id
  network_name       = "${var.prefix}-network"
  vpc_id             = var.vpc_id
  subnet_ids         = var.private_subnet_ids
  security_group_ids = [var.cluster_security_group_id]
}

resource "databricks_mws_storage_configurations" "main" {
  account_id                 = var.databricks_account_id
  storage_configuration_name = "${var.prefix}-storage"
  bucket_name                = var.workspace_root_bucket
}

resource "databricks_mws_credentials" "main" {
  account_id       = var.databricks_account_id
  credentials_name = "${var.prefix}-credentials"
  role_arn         = var.cross_account_role_arn
}

resource "databricks_mws_workspaces" "main" {
  account_id     = var.databricks_account_id
  workspace_name = "${var.prefix}-workspace"
  aws_region     = var.region

  credentials_id           = databricks_mws_credentials.main.credentials_id
  storage_configuration_id = databricks_mws_storage_configurations.main.storage_configuration_id
  network_id               = databricks_mws_networks.main.network_id

  token {
    comment = "Terraform-managed initial token"
  }
}

# ─── CLUSTER POLICY: Standard ETL ──────────────────────────────────────────
resource "databricks_cluster_policy" "etl" {
  name = "${var.prefix}-etl-policy"

  definition = jsonencode({
    "spark_version" : {
      "type" : "allowlist",
      "values" : ["14.3.x-scala2.12", "15.4.x-scala2.12"],
      "defaultValue" : "15.4.x-scala2.12"
    },
    "node_type_id" : {
      "type" : "allowlist",
      "values" : ["r5.xlarge", "r5.2xlarge", "r5.4xlarge", "m5.xlarge", "m5.2xlarge"]
    },
    "autotermination_minutes" : {
      "type" : "fixed",
      "value" : 30
    },
    "aws_attributes.availability" : {
      "type" : "fixed",
      "value" : "SPOT_WITH_FALLBACK"
    },
    "aws_attributes.spot_bid_price_percent" : {
      "type" : "fixed",
      "value" : 100
    }
  })
}

# ─── CLUSTER POLICY: Interactive / Analyst ─────────────────────────────────
resource "databricks_cluster_policy" "interactive" {
  name = "${var.prefix}-interactive-policy"

  definition = jsonencode({
    "spark_version" : {
      "type" : "allowlist",
      "values" : ["14.3.x-scala2.12", "15.4.x-scala2.12"],
      "defaultValue" : "15.4.x-scala2.12"
    },
    "node_type_id" : {
      "type" : "allowlist",
      "values" : ["m5.xlarge", "m5.2xlarge", "r5.xlarge"]
    },
    "autotermination_minutes" : {
      "type" : "range",
      "minValue" : 10,
      "maxValue" : 120,
      "defaultValue" : 30
    },
    "num_workers" : {
      "type" : "range",
      "minValue" : 1,
      "maxValue" : 10
    }
  })
}

# ─── INSTANCE POOL ─────────────────────────────────────────────────────────
resource "databricks_instance_pool" "main" {
  instance_pool_name = "${var.prefix}-pool"
  min_idle_instances = 1
  max_capacity       = 20

  aws_attributes {
    availability           = "SPOT_WITH_FALLBACK"
    zone_id                = "auto"
    spot_bid_price_percent = 100
  }

  node_type_id                         = "m5.xlarge"
  idle_instance_autotermination_minutes = 15
}

# ─── SECRET SCOPE (backed by AWS Secrets Manager) ──────────────────────────
resource "databricks_secret_scope" "aws" {
  name = "aws-secrets"

  keyvault_metadata {
    resource_id = var.secrets_manager_secret_arn
    dns_name    = var.secrets_manager_endpoint
  }
}

# ─── DATABRICKS GROUPS & PERMISSIONS ───────────────────────────────────────
resource "databricks_group" "data_engineers" {
  display_name = "data-engineers"
}

resource "databricks_group" "data_analysts" {
  display_name = "data-analysts"
}

resource "databricks_group" "ml_engineers" {
  display_name = "ml-engineers"
}
