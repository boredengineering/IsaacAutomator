resource "google_artifact_registry_repository_iam_member" "reader" {
  count      = var.enable_artifact_registry ? 1 : 0
  project    = var.artifact_registry_project
  location   = var.artifact_registry_location
  repository = var.artifact_registry_repository
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.workstation_sa[0].email}"

  lifecycle {
    precondition {
      condition = (
        can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.artifact_registry_project)) &&
        can(regex("^[a-z]+-[a-z]+[0-9]+$", var.artifact_registry_location)) &&
        can(regex("^[a-z][a-z0-9_-]{0,62}$", var.artifact_registry_repository))
      )
      error_message = "Enabled Artifact Registry requires an explicit project ID, regional location, and repository ID."
    }
  }
}
