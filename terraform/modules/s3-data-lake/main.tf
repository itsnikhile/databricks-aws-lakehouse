# terraform/modules/s3-data-lake/main.tf
# S3 buckets for Bronze, Silver, Gold zones with encryption, lifecycle, and replication

locals {
  zones = ["bronze", "silver", "gold"]
}

# ─── KMS KEY for S3 encryption ─────────────────────────────────────────────
resource "aws_kms_key" "datalake" {
  description             = "${var.prefix} Data Lake CMK"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Enable IAM User Permissions"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "Allow Databricks to use the key"
        Effect = "Allow"
        Principal = { AWS = var.databricks_instance_profile_arn }
        Action   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
        Resource = "*"
      }
    ]
  })

  tags = merge(var.tags, { Name = "${var.prefix}-datalake-kms" })
}

resource "aws_kms_alias" "datalake" {
  name          = "alias/${var.prefix}-datalake"
  target_key_id = aws_kms_key.datalake.key_id
}

data "aws_caller_identity" "current" {}

# ─── S3 BUCKETS (one per zone) ─────────────────────────────────────────────
resource "aws_s3_bucket" "zone" {
  for_each = toset(local.zones)

  bucket        = "${var.prefix}-datalake-${each.key}-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.environment != "prod"

  tags = merge(var.tags, {
    Name        = "${var.prefix}-datalake-${each.key}"
    DataZone    = each.key
    Environment = var.environment
  })
}

# Block all public access
resource "aws_s3_bucket_public_access_block" "zone" {
  for_each = toset(local.zones)

  bucket                  = aws_s3_bucket.zone[each.key].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Server-side encryption with KMS CMK
resource "aws_s3_bucket_server_side_encryption_configuration" "zone" {
  for_each = toset(local.zones)

  bucket = aws_s3_bucket.zone[each.key].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.datalake.arn
    }
    bucket_key_enabled = true
  }
}

# Versioning (required for Delta Lake time travel)
resource "aws_s3_bucket_versioning" "zone" {
  for_each = toset(local.zones)

  bucket = aws_s3_bucket.zone[each.key].id
  versioning_configuration {
    status = "Enabled"
  }
}

# ─── LIFECYCLE RULES ───────────────────────────────────────────────────────
resource "aws_s3_bucket_lifecycle_configuration" "bronze" {
  bucket = aws_s3_bucket.zone["bronze"].id

  rule {
    id     = "bronze-intelligent-tiering"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "INTELLIGENT_TIERING"
    }

    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "silver" {
  bucket = aws_s3_bucket.zone["silver"].id

  rule {
    id     = "silver-intelligent-tiering"
    status = "Enabled"

    transition {
      days          = 60
      storage_class = "INTELLIGENT_TIERING"
    }

    noncurrent_version_expiration {
      noncurrent_days = 60
    }
  }
}

# ─── BUCKET POLICIES ───────────────────────────────────────────────────────
resource "aws_s3_bucket_policy" "zone" {
  for_each = toset(local.zones)

  bucket = aws_s3_bucket.zone[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DenyInsecureTransport"
        Effect = "Deny"
        Principal = "*"
        Action   = "s3:*"
        Resource = [
          "${aws_s3_bucket.zone[each.key].arn}",
          "${aws_s3_bucket.zone[each.key].arn}/*"
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      },
      {
        Sid    = "AllowDatabricksInstanceProfile"
        Effect = "Allow"
        Principal = { AWS = var.databricks_instance_profile_arn }
        Action = [
          "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
          "s3:ListBucket", "s3:GetBucketLocation"
        ]
        Resource = [
          "${aws_s3_bucket.zone[each.key].arn}",
          "${aws_s3_bucket.zone[each.key].arn}/*"
        ]
      }
    ]
  })
}

# ─── CROSS-REGION REPLICATION (prod only) ──────────────────────────────────
resource "aws_s3_bucket_replication_configuration" "gold_dr" {
  count = var.environment == "prod" ? 1 : 0

  bucket = aws_s3_bucket.zone["gold"].id
  role   = var.replication_role_arn

  rule {
    id     = "gold-cross-region-dr"
    status = "Enabled"

    destination {
      bucket        = var.dr_bucket_arn
      storage_class = "STANDARD_IA"

      encryption_configuration {
        replica_kms_key_id = var.dr_kms_key_arn
      }
    }

    source_selection_criteria {
      sse_kms_encrypted_objects {
        status = "Enabled"
      }
    }
  }
}
