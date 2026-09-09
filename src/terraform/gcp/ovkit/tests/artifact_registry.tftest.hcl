# All providers are mocked: no credentials, metadata, or GCP calls.
mock_provider "google" {}


variables {
  prefix             = "test-workstation"
  deployment_name    = "test"
  public_key_openssh = "ssh-rsa offline-test"
  instance_type      = "g2-standard-4"
  gpu_count          = 1
  gpu_type           = "nvidia-l4"
  ssh_port           = 22
  ingress_cidrs      = ["192.0.2.0/24"]
  boot_disk_type     = "pd-ssd"
  os_username        = "ubuntu"
  region             = "us-central1"
  image_project      = "vm-project"
  project            = "vm-project"
}

run "disabled_simple" {
  command = plan
  assert {
    condition     = length(google_service_account.workstation_sa) == 0 && length(google_artifact_registry_repository_iam_member.reader) == 0
    error_message = "Disabled simple mode must not add a service account or registry IAM."
  }
  assert {
    condition     = !contains(google_compute_instance.default.service_account[0].scopes, "cloud-platform")
    error_message = "Disabled simple mode must retain existing scopes."
  }
}

run "enabled_simple_cross_project" {
  command = plan
  variables {
    enable_artifact_registry     = true
    artifact_registry_project    = "images-project"
    artifact_registry_location   = "us-west1"
    artifact_registry_repository = "workloads"
  }
  assert {
    condition     = length(google_service_account.workstation_sa) == 1 && google_service_account.workstation_sa[0].project == "vm-project"
    error_message = "Registry access requires the dedicated SA actually attached to the VM."
  }
  assert {
    condition     = contains(google_compute_instance.default.service_account[0].scopes, "cloud-platform")
    error_message = "Registry pulls need cloud-platform OAuth scope."
  }
  assert {
    condition     = google_artifact_registry_repository_iam_member.reader[0].role == "roles/artifactregistry.reader"
    error_message = "Reader IAM must name the attached VM identity."
  }
  assert {
    condition     = google_artifact_registry_repository_iam_member.reader[0].project == "images-project" && google_artifact_registry_repository_iam_member.reader[0].location == "us-west1" && google_artifact_registry_repository_iam_member.reader[0].repository == "workloads"
    error_message = "Reader IAM must be scoped to the explicit existing cross-project repository."
  }
}

run "enabled_team" {
  command = plan
  variables {
    security_profile             = "team"
    enable_artifact_registry     = true
    artifact_registry_project    = "images-project"
    artifact_registry_location   = "us-central1"
    artifact_registry_repository = "workloads"
  }
  assert {
    condition     = length(google_service_account.workstation_sa) == 1 && length(google_artifact_registry_repository_iam_member.reader) == 1 && contains(google_compute_instance.default.service_account[0].scopes, "cloud-platform")
    error_message = "Team tier must receive a dedicated identity, reader IAM and cloud-platform scopes."
  }
}

run "enabled_enterprise" {
  command = plan
  variables {
    security_profile             = "enterprise"
    enable_artifact_registry     = true
    artifact_registry_project    = "images-project"
    artifact_registry_location   = "us-central1"
    artifact_registry_repository = "workloads"
  }
  assert {
    condition     = length(google_service_account.workstation_sa) == 1 && length(google_artifact_registry_repository_iam_member.reader) == 1 && contains(google_compute_instance.default.service_account[0].scopes, "cloud-platform")
    error_message = "Enterprise must reuse the existing dedicated identity, not create a second account."
  }
}

run "disabled_enterprise" {
  command = plan
  variables {
    security_profile = "enterprise"
  }
  assert {
    condition     = length(google_service_account.workstation_sa) == 1 && length(google_artifact_registry_repository_iam_member.reader) == 0
    error_message = "Disabled enterprise retains its dedicated SA without registry IAM."
  }
}

run "reject_missing_project" {
  command = plan
  variables {
    enable_artifact_registry     = true
    artifact_registry_location   = "us-central1"
    artifact_registry_repository = "workloads"
  }
  expect_failures = [google_artifact_registry_repository_iam_member.reader]
}

run "reject_missing_location" {
  command = plan
  variables {
    enable_artifact_registry     = true
    artifact_registry_project    = "images-project"
    artifact_registry_repository = "workloads"
  }
  expect_failures = [google_artifact_registry_repository_iam_member.reader]
}
