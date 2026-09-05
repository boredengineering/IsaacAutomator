# ==============================================================================
# Cloud Key Management Service (KMS) - Customer-Managed Encryption Keys (CMEK)
# Strictly conditional on var.enable_cmek (zero cost when disabled)
# ==============================================================================

resource "google_project_service" "kms" {
  count              = var.enable_cmek ? 1 : 0
  project            = var.project
  service            = "cloudkms.googleapis.com"
  disable_on_destroy = false
}

data "google_project" "current" {
  project_id = var.project
}

# Regional KMS Key Ring
resource "google_kms_key_ring" "workstation_keyring" {
  count      = var.enable_cmek ? 1 : 0
  name       = "${var.prefix}-${var.deployment_name}-keyring"
  location   = local.region
  project    = var.project
  depends_on = [google_project_service.kms]
}

# 1. CryptoKey for Compute Engine Boot & Persistent Disks
resource "google_kms_crypto_key" "compute_disk_key" {
  count           = var.enable_cmek ? 1 : 0
  name            = "compute-disk-key"
  key_ring        = google_kms_key_ring.workstation_keyring[0].id
  rotation_period = "7776000s" # 90 days

  lifecycle {
    prevent_destroy = true
  }
}

# 2. CryptoKey for Cloud Storage (Terraform State & Backups)
resource "google_kms_crypto_key" "storage_key" {
  count           = var.enable_cmek ? 1 : 0
  name            = "storage-key"
  key_ring        = google_kms_key_ring.workstation_keyring[0].id
  rotation_period = "7776000s"

  lifecycle {
    prevent_destroy = true
  }
}

# 3. CryptoKey for Secret Manager Secrets
resource "google_kms_crypto_key" "secrets_key" {
  count           = var.enable_cmek ? 1 : 0
  name            = "secrets-key"
  key_ring        = google_kms_key_ring.workstation_keyring[0].id
  rotation_period = "7776000s"

  lifecycle {
    prevent_destroy = true
  }
}

# ------------------------------------------------------------------------------
# Service Agent IAM Grants (Required for CMEK Decryption)
# ------------------------------------------------------------------------------

# A. Compute Engine Service Agent
resource "google_kms_crypto_key_iam_member" "compute_cmek" {
  count         = var.enable_cmek ? 1 : 0
  crypto_key_id = google_kms_crypto_key.compute_disk_key[0].id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.current.number}@compute-system.iam.gserviceaccount.com"
}

# B. Cloud Storage Service Agent
data "google_storage_project_service_account" "gcs_account" {
  count   = var.enable_cmek ? 1 : 0
  project = var.project
}

resource "google_kms_crypto_key_iam_member" "storage_cmek" {
  count         = var.enable_cmek ? 1 : 0
  crypto_key_id = google_kms_crypto_key.storage_key[0].id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${data.google_storage_project_service_account.gcs_account[0].email_address}"
}

# C. Secret Manager Service Agent
resource "google_kms_crypto_key_iam_member" "secretmanager_cmek" {
  count         = var.enable_cmek ? 1 : 0
  crypto_key_id = google_kms_crypto_key.secrets_key[0].id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-secretmanager.iam.gserviceaccount.com"
}
