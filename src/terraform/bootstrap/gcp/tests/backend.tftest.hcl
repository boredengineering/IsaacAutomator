mock_provider "google" {}

variables {
  project              = "example-project"
  region               = "us-central1"
  state_bucket_name    = "example-state-test"
  controller_principal = "serviceAccount:controller@example-project.iam.gserviceaccount.com"
}

run "protected_storage" {
  command = plan
  assert {
    condition     = !google_storage_bucket.state_bucket.force_destroy && google_storage_bucket.state_bucket.versioning[0].enabled
    error_message = "Retain state versions and refuse force deletion."
  }
  assert {
    condition     = google_storage_bucket.state_bucket.uniform_bucket_level_access && google_storage_bucket.state_bucket.public_access_prevention == "enforced"
    error_message = "No public or per-object ACL access."
  }
  assert {
    condition     = google_storage_bucket.state_bucket.soft_delete_policy[0].retention_duration_seconds == 604800
    error_message = "Retain seven days of soft-deleted state."
  }
  assert {
    condition     = google_storage_bucket_iam_member.controller.member == var.controller_principal && google_storage_bucket_iam_member.controller.role == "roles/storage.objectAdmin"
    error_message = "Explicit controller gets bucket-scoped object permissions only."
  }
}

run "reject_public_principal" {
  command = plan
  variables {
    controller_principal = "allUsers"
  }
  expect_failures = [var.controller_principal]
}

run "existing_cmek" {
  command = plan
  variables {
    kms_key_name = "projects/example-project/locations/us-central1/keyRings/backend/cryptoKeys/state"
  }
  assert {
    condition     = google_storage_bucket.state_bucket.encryption[0].default_kms_key_name == var.kms_key_name
    error_message = "Use only explicitly selected existing CMEK."
  }
}
