# ==============================================================================
# Google Secret Manager - Zero-Plaintext Secret Storage
# Conditional on var.enable_secrets (zero cost when disabled)
# ==============================================================================

resource "google_project_service" "secretmanager" {
  count              = var.enable_secrets ? 1 : 0
  project            = var.project
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

locals {
  use_cmek = var.enable_secrets && var.enable_cmek && length(google_kms_crypto_key.secrets_key) > 0
}

# 1. NGC API Key Secret
resource "google_secret_manager_secret" "ngc_api_key" {
  count     = var.enable_secrets && var.ngc_api_key != "" ? 1 : 0
  secret_id = "${var.prefix}-${var.deployment_name}-ngc-api-key"
  project   = var.project

  dynamic "replication" {
    for_each = local.use_cmek ? [1] : []
    content {
      user_managed {
        replicas {
          location = local.region
          customer_managed_encryption {
            kms_key_name = google_kms_crypto_key.secrets_key[0].id
          }
        }
      }
    }
  }

  dynamic "replication" {
    for_each = local.use_cmek ? [] : [1]
    content {
      automatic = true
    }
  }

  labels = {
    deployment = var.deployment_name
    managed_by = "isaac-automator"
  }

  depends_on = [
    google_kms_crypto_key_iam_member.secretmanager_cmek,
    google_project_service.secretmanager
  ]
}

resource "google_secret_manager_secret_version" "ngc_api_key_val" {
  count       = var.enable_secrets && var.ngc_api_key != "" ? 1 : 0
  secret      = google_secret_manager_secret.ngc_api_key[0].id
  secret_data = var.ngc_api_key
}

# 2. Hugging Face Token Secret
resource "google_secret_manager_secret" "hf_token" {
  count     = var.enable_secrets && var.hf_token != "" ? 1 : 0
  secret_id = "${var.prefix}-${var.deployment_name}-hf-token"
  project   = var.project

  dynamic "replication" {
    for_each = local.use_cmek ? [1] : []
    content {
      user_managed {
        replicas {
          location = local.region
          customer_managed_encryption {
            kms_key_name = google_kms_crypto_key.secrets_key[0].id
          }
        }
      }
    }
  }

  dynamic "replication" {
    for_each = local.use_cmek ? [] : [1]
    content {
      automatic = true
    }
  }

  labels = {
    deployment = var.deployment_name
    managed_by = "isaac-automator"
  }

  depends_on = [
    google_kms_crypto_key_iam_member.secretmanager_cmek,
    google_project_service.secretmanager
  ]
}

resource "google_secret_manager_secret_version" "hf_token_val" {
  count       = var.enable_secrets && var.hf_token != "" ? 1 : 0
  secret      = google_secret_manager_secret.hf_token[0].id
  secret_data = var.hf_token
}
