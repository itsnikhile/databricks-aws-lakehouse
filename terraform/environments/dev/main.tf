# terraform/environments/dev/main.tf

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.40"
    }
  }

  backend "s3" {
    bucket         = "your-terraform-state-bucket"
    key            = "databricks-lakehouse/dev/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    kms_key_id     = "alias/your-terraform-state-kms"
    dynamodb_table = "terraform-state-lock"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Environment = "dev"
      Project     = "databricks-lakehouse"
      ManagedBy   = "terraform"
    }
  }
}

provider "databricks" {
  host       = module.workspace.workspace_url
  account_id = var.databricks_account_id
}

locals {
  prefix      = "dev-lakehouse"
  environment = "dev"
}

# ─── NETWORKING ────────────────────────────────────────────────────────────
module "networking" {
  source = "../../modules/networking"

  prefix             = local.prefix
  region             = var.aws_region
  vpc_cidr           = "10.10.0.0/16"
  availability_zones = ["us-east-1a", "us-east-1b"]
  tags               = { Environment = local.environment }
}

# ─── IAM ROLES ─────────────────────────────────────────────────────────────
module "iam" {
  source = "../../modules/iam-roles"

  prefix                  = local.prefix
  environment             = local.environment
  databricks_account_id   = var.databricks_account_id
}

# ─── S3 DATA LAKE ──────────────────────────────────────────────────────────
module "s3" {
  source = "../../modules/s3-data-lake"

  prefix                          = local.prefix
  environment                     = local.environment
  databricks_instance_profile_arn = module.iam.instance_profile_arn
  tags                            = { Environment = local.environment }
}

# ─── DATABRICKS WORKSPACE ──────────────────────────────────────────────────
module "workspace" {
  source = "../../modules/workspace"

  prefix                    = local.prefix
  region                    = var.aws_region
  databricks_account_id     = var.databricks_account_id
  vpc_id                    = module.networking.vpc_id
  private_subnet_ids        = module.networking.private_subnet_ids
  cluster_security_group_id = module.networking.databricks_cluster_sg_id
  workspace_root_bucket     = module.s3.workspace_bucket_name
  cross_account_role_arn    = module.iam.cross_account_role_arn
  secrets_manager_secret_arn = var.secrets_manager_arn
  secrets_manager_endpoint   = "https://secretsmanager.${var.aws_region}.amazonaws.com"
}

# ─── UNITY CATALOG ─────────────────────────────────────────────────────────
module "unity_catalog" {
  source = "../../modules/unity-catalog"

  prefix                   = local.prefix
  environment              = local.environment
  region                   = var.aws_region
  workspace_id             = module.workspace.workspace_id
  unity_catalog_bucket     = module.s3.unity_catalog_bucket_name
  bronze_bucket            = module.s3.bronze_bucket_name
  silver_bucket            = module.s3.silver_bucket_name
  gold_bucket              = module.s3.gold_bucket_name
  unity_catalog_role_arn   = module.iam.unity_catalog_role_arn
}

# ─── OUTPUTS ───────────────────────────────────────────────────────────────
output "workspace_url" {
  value = module.workspace.workspace_url
}

output "bronze_bucket" {
  value = module.s3.bronze_bucket_name
}

output "silver_bucket" {
  value = module.s3.silver_bucket_name
}

output "gold_bucket" {
  value = module.s3.gold_bucket_name
}
