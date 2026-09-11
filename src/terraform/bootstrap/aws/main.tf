# Independent admin-owned stack. Never imported into the workload graph.
terraform {
  required_version = ">= 1.7.0, < 2.0.0"
  backend "local" {}
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 5.100.0"
    }
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.owner_account_id]
}

resource "aws_s3_bucket" "state" {
  bucket        = var.bucket_name
  force_destroy = false
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_id == "" ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_id == "" ? null : var.kms_key_id
    }
  }
  lifecycle {
    prevent_destroy = true
  }
}

locals {
  bucket_arn = "arn:aws:s3:::${var.bucket_name}"
  # Narrow listing plus state read/write; DeleteObject ONLY for native lockfiles.
  controller_policy = {
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = var.controller_principal }
        Action    = ["s3:ListBucket"]
        Resource  = local.bucket_arn
        Condition = { StringLike = { "s3:prefix" = ["${var.key_prefix}/*"] } }
      },
      {
        Effect    = "Allow"
        Principal = { AWS = var.controller_principal }
        Action    = ["s3:GetObject", "s3:PutObject"]
        Resource  = "${local.bucket_arn}/${var.key_prefix}/*.tfstate"
      },
      {
        Effect    = "Allow"
        Principal = { AWS = var.controller_principal }
        Action    = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource  = "${local.bucket_arn}/${var.key_prefix}/*.tflock"
      }
    ]
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(local.controller_policy.Statement, [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [local.bucket_arn, "${local.bucket_arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }])
  })
  depends_on = [aws_s3_bucket_public_access_block.state]
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "versions" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "BoundNoncurrentStateHistory"
    status = "Enabled"
    filter {
      prefix = "${var.key_prefix}/"
    }
    noncurrent_version_expiration {
      noncurrent_days           = 90
      newer_noncurrent_versions = 10
    }
  }
  depends_on = [aws_s3_bucket_versioning.state]
  lifecycle {
    prevent_destroy = true
  }
}
