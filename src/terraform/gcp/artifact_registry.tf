# Only consume an existing repository. Its lifecycle belongs to registry/gcp.
resource "google_project_service" "artifact_registry" {
  count              = var.enable_artifact_registry ? 1 : 0
  project            = var.artifact_registry_project
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false

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
