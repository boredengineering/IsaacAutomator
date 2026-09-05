# ==============================================================================
# Hardened GCS Remote State Bucket Module
# Uniform bucket-level access, object versioning, soft-delete, and native locking
# ==============================================================================

terraform {
  required_version = ">= 1.3.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 4.57.0"
    }
  }
}

variable "project" {
  type        = string
  description = "GCP Project ID"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "GCP Region for the state bucket"
}

variable "state_bucket_name" {
  type        = string
  default     = ""
  description = "Explicit state bucket name (defaults to isaacautomator-state-<project>-<region>)"
}

variable "kms_key_name" {
  type        = string
  default     = ""
  description = "Optional KMS CMEK key to encrypt state objects"
}

locals {
  name = var.state_bucket_name != "" ? var.state_bucket_name : "isaacautomator-state-${var.project}-${var.region}"
}

# Production-Hardened State Bucket
resource "google_storage_bucket" "state_bucket" {
  name                        = local.name
  project                     = var.project
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  soft_delete_policy {
    retention_duration_seconds = 604800 # 7-day retention against ransomware/accidental purge
  }

  dynamic "encryption" {
    for_each = var.kms_key_name != "" ? [1] : []
    content {
      default_kms_key_name = var.kms_key_name
    }
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      num_newer_versions         = 10
      days_since_noncurrent_time = 90
    }
  }
}

output "state_bucket_name" {
  value = google_storage_bucket.state_bucket.name
}

output "state_bucket_url" {
  value = google_storage_bucket.state_bucket.url
}
