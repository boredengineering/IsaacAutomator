# Generate the registry service agent before granting access to an existing key.
resource "google_project_service_identity" "artifact_registry" {
  provider = google-beta
  count    = var.kms_key_name != "" ? 1 : 0
  project  = var.project
  service  = "artifactregistry.googleapis.com"

  depends_on = [google_project_service.artifact_registry]
}

resource "google_kms_crypto_key_iam_member" "artifact_registry" {
  count         = var.kms_key_name != "" ? 1 : 0
  crypto_key_id = var.kms_key_name
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_project_service_identity.artifact_registry[0].email}"
}

# Additive membership: do not replace existing readers or other publishers.
resource "google_artifact_registry_repository_iam_member" "publisher" {
  for_each   = var.publisher_members
  project    = google_artifact_registry_repository.images.project
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.repository_id
  role       = "roles/artifactregistry.writer"
  member     = each.value
}
