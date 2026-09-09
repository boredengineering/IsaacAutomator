mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project    = "images-project"
  location   = "us-central1"
  repository = "workloads"
}

run "protected_docker_repository" {
  command = plan
  assert {
    condition     = google_artifact_registry_repository.images.format == "DOCKER" && google_artifact_registry_repository.images.project == "images-project" && google_artifact_registry_repository.images.location == "us-central1"
    error_message = "Create a regional Docker repository in the explicit images project."
  }
  assert {
    condition     = !google_project_service.artifact_registry.disable_on_destroy
    error_message = "Shared API must survive removal from state."
  }
  assert {
    condition     = length(google_artifact_registry_repository_iam_member.publisher) == 0 && length(google_kms_crypto_key_iam_member.artifact_registry) == 0 && length(google_project_service_identity.artifact_registry) == 0
    error_message = "No publisher or CMEK grants by default."
  }
  assert {
    condition     = output.repository_url == "us-central1-docker.pkg.dev/images-project/workloads"
    error_message = "Export the image repository URL for consumers."
  }
}

run "existing_cmek_and_scoped_publishers" {
  command = plan
  variables {
    kms_key_name      = "projects/keys-project/locations/us-central1/keyRings/images/cryptoKeys/images"
    publisher_members = ["serviceAccount:publisher@images-project.iam.gserviceaccount.com"]
  }
  assert {
    condition     = google_artifact_registry_repository.images.kms_key_name == var.kms_key_name && google_kms_crypto_key_iam_member.artifact_registry[0].crypto_key_id == var.kms_key_name
    error_message = "Use the supplied existing CMEK key, never a workstation key."
  }
  assert {
    condition     = google_kms_crypto_key_iam_member.artifact_registry[0].role == "roles/cloudkms.cryptoKeyEncrypterDecrypter" && google_project_service_identity.artifact_registry[0].project == "images-project" && google_project_service_identity.artifact_registry[0].service == "artifactregistry.googleapis.com"
    error_message = "Grant key use to the registry service identity in the registry project."
  }
  assert {
    condition     = length(google_artifact_registry_repository_iam_member.publisher) == 1 && alltrue([for p in google_artifact_registry_repository_iam_member.publisher : p.role == "roles/artifactregistry.writer" && p.project == "images-project" && p.location == "us-central1" && p.repository == "workloads" && p.member == "serviceAccount:publisher@images-project.iam.gserviceaccount.com"])
    error_message = "Publishers get repository-scoped writer only."
  }
}
