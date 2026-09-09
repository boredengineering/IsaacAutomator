# A durable shared stack, never a child module of a workstation deployment.
terraform {
  required_version = ">= 1.3.5"
  backend "s3" {}
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.41"
    }
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
}

locals {
  repository_arn = "arn:aws:ecr:${var.region}:${var.account_id}:repository/${var.repository}"
  repository_url = "${var.account_id}.dkr.ecr.${var.region}.amazonaws.com/${var.repository}"
}

resource "aws_ecr_repository" "images" {
  name                 = var.repository
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = var.kms_key_arn == "" ? "AES256" : "KMS"
    kms_key         = var.kms_key_arn == "" ? null : var.kms_key_arn
  }

  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = var.kms_key_arn == "" || startswith(var.kms_key_arn, "arn:aws:kms:${var.region}:${var.account_id}:key/")
      error_message = "The existing KMS key must belong to the repository account and region."
    }
  }
}
