output "repository_id" {
  description = "Fully qualified resource ID for repository-scoped IAM."
  value       = google_artifact_registry_repository.images.id
}

output "project" {
  value = var.project
}

output "location" {
  value = var.location
}

output "repository" {
  value = var.repository
}

output "repository_url" {
  description = "Docker repository URL; append image@sha256:digest for consumers."
  value       = "${var.location}-docker.pkg.dev/${var.project}/${var.repository}"
}
