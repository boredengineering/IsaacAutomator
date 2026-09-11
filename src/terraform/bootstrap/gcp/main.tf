# ==============================================================================
# Hardened GCS Remote State Bucket Module
# Uniform bucket-level access, object versioning, soft-delete, and native locking
# ==============================================================================

terraform {
  required_version = ">= 1.7.0, < 2.0.0"
  backend "local" {}
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 6.45.0"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}

# Production-Hardened State Bucket
resource "google_storage_bucket" "state_bucket" {
  name                        = var.state_bucket_name
  project                     = var.project
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  lifecycle {
    prevent_destroy = true
  }

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

resource "google_storage_bucket_iam_member" "controller" {
  bucket = google_storage_bucket.state_bucket.name
  role   = "roles/storage.objectAdmin"
  member = var.controller_principal
  lifecycle {
    prevent_destroy = true
  }
}
