mock_provider "google" {}
mock_provider "tls" {}

variables {
  prefix                          = "test"
  deployment_name                 = "offline"
  project                         = "vm-project"
  zone                            = "us-central1-a"
  ssh_port                        = 22
  ingress_cidrs                   = ["192.0.2.0/24"]
  isaac_workstation_enabled       = true
  isaac_workstation_instance_type = "g2-standard-4"
  isaac_workstation_gpu_count     = 1
  isaac_workstation_gpu_type      = "nvidia-l4"
}

run "disabled_has_no_registry_api" {
  command = plan
  assert {
    condition     = length(google_project_service.artifact_registry) == 0
    error_message = "Disabled mode must not enable registry services."
  }
}

run "enabled_cross_project" {
  command = plan
  variables {
    enable_artifact_registry     = true
    artifact_registry_project    = "images-project"
    artifact_registry_location   = "us-west1"
    artifact_registry_repository = "workloads"
    security_profile             = "team"
  }
  assert {
    condition     = google_project_service.artifact_registry[0].project == "images-project" && google_project_service.artifact_registry[0].service == "artifactregistry.googleapis.com" && !google_project_service.artifact_registry[0].disable_on_destroy
    error_message = "Enable the API in the repository's project and never disable it on workstation destruction."
  }
}

# Check root validation even when the workstation module is not instantiated.
run "reject_implicit_project" {
  command = plan
  variables {
    isaac_workstation_enabled    = false
    enable_artifact_registry     = true
    artifact_registry_location   = "us-central1"
    artifact_registry_repository = "workloads"
  }
  expect_failures = [google_project_service.artifact_registry]
}

run "reject_missing_repository" {
  command = plan
  variables {
    isaac_workstation_enabled  = false
    enable_artifact_registry   = true
    artifact_registry_project  = "images-project"
    artifact_registry_location = "us-central1"
  }
  expect_failures = [google_project_service.artifact_registry]
}
